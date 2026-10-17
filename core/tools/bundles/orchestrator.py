"""Tool definitions owned by the orchestrator.

The schemas are pydantic models turned into OpenAI tool specs; the graph's
tools node validates each call against its model and runs it in order
through run_orchestrator_tool, so calls of one turn never race.

Tools provided:
    ├── make_plan                       create the plan
    ├── edit_plan                       update phases
    ├── delete_plan                     remove a phase or the whole plan
    ├── fanout_subagents                ask departments questions in parallel
    └── end_orchestration               finish and hand over to the final report

Provides:
- ORCHESTRATOR_TOOL_SPECS:      tool specs to bind to the model
- FINAL_TOOL_SPECS:             the specs left when the iteration budget is spent
- run_orchestrator_tool:        validate and run one tool call on the turn's working state
"""

import json
from typing import Literal

from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field, ValidationError, field_validator

from core.tools._kernel import _orchestration as kernel
from core.tools.descriptions.orchestration import TOOL_DESCRIPTION


Status = Literal["pending", "in_progress", "done"]
Department = Literal["sales", "customer", "product"]


class _JsonListArgs(BaseModel):
    """Accept list arguments sent as a JSON string; some models do that."""

    @field_validator("*", mode="before")
    @classmethod
    def _parse_json(cls, value):
        if isinstance(value, str) and value.strip().startswith("["):
            return json.loads(value)
        return value


class PlanPhase(BaseModel):
    id: str = Field(description="short unique id, e.g. 'p1'")
    title: str = Field(description="what the phase does")
    status: Status = "pending"


class MakePlanArgs(_JsonListArgs):
    phases: list[PlanPhase]


class PhaseUpdate(BaseModel):
    id: str
    status: Status | None = None
    title: str | None = None


class EditPlanArgs(_JsonListArgs):
    updates: list[PhaseUpdate]


class DeletePlanArgs(BaseModel):
    phase_id: str = ""
    delete_all: bool = False


class DepartmentTask(BaseModel):
    department: Department
    question: str = Field(description="self-contained question with exact periods and what to return")


class FanoutArgs(_JsonListArgs):
    tasks: list[DepartmentTask]


class EndArgs(BaseModel):
    response: str = Field(description="handoff note for the final report")


ARGS = {
    "make_plan": MakePlanArgs,
    "edit_plan": EditPlanArgs,
    "delete_plan": DeletePlanArgs,
    "fanout_subagents": FanoutArgs,
    "end_orchestration": EndArgs,
}


def _spec(name: str) -> dict:
    """OpenAI tool spec for one tool."""
    spec = convert_to_openai_tool(ARGS[name])
    spec["function"]["name"] = name
    spec["function"]["description"] = TOOL_DESCRIPTION[name]
    return spec


ORCHESTRATOR_TOOL_SPECS = [_spec(name) for name in ARGS]
FINAL_TOOL_SPECS = [_spec("end_orchestration")]


def run_orchestrator_tool(name: str, args: dict, work: dict, online: dict[str, str]) -> str:
    """Validate one tool call and run it on the turn's working state.

    Returns:
        the ToolMessage content (JSON with status ok or error).
    """
    if name not in ARGS:
        return json.dumps({"status": "error", "message": f"unknown tool {name!r}"})
    try:
        parsed = ARGS[name].model_validate(args or {}).model_dump()
    except (ValidationError, json.JSONDecodeError) as exc:
        return json.dumps({"status": "error", "message": f"invalid arguments for {name}: {str(exc)[:500]}"})

    if name == "make_plan":
        return kernel.make_plan(work, parsed["phases"])
    if name == "edit_plan":
        return kernel.edit_plan(work, parsed["updates"])
    if name == "delete_plan":
        return kernel.delete_plan(work, parsed["phase_id"], parsed["delete_all"])
    if name == "fanout_subagents":
        return kernel.fanout_subagents(work, parsed["tasks"], online)
    return kernel.end_orchestration(work, parsed["response"])
