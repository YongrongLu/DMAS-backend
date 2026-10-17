"""Orchestrator nodes: decide, run control tools, write the final report

Provides:
- make_orchestrator_node:   the LLM step choosing the next control tool
- make_tools_node:          runs the step's tool calls in order on one working state
- make_announce_node:       streams the final report to the CEO
- get_hub:                  the agent hub from the run config

Key constraints:
- the system prompt never changes during a run; plan, budget and online
  departments travel in a runtime-state block appended to each request
- a reply without tool calls is taken as the handoff note, and the last
  turn binds only end_orchestration, so the run always reaches the report
- the report is written from the department results and the handoff note
  only, not from the orchestrator's raw history
"""

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import get_async_callback_manager_for_config

from core.agents.model import chat_model, invoke
from core.agents.state import OrchestrationState
from core.agents.streaming import emit
from core.prompts.system_prompt_announce import ANNOUNCE_PROMPT, render_announce_input
from core.prompts.system_prompt_orchestrator import ORCHESTRATOR_PROMPT, render_snapshot
from core.tools._kernel._access import orchestrator_policy
from core.tools.bundles.files import build_file_tools
from core.tools.bundles.orchestrator import CONTROL_TOOL_NAMES, CONTROL_TOOL_SPECS, END_TOOL_SPECS, run_control_tool
from utils import console
from utils.settings import settings

MAX_ITERATIONS = 14
HUB_CONFIG_KEY = "hub"
TAG = "orchestrator"


def get_hub(config: RunnableConfig):
    """The agent hub placed in config["configurable"] by the entry point."""
    hub = (config.get("configurable") or {}).get(HUB_CONFIG_KEY)
    if hub is None:
        raise RuntimeError("the orchestrator graph needs config['configurable']['hub']")
    return hub


def _text(message: AIMessage) -> str:
    """The text of a model reply."""
    if isinstance(message.content, str):
        return message.content
    return "".join(part.get("text", "") for part in message.content if isinstance(part, dict))


# orchestrator 自己的文件工具：只能操作 workspaces/orchestrator，看不到任何部门数据
FILE_TOOLS = build_file_tools(orchestrator_policy(), with_bash=False)
FILE_TOOLS_BY_NAME = {t.name: t for t in FILE_TOOLS}


def make_orchestrator_node():
    """The orchestrator's LLM step."""

    async def orchestrator(state: OrchestrationState, config: RunnableConfig) -> dict:
        departments = get_hub(config).department_cards()
        final_turn = state["iteration"] + 1 >= MAX_ITERATIONS
        model = chat_model().bind_tools(END_TOOL_SPECS if final_turn else [*CONTROL_TOOL_SPECS, *FILE_TOOLS])
        snapshot = render_snapshot(state["plan"], state["iteration"], MAX_ITERATIONS, departments)
        messages = [SystemMessage(ORCHESTRATOR_PROMPT), *state["messages"], HumanMessage(snapshot)]

        response = await invoke(model, messages, role=TAG, config=config)
        text = _text(response).strip()
        if text:
            console.say(TAG, console.preview(text, 300), "magenta")

        update = {"messages": [response], "iteration": state["iteration"] + 1}
        if not response.tool_calls:
            update["response"] = text or "Summarise the department findings for the user."
        return update

    return orchestrator


def _show_tool_result(name: str, work: dict, content: str) -> None:
    """Print what a control tool did."""
    if '"status": "error"' in content:
        console.say(TAG, f"{name} rejected: {console.preview(content, 200)}", "yellow")
    elif name in ("make_plan", "edit_plan", "delete_plan"):
        icons = {"pending": "○", "in_progress": "◐", "done": "●"}
        console.block("PLAN", [f"{icons[p['status']]} [{p['id']}] {p['title']}" for p in work["plan"]] or ["(empty)"])
    elif name == "fanout_subagents":
        console.block(f"FANOUT · round {work['round']}",
                      [f"→ {t['department']} @ {t['device_id']}: {console.preview(t['question'], 220)}"
                       for t in work["round_tasks"]], "yellow")


def make_tools_node():
    """Runs the orchestrator's tool calls in order."""

    async def orchestrator_tools(state: OrchestrationState, config: RunnableConfig) -> dict:
        online = get_hub(config).online_departments()
        work = {"plan": list(state["plan"]), "round_tasks": [], "round": state["round"], "response": ""}
        messages = []
        for call in state["messages"][-1].tool_calls:
            if call["name"] in CONTROL_TOOL_NAMES:
                manager = get_async_callback_manager_for_config(config)
                tool_run = await manager.on_tool_start(
                    {"name": call["name"]}, json.dumps(call["args"], ensure_ascii=False),
                    inputs=call["args"], tool_call_id=call["id"],
                )
                try:
                    content = run_control_tool(call["name"], call["args"], work, online)
                except Exception as exc:
                    await tool_run.on_tool_error(exc)
                    raise
                if json.loads(content).get("status") == "error":
                    await tool_run.on_tool_error(ValueError(content))
                else:
                    await tool_run.on_tool_end(content)
                _show_tool_result(call["name"], work, content)
                if '"status": "error"' in content:
                    await emit(config, "tool_rejected", {"tool": call["name"], "message": content[:300]})
                elif call["name"] in ("make_plan", "edit_plan", "delete_plan"):
                    await emit(config, "plan", {"plan": work["plan"]})
                elif call["name"] == "fanout_subagents":
                    await emit(config, "fanout", {"round": work["round"], "tasks": work["round_tasks"]})
                else:
                    await emit(config, "plan", {"plan": work["plan"]})
                    await emit(config, "handoff", {"response": work["response"]})
            elif call["name"] in FILE_TOOLS_BY_NAME:
                content = str(await FILE_TOOLS_BY_NAME[call["name"]].ainvoke(call["args"], config=config))
                console.say(TAG, f"{call['name']} → {console.preview(content, 120)}", "grey")
            else:
                content = f"Error: unknown tool {call['name']!r}"
            messages.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))
        return {"messages": messages, **work}

    return orchestrator_tools


def make_announce_node():
    """Streams the final report."""

    async def announce(state: OrchestrationState, config: RunnableConfig) -> dict:
        results = list(state["results"].values())
        messages = [
            SystemMessage(ANNOUNCE_PROMPT),
            HumanMessage(render_announce_input(state["user_query"], results, state["response"])),
        ]
        print("\n" + "═" * 72 + "\nFINAL REPORT\n" + "═" * 72, flush=True)
        report = ""
        async for chunk in chat_model(thinking=settings.llm_report_thinking).astream(messages, config=config):
            piece = chunk.content if isinstance(chunk.content, str) else ""
            report += piece
            print(piece, end="", flush=True)
        if not report.strip():
            # 模型没写出正文（例如 token 全用在了思考上）：至少把交接说明给 CEO
            report = state["response"]
            print("(the report writer returned nothing; showing the coordinator's summary)\n" + report, flush=True)
        print("\n" + "═" * 72, flush=True)
        await emit(config, "report", {"text": report})
        return {"report": report}

    return announce
