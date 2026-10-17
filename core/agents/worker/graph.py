"""Department agent graph -- a ReAct loop over file, bash, skill and plan tools

    START → agent ⇄ tools
              ↓ (no tool call)
            finish → END

Provides:
- build_department_graph:   compile the agent of one department
- run_department_task:      run one dispatched task to a result dict; never raises

Key constraints:
- every file and bash tool is bound to the department's AccessPolicy:
  its shared/ data (as data/) read-only, its workspace read/write
- tool calls of one turn run in order; plan calls update the agent's plan
- bash only runs after the agent has loaded at least one skill in this task,
  so the methods in the skills are actually used
- at the last allowed iteration the model is called without tools, so it
  has to write its conclusion
- finish runs the egress guard; the result dict is the only thing that
  leaves the department:
  {"task_id", "department", "status", "summary", "egress", "iterations", "tokens", "elapsed_seconds"}
"""

import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from core.agents.model import chat_model, invoke
from core.agents.state import DepartmentState
from core.departments import DepartmentCard
from core.middlewares.egress_guard import apply_egress_guard
from core.prompts.system_prompt_department import render_department_prompt, render_department_snapshot
from core.tools._kernel._access import AccessPolicy
from core.tools.bundles.files import build_file_tools
from core.tools.bundles.plan import PLAN_TOOL_NAMES, PLAN_TOOL_SPECS, run_plan_tool
from utils import console
from utils.logging import get_logger

logger = get_logger(__name__)

MAX_ITERATIONS = 24
FINAL_TURN_PROMPT = "You have used your budget. Write your final answer now, without tool calls."
SKILL_FIRST = ("Not run: load the skill(s) that fit this question with load_skill before running commands - "
               "they contain the methods to use (see <AVAILABLE_SKILLS>). Then run your command again.")


def _text(message: AIMessage) -> str:
    """The text of a model reply, whatever shape its content has."""
    if isinstance(message.content, str):
        return message.content
    return "".join(part.get("text", "") for part in message.content if isinstance(part, dict))


def _describe_call(call: dict) -> str:
    """One console line for a tool call."""
    args = call["args"]
    if call["name"] == "bash":
        return f"$ {console.preview(args.get('command', ''), 200)}"
    if call["name"] == "write_file":
        return f"write_file {args.get('path')} ({len(str(args.get('content', '')))} chars)"
    shown = ", ".join(f"{k}={console.preview(v, 60)}" for k, v in args.items())
    return f"{call['name']}({shown})"


def _describe_result(content: str) -> tuple[str, str]:
    """One console line and a color for a tool result."""
    first = content.strip().splitlines()[0] if content.strip() else ""
    color = "red" if first.startswith("Access denied") else "yellow" if first.startswith(("Error", "exit code 1", "exit code 2")) else "green"
    return f"→ {console.preview(first, 140)}", color


def build_department_graph(card: DepartmentCard, policy: AccessPolicy):
    """Compile the agent of one department.

    Args:
        card:       the department card.
        policy:     its access policy (workspace + shared data).
    """
    tools = build_file_tools(policy, with_bash=True, skills_for=card.name)
    tools_by_name = {t.name: t for t in tools}
    model = chat_model()
    model_with_tools = model.bind_tools([*tools, *PLAN_TOOL_SPECS])
    system_prompt = render_department_prompt(card, policy)

    async def agent(state: DepartmentState) -> dict:
        tag = f"{card.name} · {state['task']['task_id']}"
        final_turn = state["iteration"] + 1 >= MAX_ITERATIONS
        messages = [SystemMessage(system_prompt), *state["messages"],
                    HumanMessage(render_department_snapshot(state["plan"], state["iteration"], MAX_ITERATIONS))]
        if final_turn:
            messages.append(HumanMessage(FINAL_TURN_PROMPT))
        response = await invoke(model if final_turn else model_with_tools, messages, role=card.name)
        for call in response.tool_calls:
            console.say(tag, _describe_call(call), "cyan")
        usage = response.usage_metadata or {}
        return {"messages": [response], "iteration": state["iteration"] + 1, "tokens": usage.get("total_tokens", 0)}

    async def tools_step(state: DepartmentState) -> dict:
        tag = f"{card.name} · {state['task']['task_id']}"
        work = {"plan": list(state["plan"])}
        results = []
        # 小模型容易跳过 Skill 直接写代码：本次任务还没加载过任何 Skill 时，bash 先不执行
        skill_loaded = any(isinstance(m, ToolMessage) and m.name == "load_skill" for m in state["messages"])
        for call in state["messages"][-1].tool_calls:
            if call["name"] == "load_skill":
                skill_loaded = True
            if call["name"] == "bash" and not skill_loaded:
                content = SKILL_FIRST
            elif call["name"] in PLAN_TOOL_NAMES:
                content = run_plan_tool(call["name"], call["args"], work)
            elif call["name"] in tools_by_name:
                try:
                    content = str(await tools_by_name[call["name"]].ainvoke(call["args"]))
                except Exception as exc:
                    content = f"Error: {exc.__class__.__name__}: {str(exc)[:300]}"
            else:
                content = f"Error: unknown tool {call['name']!r}"
            line, color = _describe_result(content)
            console.say(tag, line, color)
            results.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))
        return {"messages": results, "plan": work["plan"]}

    async def finish(state: DepartmentState) -> dict:
        task = state["task"]
        last = next((m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and _text(m).strip()), None)
        text = _text(last).strip() if last else "The department agent produced no conclusion."
        verdict = apply_egress_guard(text, card)
        return {"result": {
            "task_id": task["task_id"],
            "department": card.name,
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


async def run_department_task(graph, card: DepartmentCard, task: dict) -> dict:
    """Run one dispatched task and return the department's result.

    Any failure becomes a result with status "failed", so the orchestrator
    can report the gap instead of crashing.
    """
    t_start = time.time()
    try:
        final = await graph.ainvoke(
            {"task": task, "messages": [HumanMessage(task["question"])], "plan": [], "iteration": 0,
             "tokens": 0, "result": {}},
            config={"recursion_limit": 2 * MAX_ITERATIONS + 5},
        )
        result = dict(final["result"])
    except Exception as exc:
        logger.error("department_task_failed", department=card.name, task_id=task["task_id"], error=str(exc)[:300])
        result = {"task_id": task["task_id"], "department": card.name, "status": "failed",
                  "summary": f"The {card.name} agent failed: {exc.__class__.__name__}: {str(exc)[:300]}"}
    result["elapsed_seconds"] = round(time.time() - t_start, 1)
    return result
