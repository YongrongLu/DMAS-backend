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

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from core.agents.model import chat_model, invoke
from core.agents.state import OrchestrationState
from core.prompts.system_prompt_announce import ANNOUNCE_PROMPT, render_announce_input
from core.prompts.system_prompt_orchestrator import render_orchestrator_prompt, render_snapshot
from core.tools.bundles.orchestrator import FINAL_TOOL_SPECS, ORCHESTRATOR_TOOL_SPECS, run_orchestrator_tool
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


def make_orchestrator_node():
    """The orchestrator's LLM step."""
    system_prompt = render_orchestrator_prompt()

    async def orchestrator(state: OrchestrationState, config: RunnableConfig) -> dict:
        online = get_hub(config).online_departments()
        final_turn = state["iteration"] + 1 >= MAX_ITERATIONS
        model = chat_model().bind_tools(FINAL_TOOL_SPECS if final_turn else ORCHESTRATOR_TOOL_SPECS)
        snapshot = render_snapshot(state["plan"], state["iteration"], MAX_ITERATIONS, online)
        messages = [SystemMessage(system_prompt), *state["messages"], HumanMessage(snapshot)]

        response = await invoke(model, messages, role=TAG)
        text = _text(response).strip()
        if text:
            console.say(TAG, console.preview(text, 300), "magenta")

        update = {"messages": [response], "iteration": state["iteration"] + 1}
        if not response.tool_calls:
            update["response"] = text or "Summarise the department findings for the CEO."
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
            content = run_orchestrator_tool(call["name"], call["args"], work, online)
            messages.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))
            _show_tool_result(call["name"], work, content)
        return {"messages": messages, **work}

    return orchestrator_tools


def make_announce_node():
    """Streams the final report."""

    async def announce(state: OrchestrationState) -> dict:
        results = list(state["results"].values())
        messages = [
            SystemMessage(ANNOUNCE_PROMPT),
            HumanMessage(render_announce_input(state["user_query"], results, state["response"])),
        ]
        print("\n" + "═" * 72 + "\nFINAL REPORT\n" + "═" * 72, flush=True)
        report = ""
        async for chunk in chat_model(thinking=settings.llm_report_thinking).astream(messages):
            piece = chunk.content if isinstance(chunk.content, str) else ""
            report += piece
            print(piece, end="", flush=True)
        if not report.strip():
            # 模型没写出正文（例如 token 全用在了思考上）：至少把交接说明给 CEO
            report = state["response"]
            print("(the report writer returned nothing; showing the coordinator's summary)\n" + report, flush=True)
        print("\n" + "═" * 72, flush=True)
        return {"report": report}

    return announce
