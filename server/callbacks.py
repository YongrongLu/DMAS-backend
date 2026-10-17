"""One callback instance and queue per HTTP request; no shared run mappings."""

import asyncio
import json
import re
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from server.schemas import Delta, PlanSnapshot, ToolEvent, WorkflowEvent


def preview(value: Any) -> str:
    value = getattr(value, "content", value)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[:2000] + ("…" if len(text) > 2000 else "")


def structured(value: Any) -> dict | None:
    """Preserve JSON shape even when individual values need clipping."""
    value = getattr(value, "content", value)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return None
    if not isinstance(value, dict):
        return None

    def cap(item, depth=0):
        if depth > 6:
            return "…"
        if isinstance(item, str):
            return item[:2000] + ("…" if len(item) > 2000 else "")
        if isinstance(item, dict):
            return {str(k): cap(v, depth + 1) for k, v in list(item.items())[:50]}
        if isinstance(item, (list, tuple)):
            return [cap(v, depth + 1) for v in item[:50]]
        return item if item is None or isinstance(item, (bool, int, float)) else preview(item)

    return cap(value)


def tool_result(name: str, output: Any) -> tuple[dict | None, str | None]:
    text = getattr(output, "content", output)
    result = structured(text)
    error = None
    if result and result.get("status") == "error":
        error = str(result.get("message", "Tool execution failed"))
    if isinstance(text, str):
        if text.startswith(("Error:", "Access denied:")):
            error = text
        elif name == "bash":
            match = re.match(r"exit code (-?\d+)(?:\n|$)", text)
            if match:
                exit_code = int(match[1])
                sections = re.split(r"(?:^|\n)(stdout|stderr):\n", text[match.end():])
                result = {"exit_code": exit_code}
                for index in range(1, len(sections) - 1, 2):
                    result[sections[index]] = preview(sections[index + 1])
                if exit_code:
                    error = f"Command exited with code {exit_code}"
    return result, preview(error) if error else None


class CompletionCallbackHandler(AsyncCallbackHandler):
    """Relay the final report, tool lifecycles, and approved department events.

    Coordinator deliberation and department model tokens never become chat
    content. The service, rather than on_llm_end, owns terminal stream events.
    """

    def __init__(self, queue: asyncio.Queue):
        self.queue = queue
        self.content_sent = False
        self._models: dict[UUID, tuple[str, bool]] = {}
        self._tools: dict[UUID, dict] = {}

    async def put(self, delta: Delta) -> None:
        await self.queue.put(delta)

    async def text(self, content: str) -> None:
        if content:
            self.content_sent = self.content_sent or bool(content.strip())
            await self.put(Delta(content=content))

    async def on_chat_model_start(self, serialized, messages, *, run_id: UUID, metadata=None, **kwargs):
        node = (metadata or {}).get("langgraph_node", "")
        self._models[run_id] = (node, False)
        if node == "announce":
            await self.put(Delta(workflow=WorkflowEvent(type="phase", phase="reporting")))

    async def on_llm_new_token(self, token: str, *, run_id: UUID, **kwargs):
        node, sent = self._models.get(run_id, ("", False))
        if node == "announce" and token:
            self._models[run_id] = (node, True)
            await self.text(token)

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs):
        node, sent = self._models.pop(run_id, ("", False))
        if node == "announce" and not sent and response.generations and response.generations[0]:
            await self.text(response.generations[0][0].text)

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs):
        # The model layer can retry. Only an exception escaping the graph is
        # terminal; emitting one here would prematurely end a recoverable run.
        self._models.pop(run_id, None)

    async def on_tool_start(self, serialized, input_str, *, run_id: UUID, inputs=None, metadata=None, **kwargs):
        identity = {
            "id": str(kwargs.get("tool_call_id") or run_id),
            "name": (serialized or {}).get("name", "tool"),
            "agent": str((metadata or {}).get("department") or "orchestrator"),
        }
        self._tools[run_id] = identity
        await self.put(Delta(tool_event=ToolEvent(
            type="tool_start", **identity, input=preview(inputs if inputs is not None else input_str),
            arguments=structured(inputs if inputs is not None else input_str),
        )))

    async def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs):
        identity = self._tools.pop(run_id, None)
        if identity:
            result, error = tool_result(identity["name"], output)
            failed = getattr(output, "status", None) == "error" or error is not None
            await self.put(Delta(tool_event=ToolEvent(
                type="tool_error" if failed else "tool_end", **identity, result=result,
                output=preview(output), error=(error or preview(output)) if failed else None,
            )))

    async def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs):
        identity = self._tools.pop(run_id, None)
        if identity:
            await self.put(Delta(tool_event=ToolEvent(type="tool_error", **identity, error=preview(error))))

    async def on_custom_event(self, name: str, data: Any, *, run_id: UUID, **kwargs):
        if not isinstance(data, dict):
            return
        if name == "department_started":
            task = data["task"]
            await self.put(Delta(workflow=WorkflowEvent(
                type="department_start", task_id=task["task_id"], department=task["department"],
            )))
        elif name == "department_result":
            result = data["result"]
            await self.put(Delta(workflow=WorkflowEvent(
                type="department_end", task_id=result["task_id"],
                department=result["department"], status=result["status"],
            )))
        elif name == "handoff":
            await self.put(Delta(workflow=WorkflowEvent(type="phase", phase="merging")))
        elif name == "plan":
            await self.put(Delta(plan=PlanSnapshot(
                agent=str((kwargs.get("metadata") or {}).get("department") or "orchestrator"),
                phases=data.get("plan", []),
            )))
        elif name == "report" and not self.content_sent:
            await self.text(data.get("text", ""))
