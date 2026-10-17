"""Messages between the orchestrator's hub and the department agents

Every message is one JSON text frame over WebSocket: {"type": ..., "payload": {...}}

    register      agent -> hub   {"device_id", "department", "capability"}
    register_ack  hub -> agent   {"ok", "message"}
    task          hub -> agent   {"dispatch_id", "task"}       task = {"task_id", "department", "question", ...}
    result        agent -> hub   {"dispatch_id", "result"}     result = the department's result dict

Provides:
- encode / decode:      build and parse a frame, checking the required fields
- failed_result:        the result reported when a task cannot be completed

Key constraints:
- only the question goes out and only the conclusion comes back; the
  orchestrator's context and the department's data never cross the wire
- dispatch_id is generated per dispatch, so a late result can never be
  matched to another task
"""

import json

REGISTER = "register"
REGISTER_ACK = "register_ack"
TASK = "task"
RESULT = "result"

REQUIRED_FIELDS = {
    REGISTER: {"device_id", "department", "capability"},
    REGISTER_ACK: {"ok", "message"},
    TASK: {"dispatch_id", "task"},
    RESULT: {"dispatch_id", "result"},
}


class ProtocolError(ValueError):
    """A frame does not follow the protocol."""


def _check(msg_type, payload) -> None:
    if msg_type not in REQUIRED_FIELDS:
        raise ProtocolError(f"unknown message type {msg_type!r}")
    if not isinstance(payload, dict):
        raise ProtocolError(f"{msg_type} payload must be an object")
    missing = REQUIRED_FIELDS[msg_type] - payload.keys()
    if missing:
        raise ProtocolError(f"{msg_type} payload is missing {sorted(missing)}")


def encode(msg_type: str, payload: dict) -> str:
    """Build one frame."""
    _check(msg_type, payload)
    return json.dumps({"type": msg_type, "payload": payload}, ensure_ascii=False)


def decode(raw: str | bytes) -> tuple[str, dict]:
    """Parse one frame into (type, payload)."""
    try:
        message = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"frame is not JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("frame must be an object")
    _check(message.get("type"), message.get("payload"))
    return message["type"], message["payload"]


def failed_result(task: dict, reason: str, status: str = "failed", elapsed: float = 0.0) -> dict:
    """The result of a task that did not complete (offline, disconnected, timeout, crash)."""
    return {
        "task_id": task.get("task_id", ""),
        "department": task.get("department", ""),
        "device_id": task.get("device_id", ""),
        "status": status,
        "summary": f"No result from the {task.get('department', '?')} department: {reason}.",
        "elapsed_seconds": round(elapsed, 1),
    }
