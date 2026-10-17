"""Orchestrator control tools: plan, fanout to departments, end

Every function works on `work`, the orchestrator's mutable view of the state
for the current turn ({"plan", "round_tasks", "round", "response"}), and
returns a JSON string for the ToolMessage. Calls of one turn run in order on
the same `work`, so a second call sees the first one's effect.

Provides:
- make_plan / edit_plan / delete_plan:  manage the plan phases
- fanout_subagents:                     dispatch one question per department
- end_orchestration:                    hand the findings to the final report

Key constraints:
- statuses are pending / in_progress / done; at most MAX_PHASES phases
- fanout: 1..3 tasks, one per department, each department must be online;
  the device and task id are filled in here, the model only names the
  department and writes the question; one fanout per turn
- end_orchestration marks every phase done, so a forgotten edit_plan
  never blocks the report
"""

import json

from core.departments import DEPARTMENTS


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


def fanout_subagents(work: dict, tasks: list[dict], online: dict[str, str]) -> str:
    """Dispatch one question per department for this round.

    Args:
        work:       the turn's working state.
        tasks:      [{"department", "question"}].
        online:     department -> device id of the online department agents.
    """
    if work["round_tasks"]:
        return _error("fanout_subagents was already called in this turn; send all questions in one call")
    if not 1 <= len(tasks) <= len(DEPARTMENTS):
        return _error(f"send 1 to {len(DEPARTMENTS)} tasks, one per department")
    departments = [t["department"] for t in tasks]
    if len(set(departments)) != len(departments):
        return _error("one task per department per round; merge the questions for the same department")
    offline = [d for d in departments if d not in online]
    if offline:
        return _error(f"department(s) {offline} are offline; online: {sorted(online)}")
    if any(not t["question"].strip() for t in tasks):
        return _error("every task needs a question")

    work["round"] += 1
    work["round_tasks"] = [
        {
            "task_id": f"r{work['round']}-{t['department']}",
            "department": t["department"],
            "device_id": online[t["department"]],
            "question": t["question"].strip(),
        }
        for t in tasks
    ]
    return _ok(f"dispatched {len(tasks)} task(s); results arrive in the next message",
               tasks=[{k: t[k] for k in ("task_id", "department", "device_id")} for t in work["round_tasks"]])


def end_orchestration(work: dict, response: str) -> str:
    """Finish: store the handoff note for the final report."""
    if not response.strip():
        return _error("response must summarise the findings for the final report")
    work["plan"] = [{**p, "status": "done"} for p in work["plan"]]
    work["response"] = response.strip()
    return _ok("orchestration finished; the final report will be written from your note")
