"""Department agent graph -- a ReAct loop over file, bash, skill and plan tools,
with the device owner in the loop

    START → intake ⏸ ──(declined)──────────────────────────┐
              ↓                                            │
            agent ⇄ tools ──(blocked on private/)→ access ⏸ │
              ↓ (no tool call)          ↑__________↓       │
            finish → deliver ⏸ → END ←─────────────────────┘

⏸ = LangGraph interrupt: the graph stops and the agent process asks the
person at the device (distributed/approval.py), then resumes with True / False.

Provides:
- build_department_graph:   compile the agent of one department
- run_department_task:      run one dispatched task to a result dict, answering the pauses; never raises

Key constraints:
- every file and bash tool is bound to the department's AccessPolicy:
  its shared/ data (as data/) read-only, its workspace read/write; the
  restricted private/ folder opens only after the owner approves, for this
  task only, and is asked about at most once per task
- tool calls of one turn run in order; plan calls update the agent's plan
- bash only runs after the agent has loaded at least one skill in this task,
  so the methods in the skills are actually used
- at the last allowed iteration the model is called without tools, so it
  has to write its conclusion
- finish runs the egress guard, deliver lets the owner withhold the result;
  the result dict is the only thing that leaves the department:
  {"task_id", "department", "status", "summary", "egress", "iterations", "tokens", "elapsed_seconds"}
  status: success / failed / declined (the owner refused the task or withheld the result)
- interrupts only happen in intake, access and deliver, which have no side
  effects before the pause, so re-running them on resume is safe
"""

import dataclasses
import os
import time
import uuid

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import get_async_callback_manager_for_config
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from core.agents.model import chat_model, invoke
from core.agents.state import DepartmentState
from core.departments import DepartmentCard
from core.middlewares.egress_guard import apply_egress_guard
from core.prompts.system_prompt_department import render_department_prompt, render_department_snapshot
from core.tools._kernel._access import AccessPolicy
from core.tools._kernel.sandbox.docker_runner import container_path
from core.tools.bundles.files import build_file_tools
from core.tools.bundles.plan import PLAN_TOOL_NAMES, PLAN_TOOL_SPECS, run_plan_tool
from utils import console
from utils.logging import get_logger
from utils.runtime import portable_relative_path

logger = get_logger(__name__)

MAX_ITERATIONS = 24
FINAL_TURN_PROMPT = "You have used your budget. Write your final answer now, without tool calls."
SKILL_FIRST = ("Not run: load the skill(s) that fit this question with load_skill before running commands - "
               "they contain the methods to use (see <AVAILABLE_SKILLS>). Then run your command again.")
ACCESS_GRANTED = ("The device owner opened the restricted folder {path} for this task. Run the blocked call again. "
                  "Its data stays on this device: report aggregates only.")
ACCESS_DENIED = ("The device owner kept the restricted folder {path} closed. Do not try it again; answer with the "
                 "data you have and name the gap in your caveats.")
