"""Department agent graph -- one ReAct loop over load_skill and shell_executor

    START → agent ⇄ tools
              ↓ (no tool call)
            finish → END

Provides:
- build_department_graph:   compile the agent of one department, bound to its data file
- run_department_task:      run one dispatched task to a result dict; never raises

Key constraints:
- the agent only ever sees aggregated skill results; the egress guard in
  finish checks the conclusion before it is returned
- at the last allowed iteration the model is called without tools, so it
  has to write its conclusion instead of starting new work
- the result dict is the only thing that leaves the department:
  {"task_id", "department", "status", "summary", "egress", "iterations", "tokens", "elapsed_seconds"}
"""

import json
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from core.agents.model import chat_model, invoke
from core.agents.state import DepartmentState
from core.departments.base import DepartmentSpec
from core.middlewares.egress_guard import apply_egress_guard
from core.prompts.system_prompt_department import render_department_prompt
from core.tools.bundles.department import build_department_tools
from utils import console
from utils.logging import get_logger

logger = get_logger(__name__)

MAX_ITERATIONS = 16
FINAL_TURN_PROMPT = "You have used your analysis budget. Write your final answer now, without tool calls."


def _text(message: AIMessage) -> str:
    """The text of a model reply, whatever shape its content has."""
    if isinstance(message.content, str):
        return message.content
    return "".join(part.get("text", "") for part in message.content if isinstance(part, dict))


def _describe_call(call: dict) -> str:
    """One console line for a tool call."""
    if call["name"] == "shell_executor":
        return f"$ {call['args'].get('command', '')}"
    return f"{call['name']}({', '.join(f'{k}={v}' for k, v in call['args'].items())})"


def _describe_result(content: str) -> tuple[str, str]:
    """One console line and a color for a tool result."""
    try:
        result = json.loads(content)
    except (TypeError, ValueError):
        return console.preview(content), "grey"
    status = result.get("status", "?")
    color = {"ok": "green", "error": "yellow", "denied": "red"}.get(status, "grey")
    detail = result.get("message") or result.get("skill", "")
    rows = f", {len(result['rows'])} rows" if isinstance(result.get("rows"), list) and result["rows"] else ""
    return f"→ {status}{rows}: {console.preview(detail, 120)}", color


def build_department_graph(spec: DepartmentSpec, data_path: str):
    """Compile the agent of one department.

    Args:
        spec:       the department.
        data_path:  its view on this device.
    """
    tools = build_department_tools(spec, data_path)
    model = chat_model()
    model_with_tools = model.bind_tools(tools)
    system_prompt = render_department_prompt(spec)
    tool_node = ToolNode(tools)

    async def agent(state: DepartmentState) -> dict:
        tag = f"{spec.name} · {state['task']['task_id']}"
        final_turn = state["iteration"] + 1 >= MAX_ITERATIONS
        messages = [SystemMessage(system_prompt), *state["messages"]]
        if final_turn:
            messages.append(HumanMessage(FINAL_TURN_PROMPT))
        response = await invoke(model if final_turn else model_with_tools, messages, role=spec.name)
        for call in response.tool_calls:
            console.say(tag, _describe_call(call), "cyan")
        usage = response.usage_metadata or {}
        return {"messages": [response], "iteration": state["iteration"] + 1, "tokens": usage.get("total_tokens", 0)}

    async def tools_step(state: DepartmentState, config) -> dict:
        tag = f"{spec.name} · {state['task']['task_id']}"
        update = await tool_node.ainvoke(state, config)
        for message in update["messages"]:
            line, color = _describe_result(message.content)
            console.say(tag, line, color)
        return update

    async def finish(state: DepartmentState) -> dict:
        task = state["task"]
        last = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and _text(m).strip()), None)
        text = _text(last).strip() if last else "The department agent produced no conclusion."
        verdict = apply_egress_guard(text, spec, data_path)
        return {"result": {
            "task_id": task["task_id"],
            "department": spec.name,
            "status": "success" if last else "failed",
            "summary": verdict.text,
            "egress": verdict.action,
            "iterations": state["iteration"],
            "tokens": state["tokens"],
        }}

    def route(state: DepartmentState) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else "finish"

    builder = StateGraph(DepartmentState)
    builder.add_node("agent", agent)
    builder.add_node("tools", tools_step)
    builder.add_node("finish", finish)
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", route, ["tools", "finish"])
    builder.add_edge("tools", "agent")
    builder.add_edge("finish", END)
    return builder.compile()


async def run_department_task(graph, spec: DepartmentSpec, task: dict) -> dict:
    """Run one dispatched task and return the department's result.

    Any failure becomes a result with status "failed", so the orchestrator
    can report the gap instead of crashing.
    """
    t_start = time.time()
    try:
        final = await graph.ainvoke(
            {"task": task, "messages": [HumanMessage(task["question"])], "iteration": 0, "tokens": 0, "result": {}},
            config={"recursion_limit": 2 * MAX_ITERATIONS + 5},
        )
        result = dict(final["result"])
    except Exception as exc:
        logger.error("department_task_failed", department=spec.name, task_id=task["task_id"], error=str(exc)[:300])
        result = {"task_id": task["task_id"], "department": spec.name, "status": "failed",
                  "summary": f"The {spec.name} agent failed: {exc.__class__.__name__}: {str(exc)[:300]}"}
    result["elapsed_seconds"] = round(time.time() - t_start, 1)
    return result
