"""Orchestrator main graph

    START → orchestrator → orchestrator_tools ─┬→ department (one Send per task, run on the devices)
              ↑   │                            │        ↓
              │   │                            │     collect ──→ orchestrator
              │   └── no tool call ──┐         ├→ orchestrator (plan changes only)
              │                      ↓         │
              └──────────────────  announce ←──┘ (end_orchestration)  → END

Provides:
- build_graph:          compile the orchestration graph
- initial_state:        the starting state for one CEO question

Key constraints:
- every department task goes through the hub to the device that owns the
  data; the graph never touches department data
- all department branches of a round run in the same step, so collect runs
  once per round and injects every result before the orchestrator wakes up
"""

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from core.agents.orchestrator import get_hub, make_announce_node, make_orchestrator_node, make_tools_node
from core.agents.state import OrchestrationState
from utils import console


def initial_state(query: str) -> dict:
    """The starting state for one question."""
    return {
        "messages": [HumanMessage(query)], "user_query": query, "plan": [], "round_tasks": [],
        "results": {}, "round": 0, "iteration": 0, "response": "", "report": "",
    }


async def department(task: dict, config: RunnableConfig) -> dict:
    """Run one task on the device of its department, through the hub."""
    result = await get_hub(config).dispatch(task["task"])
    icon = "✓" if result.get("status") == "success" else "✗"
    console.say("orchestrator", f"{icon} {result.get('department')} @ {result.get('device_id', '?')} "
                                f"{result.get('status')} in {result.get('elapsed_seconds', 0)}s",
                "green" if icon == "✓" else "red")
    return {"results": {result["task_id"]: result}}


def _format_result(result: dict) -> str:
    """One department result as the orchestrator reads it."""
    return (f'<DEPARTMENT_RESULT task_id="{result["task_id"]}" department="{result.get("department")}" '
            f'device="{result.get("device_id", "?")}" status="{result.get("status")}" '
            f'elapsed="{result.get("elapsed_seconds", 0)}s">\n{result.get("summary", "")}\n</DEPARTMENT_RESULT>')


def collect(state: OrchestrationState) -> dict:
    """Inject this round's results into the orchestrator's conversation and close the round."""
    results = [state["results"][t["task_id"]] for t in state["round_tasks"] if t["task_id"] in state["results"]]
    return {"messages": [HumanMessage(_format_result(r)) for r in results], "round_tasks": []}


def _after_orchestrator(state: OrchestrationState) -> str:
    return "announce" if state["response"] else "orchestrator_tools"


def _after_tools(state: OrchestrationState):
    if state["response"]:
        return "announce"
    if state["round_tasks"]:
        return [Send("department", {"task": t}) for t in state["round_tasks"]]
    return "orchestrator"


def build_graph():
    """Compile the orchestration graph; run it with config["configurable"]["hub"] set."""
    builder = StateGraph(OrchestrationState)
    builder.add_node("orchestrator", make_orchestrator_node())
    builder.add_node("orchestrator_tools", make_tools_node())
    builder.add_node("department", department)
    builder.add_node("collect", collect)
    builder.add_node("announce", make_announce_node())

    builder.add_edge(START, "orchestrator")
    builder.add_conditional_edges("orchestrator", _after_orchestrator, ["orchestrator_tools", "announce"])
    builder.add_conditional_edges("orchestrator_tools", _after_tools, ["announce", "department", "orchestrator"])
    builder.add_edge("department", "collect")
    builder.add_edge("collect", "orchestrator")
    builder.add_edge("announce", END)
    return builder.compile()
