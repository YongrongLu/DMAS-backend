"""LangGraph state definitions

Provides:
- OrchestrationState:   state of the orchestrator graph
- DepartmentState:      state of one department agent working on one task

Key constraints:
- department results arrive from parallel branches, so `results` merges
  dicts keyed by task_id; every other orchestrator field has one writer per step
- a department graph keeps its own `messages`; only its `result` dict ever
  leaves it, so its tool outputs never reach the orchestrator
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    """Reducer: shallow-merge two dicts, right wins."""
    return {**(left or {}), **(right or {})}


class OrchestrationState(TypedDict):
    """State of the orchestrator graph.

    Attributes:
        messages:       the orchestrator's conversation: user query, its tool calls,
                        tool results and the department results injected by collect.
        user_query:     the CEO's question.
        plan:           plan phases: {"id", "title", "status"}.
        round_tasks:    tasks dispatched in the current fanout round, cleared by collect.
        results:        task_id -> department result, across all rounds.
        round:          number of fanout rounds so far.
        iteration:      orchestrator LLM calls so far.
        response:       the handoff note; set means the orchestration is finished.
        report:         the final report written by announce.
    """
    messages: Annotated[list, add_messages]
    user_query: str
    plan: list[dict]
    round_tasks: list[dict]
    results: Annotated[dict, merge_dicts]
    round: int
    iteration: int
    response: str
    report: str


class DepartmentState(TypedDict):
    """State of one department agent working on one task.

    Attributes:
        task:           {"task_id", "department", "question", ...} as dispatched.
        messages:       the department agent's own conversation.
        plan:           the agent's own plan phases.
        iteration:      LLM calls so far.
        tokens:         tokens used so far.
        result:         the conclusion sent back to the orchestrator.
    """
    task: dict
    messages: Annotated[list, add_messages]
    plan: list[dict]
    iteration: int
    tokens: Annotated[int, operator.add]
    result: dict