TASK_DECLINED = "The device owner declined this task; no analysis was run on this device."
RESULT_WITHHELD = "The device owner reviewed the conclusion and withheld it; nothing was sent from this device."
PATH_TOOLS = ("view_file", "glob_tool", "grep_tool")


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


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def build_department_graph(card: DepartmentCard, policy: AccessPolicy):
    """Compile the agent of one department.

    Args:
        card:       the department card.
        policy:     its access policy (workspace + shared data).
    """
    tools = build_file_tools(policy, with_bash=True, skills_for=card.name)
    model = chat_model()
    model_with_tools = model.bind_tools([*tools, *PLAN_TOOL_SPECS])
    system_prompt = render_department_prompt(card, policy)
    restricted = os.path.realpath(card.private_dir) if os.path.isdir(card.private_dir) else ""
    restricted_rel = portable_relative_path(restricted, policy.workspace) if restricted else ""

    def blocked_on_restricted(call: dict, content: str, active: AccessPolicy) -> bool:
        """Whether a tool call was refused because it reached into the restricted folder."""
        if not restricted:
            return False
        if call["name"] in PATH_TOOLS and content.startswith("Access denied"):
            return _inside(active.resolve(call["args"].get("path", ".")), restricted)
        # Seatbelt denies the read; Docker leaves unapproved private/ unmounted.
        return (call["name"] == "bash"
                and any(error in content for error in ("Operation not permitted", "Permission denied", "No such file or directory"))
                and any(path in content for path in (restricted, restricted_rel, container_path(restricted))))

    def ask(kind: str, task: dict, title: str, text: str) -> bool:
        """Pause the graph until the device owner answers."""
        return interrupt({"kind": kind, "task_id": task["task_id"], "department": card.name,
                          "title": f"{card.display_name} · {title}", "text": text}) is True

    async def intake(state: DepartmentState) -> dict:
        task = state["task"]
        if ask("task", task, "run this task?",
               f"The orchestrator asks (task {task['task_id']}):\n\n{task['question']}\n\n"
               "Run it on this device's data?"):
            return {}
        return {"result": {"task_id": task["task_id"], "department": card.name, "status": "declined",
                           "summary": TASK_DECLINED, "egress": "none", "iterations": 0, "tokens": 0}}

    async def agent(state: DepartmentState, config: RunnableConfig) -> dict:
        tag = f"{card.name} · {state['task']['task_id']}"
        final_turn = state["iteration"] + 1 >= MAX_ITERATIONS
        messages = [SystemMessage(system_prompt), *state["messages"],
                    HumanMessage(render_department_snapshot(state["plan"], state["iteration"], MAX_ITERATIONS))]
        if final_turn:
            messages.append(HumanMessage(FINAL_TURN_PROMPT))
        response = await invoke(model if final_turn else model_with_tools, messages, role=card.name, config=config)
        for call in response.tool_calls:
            console.say(tag, _describe_call(call), "cyan")
        usage = response.usage_metadata or {}
        return {"messages": [response], "iteration": state["iteration"] + 1, "tokens": usage.get("total_tokens", 0)}

    async def tools_step(state: DepartmentState, config: RunnableConfig) -> dict:
        tag = f"{card.name} · {state['task']['task_id']}"
        # 主人批准过的受限目录只对本次任务开放：每一步按当前授权重新绑定工具
        active = dataclasses.replace(policy, read_roots=(*policy.read_roots, *state.get("grants", [])))
        tools_by_name = {t.name: t for t in build_file_tools(active, with_bash=True, skills_for=card.name)}
        work = {"plan": list(state["plan"])}
        results, blocked = [], []
        # 小模型容易跳过 Skill 直接写代码：本次任务还没加载过任何 Skill 时，bash 先不执行
        skill_loaded = any(isinstance(m, ToolMessage) and m.name == "load_skill" for m in state["messages"])
        for call in state["messages"][-1].tool_calls:
            direct = call["name"] in PLAN_TOOL_NAMES or call["name"] not in tools_by_name or (call["name"] == "bash" and not skill_loaded)
            run = None
            if direct:
                manager = get_async_callback_manager_for_config(config)
                run = await manager.on_tool_start({"name": call["name"]}, str(call["args"]),
                                                  inputs=call["args"], tool_call_id=call["id"])
            if call["name"] == "load_skill":
                skill_loaded = True
            if call["name"] == "bash" and not skill_loaded:
                content = SKILL_FIRST
            elif call["name"] in PLAN_TOOL_NAMES:
                content = run_plan_tool(call["name"], call["args"], work)
            elif call["name"] in tools_by_name:
                try:
                    content = str(await tools_by_name[call["name"]].ainvoke(call["args"], config=config))
                except Exception as exc:
                    content = f"Error: {exc.__class__.__name__}: {str(exc)[:300]}"
            else:
                content = f"Error: unknown tool {call['name']!r}"
            if run:
                await run.on_tool_end(content)
            if blocked_on_restricted(call, content, active):
                blocked.append(_describe_call(call))
            line, color = _describe_result(content)
            console.say(tag, line, color)
            results.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))
        return {"messages": results, "plan": work["plan"], "blocked": blocked}

    async def access(state: DepartmentState) -> dict:
        task = state["task"]
        attempts = "\n".join(f"- {console.preview(b, 160)}" for b in state["blocked"])
        if ask("access", task, "open restricted data?",
               f"The agent working on task {task['task_id']} tried to read the restricted folder "
               f"private/:\n{attempts}\n\nQuestion: {console.preview(task['question'], 400)}\n\n"
               "Open private/ to the agent for this task only?"):
            return {"access": "granted", "grants": [restricted], "blocked": [],
                    "messages": [HumanMessage(ACCESS_GRANTED.format(path=restricted_rel))]}
        return {"access": "denied", "blocked": [], "messages": [HumanMessage(ACCESS_DENIED.format(path=restricted_rel))]}

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

    async def deliver(state: DepartmentState) -> dict:
        result = state["result"]
        if result["status"] != "success":
            return {}
        if ask("deliver", state["task"], "send this conclusion?",
               f"Conclusion for task {result['task_id']} (egress guard: {result['egress']}):\n\n"
               f"{result['summary']}\n\nSend it to the orchestrator?"):
            return {}
        return {"result": {**result, "status": "declined", "summary": RESULT_WITHHELD, "egress": "withheld"}}

    def after_intake(state: DepartmentState) -> str:
        return END if state["result"] else "agent"

    def route(state: DepartmentState) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else "finish"

    def after_tools(state: DepartmentState) -> str:
        return "access" if state["blocked"] and not state["access"] else "agent"

    builder = StateGraph(DepartmentState)
    builder.add_node("intake", intake)
    builder.add_node("agent", agent)
    builder.add_node("tools", tools_step)
    builder.add_node("access", access)
    builder.add_node("finish", finish)
    builder.add_node("deliver", deliver)
    builder.add_edge(START, "intake")
    builder.add_conditional_edges("intake", after_intake, ["agent", END])
    builder.add_conditional_edges("agent", route, ["tools", "finish"])
    builder.add_conditional_edges("tools", after_tools, ["access", "agent"])
    builder.add_edge("access", "agent")
    builder.add_edge("finish", "deliver")
    builder.add_edge("deliver", END)
    # interrupt 需要 checkpointer 才能暂停后续跑；每个任务一个 thread，跑完就删
    return builder.compile(checkpointer=InMemorySaver())


