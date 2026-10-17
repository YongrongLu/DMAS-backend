"""Chat Completions envelope with tool execution and workflow extensions."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1)
    model: str = "retail-rescue"
    stream: Literal[True] = True

    @model_validator(mode="after")
    def validate_query(self):
        if self.messages[-1].role != "user" or not self.messages[-1].content.strip():
            raise ValueError("The last message must be a non-empty user message")
        return self


class ToolEvent(BaseModel):
    type: Literal["tool_start", "tool_end", "tool_error"]
    id: str
    name: str
    agent: str = "orchestrator"
    input: str | None = None
    output: str | None = None
    error: str | None = None
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


class PlanPhase(BaseModel):
    id: str
    title: str
    status: Literal["pending", "in_progress", "done"]


class PlanSnapshot(BaseModel):
    agent: str = "orchestrator"
    phases: list[PlanPhase]


class WorkflowEvent(BaseModel):
    type: Literal["phase", "department_start", "department_end"]
    phase: Literal["planning", "working", "merging", "reporting"] | None = None
    task_id: str | None = None
    department: str | None = None
    status: str | None = None


class Delta(BaseModel):
    role: Literal["assistant"] | None = None
    content: str | None = None
    tool_event: ToolEvent | None = None
    workflow: WorkflowEvent | None = None
    plan: PlanSnapshot | None = None


class Choice(BaseModel):
    index: int = 0
    delta: Delta
    finish_reason: Literal["stop"] | None = None

    @field_serializer("delta")
    def serialize_delta(self, value: Delta):
        return value.model_dump(exclude_none=True)


class CompletionChunk(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[Choice]


def sse_data(payload: BaseModel | str) -> str:
    data = payload.model_dump_json() if isinstance(payload, BaseModel) else payload
    return f"data: {data}\n\n"
