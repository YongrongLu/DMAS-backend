"""Orchestrator control tools: fanout to departments, end

Every function works on `work`, the orchestrator's mutable view of the state
for the current turn ({"plan", "round_tasks", "round", "response"}), and
returns a JSON string for the ToolMessage. Calls of one turn run in order on
the same `work`, so a second call sees the first one's effect.

Provides:
- fanout_subagents:                     dispatch one question per department
- end_orchestration:                    hand the findings to the final report

Key constraints:
- fanout: one task per department, each department must be online;
  the device and task id are filled in here, the model only names the
  department and writes the question; one fanout per turn
- end_orchestration marks every phase done, so a forgotten edit_plan
  never blocks the report
"""

import json


def _ok(message: str, **extra) -> str:
    return json.dumps({"status": "ok", "message": message, **extra}, ensure_ascii=False)


def _error(message: str) -> str:
    return json.dumps({"status": "error", "message": message}, ensure_ascii=False)


def fanout_subagents(work: dict, tasks: list[dict], online: dict[str, str]) -> str:
    """Dispatch one question per department for this round.

    Args:
        work:       the turn's working state.
        tasks:      [{"department", "question"}].
        online:     department -> device id of the online department agents.
    """
    if work["round_tasks"]:
        return _error("fanout_subagents was already called in this turn; send all questions in one call")
    if not 1 <= len(tasks) <= max(1, len(online)):
        return _error(f"send 1 to {max(1, len(online))} tasks, one per online department")
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
    return _ok("orchestration finished; the final report will be written from your note", plan=work["plan"])
