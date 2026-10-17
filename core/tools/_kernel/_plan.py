"""Plan tools shared by the orchestrator and the department agents

Every function works on `work`, the agent's mutable view of its state for the
current turn (it holds "plan"), and returns a JSON string for the ToolMessage.
Calls of one turn run in order on the same `work`.

Provides:
- make_plan / edit_plan / delete_plan:  manage the plan phases

Key constraints:
- statuses are pending / in_progress / done; at most MAX_PHASES phases
- phase ids are unique; edit_plan never changes an id
"""

import json


PHASE_STATUSES = ("pending", "in_progress", "done")
MAX_PHASES = 8


def _ok(message: str, **extra) -> str:
    return json.dumps({"status": "ok", "message": message, **extra}, ensure_ascii=False)


def _error(message: str) -> str:
    return json.dumps({"status": "error", "message": message}, ensure_ascii=False)


def make_plan(work: dict, phases: list[dict]) -> str:
    """Create the plan; refused when one exists (use edit_plan or delete_plan)."""
    if work["plan"]:
        return _error("a plan already exists; use edit_plan to update it or delete_plan(delete_all=true) to reset")
    if not phases or len(phases) > MAX_PHASES:
        return _error(f"a plan needs 1 to {MAX_PHASES} phases")
    ids = [p["id"].strip() for p in phases]
    if len(set(ids)) != len(ids) or not all(ids):
        return _error("phase ids must be unique and non-empty")
    work["plan"] = [{"id": p["id"].strip(), "title": p["title"].strip(), "status": p["status"]} for p in phases]
    return _ok(f"plan created with {len(phases)} phases", plan=work["plan"])


def edit_plan(work: dict, updates: list[dict]) -> str:
    """Change the status or title of existing phases."""
    if not work["plan"]:
        return _error("there is no plan yet; call make_plan first")
    by_id = {p["id"]: dict(p) for p in work["plan"]}
    for update in updates:
        phase = by_id.get(update["id"].strip())
        if phase is None:
            return _error(f"no phase {update['id']!r}; existing: {sorted(by_id)}")
        if update.get("status"):
            phase["status"] = update["status"]
        if update.get("title"):
            phase["title"] = update["title"].strip()
    work["plan"] = [by_id[p["id"]] for p in work["plan"]]
    return _ok(f"{len(updates)} phase(s) updated", plan=work["plan"])


def delete_plan(work: dict, phase_id: str = "", delete_all: bool = False) -> str:
    """Remove one phase, or the whole plan."""
    if delete_all:
        work["plan"] = []
        return _ok("plan cleared", plan=[])
    remaining = [p for p in work["plan"] if p["id"] != phase_id.strip()]
    if len(remaining) == len(work["plan"]):
        return _error(f"no phase {phase_id!r}")
    work["plan"] = remaining
    return _ok(f"phase {phase_id} removed", plan=remaining)
