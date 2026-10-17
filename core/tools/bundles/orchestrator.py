"""Tool definitions owned by the orchestrator.

Control tools (plan, fanout, end) are pydantic specs run in order by the
graph's tools node on the turn's working state; file tools are ordinary
tools bound to the orchestrator's own workspace.

Tools provided:
    ├── make_plan / edit_plan / delete_plan     plan the work
    ├── fanout_subagents                        ask departments questions in parallel
    ├── end_orchestration                       finish and hand over to the final report
    └── view_file / glob_tool / grep_tool / write_file / str_replace    its own workspace only

Provides:
- CONTROL_TOOL_SPECS:       plan + fanout + end specs
- CONTROL_TOOL_NAMES:       their names
- END_TOOL_SPECS:           only end_orchestration, for the last turn
- run_control_tool:         validate and run one control tool call
"""

from pydantic import BaseModel, Field

from core.tools._kernel import _orchestration as kernel
from core.tools.bundles.plan import PLAN_TOOL_NAMES, PLAN_TOOL_SPECS, JsonListArgs, run_plan_tool, tool_spec, validate
from core.tools.descriptions.orchestration import TOOL_DESCRIPTION


class DepartmentTask(BaseModel):
    department: str = Field(description="a department name from <ONLINE_DEPARTMENTS>")
    question: str = Field(description="self-contained question: exact scope, what to measure, what to return")


class FanoutArgs(JsonListArgs):
    tasks: list[DepartmentTask]


class EndArgs(BaseModel):
    response: str = Field(description="handoff note for the final report")


ARGS = {"fanout_subagents": FanoutArgs, "end_orchestration": EndArgs}

END_TOOL_SPECS = [tool_spec("end_orchestration", EndArgs, TOOL_DESCRIPTION["end_orchestration"])]
CONTROL_TOOL_SPECS = [*PLAN_TOOL_SPECS, tool_spec("fanout_subagents", FanoutArgs, TOOL_DESCRIPTION["fanout_subagents"]),
                      *END_TOOL_SPECS]
CONTROL_TOOL_NAMES = PLAN_TOOL_NAMES | set(ARGS)


def run_control_tool(name: str, args: dict, work: dict, online: dict[str, str]) -> str:
    """Validate one control tool call and run it on the turn's working state.

    Args:
        name / args:    the tool call.
        work:           {"plan", "round_tasks", "round", "response"} of this turn.
        online:         department -> device id of the online department agents.
    """
    if name in PLAN_TOOL_NAMES:
        return run_plan_tool(name, args, work)
    parsed = validate(ARGS[name], name, args)
    if isinstance(parsed, str):
        return parsed
    if name == "fanout_subagents":
        return kernel.fanout_subagents(work, parsed["tasks"], online)
    return kernel.end_orchestration(work, parsed["response"])
