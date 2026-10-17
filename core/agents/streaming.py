"""Streaming bridge -- LangGraph callbacks to a queue of frontend events

The orchestrator graph runs with an SSEBridge in config["callbacks"]. LangChain
calls the bridge for every model token, model call and tool call inside the
graph; graph nodes add structured events (plan, fanout, department results,
report) with emit(). Every event becomes one dict on an asyncio.Queue that
the SSE endpoint drains.

Event dicts always carry "type"; see docs/streaming-api.md for the schema.

Provides:
- SSEBridge:        AsyncCallbackHandler writing events to a queue
- emit:             send a structured event from inside a graph node

Key constraints:
- emit never raises: outside a callback context (CLI runs) it is a no-op
- department token streams never reach this bridge: departments only send
  progress events through the hub, so raw data cannot leak into the stream
"""

import asyncio
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.outputs import LLMResult

from utils.logging import get_logger

logger = get_logger(__name__)

PREVIEW_CHARS = 300


def _preview(value: Any, limit: int = PREVIEW_CHARS) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit] + "…"


async def emit(config, name: str, data: dict) -> None:
    """Send a structured event to every callback handler of the current run (no-op without one)."""
    try:
        await adispatch_custom_event(name, data, config=config)
    except Exception as exc:  # 不在回调上下文里（例如命令行运行）就直接忽略
        logger.debug("emit_skipped", event=name, error=str(exc)[:120])


class SSEBridge(AsyncCallbackHandler):
    """Turn LangGraph callbacks of one orchestration run into frontend events."""

    def __init__(self, queue: asyncio.Queue, run_id: str):
        self._queue = queue
        self._run_id = run_id
        # LangChain run id -> graph node of a model call / name of a tool call
        self._llm_nodes: dict[UUID, str] = {}
        self._tools: dict[UUID, str] = {}

    async def put(self, event: dict) -> None:
        """Queue one event, stamped with the orchestration run id."""
        await self._queue.put({"run_id": self._run_id, **event})

    async def on_chat_model_start(self, serialized, messages, *, run_id: UUID, parent_run_id=None, tags=None,
                                  metadata=None, **kwargs) -> None:
        node = (metadata or {}).get("langgraph_node", "")
        self._llm_nodes[run_id] = node
        await self.put({"type": "llm_start", "agent": "orchestrator", "node": node})

    async def on_llm_new_token(self, token: str, *, chunk=None, run_id: UUID, parent_run_id=None, tags=None,
                               **kwargs) -> None:
        if token:
            await self.put({"type": "token", "agent": "orchestrator", "node": self._llm_nodes.get(run_id, ""),
                            "text": token})

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, parent_run_id=None, tags=None, **kwargs) -> None:
        node = self._llm_nodes.pop(run_id, "")
        generation = response.generations[0][0] if response.generations and response.generations[0] else None
        message = getattr(generation, "message", None)
        tool_calls = [c["name"] for c in getattr(message, "tool_calls", None) or []]
        await self.put({"type": "llm_end", "agent": "orchestrator", "node": node,
                        "text": generation.text if generation else "", "tool_calls": tool_calls})

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, parent_run_id=None, tags=None,
                           **kwargs) -> None:
        node = self._llm_nodes.pop(run_id, "")
        await self.put({"type": "llm_error", "agent": "orchestrator", "node": node, "message": _preview(error)})

    async def on_tool_start(self, serialized, input_str: str, *, run_id: UUID, parent_run_id=None, tags=None,
                            metadata=None, inputs=None, **kwargs) -> None:
        name = (serialized or {}).get("name", "tool")
        self._tools[run_id] = name
        await self.put({"type": "tool_start", "agent": "orchestrator", "tool": name,
                        "input": _preview(inputs if inputs is not None else input_str)})

    async def on_tool_end(self, output: Any, *, run_id: UUID, parent_run_id=None, tags=None, **kwargs) -> None:
        name = self._tools.pop(run_id, "tool")
        await self.put({"type": "tool_end", "agent": "orchestrator", "tool": name,
                        "output": _preview(getattr(output, "content", output))})

    async def on_tool_error(self, error: BaseException, *, run_id: UUID, parent_run_id=None, tags=None,
                            **kwargs) -> None:
        name = self._tools.pop(run_id, "tool")
        await self.put({"type": "tool_error", "agent": "orchestrator", "tool": name, "message": _preview(error)})

    async def on_custom_event(self, name: str, data: Any, *, run_id: UUID, tags=None, metadata=None,
                              **kwargs) -> None:
        await self.put({"type": name, **(data if isinstance(data, dict) else {"data": data})})