async def run_department_task(graph, card: DepartmentCard, task: dict, ask_owner=None, *, callbacks=None) -> dict:
    """Run one dispatched task and return the department's result.

    Every pause of the graph goes to ask_owner(request) -> bool; without one,
    everything is approved. Any failure becomes a result with status
    "failed", so the orchestrator can report the gap instead of crashing.
    """
    t_start = time.time()
    thread_id = f"{task['task_id']}-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 2 * MAX_ITERATIONS + 10}
    if callbacks:
        config.update(callbacks=callbacks, metadata={"department": card.name, "task_id": task["task_id"]})
    step = {"task": task, "messages": [HumanMessage(task["question"])], "plan": [], "iteration": 0,
            "tokens": 0, "result": {}, "grants": [], "access": "", "blocked": []}
    try:
        while True:
            final = await graph.ainvoke(step, config=config)
            pauses = final.get("__interrupt__")
            if not pauses:
                break
            step = Command(resume=await ask_owner(pauses[0].value) if ask_owner else True)
        result = dict(final["result"])
    except Exception as exc:
        logger.error("department_task_failed", department=card.name, task_id=task["task_id"], error=str(exc)[:300])
        result = {"task_id": task["task_id"], "department": card.name, "status": "failed",
                  "summary": f"The {card.name} agent failed: {exc.__class__.__name__}: {str(exc)[:300]}"}
    finally:
        await graph.checkpointer.adelete_thread(thread_id)
    result["elapsed_seconds"] = round(time.time() - t_start, 1)
    return result
