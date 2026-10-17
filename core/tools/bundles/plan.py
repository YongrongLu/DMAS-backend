"""Plan tool definitions, shared by the orchestrator and the department agents.

The schemas are pydantic models turned into OpenAI tool specs; the owning
graph's tools node validates each call and runs it on the turn's working
state through run_plan_tool, so plan updates of one turn never race.

Tools provided:
    ├── make_plan                       create the plan
    ├── edit_plan                       update phases
    └── delete_plan                     remove a phase or the whole plan

Provides:
- JsonListArgs:         base model accepting list arguments sent as JSON strings
- PLAN_TOOL_SPECS:      tool specs to bind to a model
- PLAN_TOOL_NAMES:      their names
- tool_spec:            build an OpenAI tool spec from a pydantic model
- run_plan_tool:        validate and run one plan tool call
"""

import json
from typing import Literal

from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field, ValidationError, field_validator

from core.tools._kernel import _plan as kernel
from core.tools.descriptions.plan import TOOL_DESCRIPTION

Status = Literal["pending", "in_progress", "done"]


class JsonListArgs(BaseModel):
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


class MakePlanArgs(JsonListArgs):
    phases: list[PlanPhase]


class PhaseUpdate(BaseModel):
    id: str
    status: Status | None = None
    title: str | None = None


class EditPlanArgs(JsonListArgs):
    updates: list[PhaseUpdate]


class DeletePlanArgs(BaseModel):
    phase_id: str = ""
    delete_all: bool = False


ARGS = {"make_plan": MakePlanArgs, "edit_plan": EditPlanArgs, "delete_plan": DeletePlanArgs}
PLAN_TOOL_NAMES = frozenset(ARGS)


def tool_spec(name: str, model: type[BaseModel], description: str) -> dict:
    """OpenAI tool spec for one tool backed by a pydantic argument model."""
    spec = convert_to_openai_tool(model)
    spec["function"]["name"] = name
    spec["function"]["description"] = description
    return spec


PLAN_TOOL_SPECS = [tool_spec(name, model, TOOL_DESCRIPTION[name]) for name, model in ARGS.items()]


def validate(model: type[BaseModel], name: str, args: dict) -> dict | str:
    """Parsed arguments, or an error JSON string for the model."""
    try:
        return model.model_validate(args or {}).model_dump()
    except (ValidationError, json.JSONDecodeError) as exc:
        return json.dumps({"status": "error", "message": f"invalid arguments for {name}: {str(exc)[:500]}"})


def run_plan_tool(name: str, args: dict, work: dict) -> str:
    """Validate one plan tool call and run it on the turn's working state."""
    parsed = validate(ARGS[name], name, args)
    if isinstance(parsed, str):
        return parsed
    if name == "make_plan":
        return kernel.make_plan(work, parsed["phases"])
    if name == "edit_plan":
        return kernel.edit_plan(work, parsed["updates"])
    return kernel.delete_plan(work, parsed["phase_id"], parsed["delete_all"])
