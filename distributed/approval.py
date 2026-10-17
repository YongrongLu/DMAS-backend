"""Owner approval on a department device -- the human in the loop

The department graph pauses (LangGraph interrupt) at three points, and the
agent process asks the person at this device before it goes on:

    task       a question arrived from the orchestrator: run it?
    access     the agent was blocked reading the restricted private/ folder: open it for this task?
    deliver    the conclusion is ready: send it to the orchestrator?

Provides:
- ask_owner:    show one request to the device owner; True when approved

Key constraints:
- APPROVAL_MODE in .env: "dialog" (native macOS dialog, the default),
  "terminal" (y/n on the agent's terminal) or "auto" (approve everything,
  for unattended runs); a dialog that cannot open falls back to the terminal
- an unanswered request is denied after APPROVAL_TIMEOUT_SECONDS
- one request at a time, so parallel tasks never stack dialogs
- every decision is printed on the device terminal, so it is in the run log
"""

import asyncio
import shutil
import sys

from utils import console
from utils.settings import settings

DIALOG_MAX_CHARS = 1800
# text, title and timeout come in as arguments, so nothing needs escaping
_DIALOG_SCRIPT = (
    "on run argv",
    "activate",
    'set reply to display dialog (item 1 of argv) with title (item 2 of argv) buttons {"Deny", "Approve"} '
    'default button "Approve" giving up after ((item 3 of argv) as integer)',
    "return button returned of reply",
    "end run",
)

_lock = asyncio.Lock()


async def _dialog(title: str, text: str) -> bool | None:
    """Approve / Deny in a native dialog; None when no dialog can be shown."""
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return None
    body = text if len(text) <= DIALOG_MAX_CHARS else text[:DIALOG_MAX_CHARS] + "…"
    argv = ["osascript", *(a for line in _DIALOG_SCRIPT for a in ("-e", line)),
            body, title, str(int(settings.approval_timeout_seconds))]
    proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await proc.communicate()
    except asyncio.CancelledError:  # 任务被取消（hub 断开）时把弹窗一起关掉
        proc.kill()
        raise
    if proc.returncode != 0:
        console.say("owner", f"dialog unavailable ({console.preview(err.decode(errors='replace'), 120)}); "
                             "asking on the terminal", "grey")
        return None
    return out.decode().strip() == "Approve"


async def _terminal(title: str, text: str) -> bool:
    """y/n on the agent's terminal; no answer in time means no."""
    console.block(title, text.splitlines(), "magenta")
    try:
        answer = await asyncio.wait_for(asyncio.to_thread(input, "approve? [y/N] "),
                                        timeout=settings.approval_timeout_seconds)
    except (TimeoutError, EOFError):
        return False
    return answer.strip().lower() in ("y", "yes")


async def ask_owner(department: str, request: dict) -> bool:
    """Ask the owner of this device about one pause of the department graph.

    Args:
        department:     the department name, for the terminal tag.
        request:        the interrupt payload: {"kind", "task_id", "title", "text"}.
    """
    tag = f"{department} · {request.get('task_id', '?')} · owner"
    title = request["title"]
    if settings.approval_mode == "auto":
        console.say(tag, f"auto-approved: {title}", "grey")
        return True
    async with _lock:
        console.say(tag, f"⏸ waiting for approval: {title}", "magenta")
        approved = await _dialog(title, request["text"]) if settings.approval_mode == "dialog" else None
        if approved is None:
            approved = await _terminal(title, request["text"])
    console.say(tag, f"{'✓ approved' if approved else '✗ denied'}: {title}", "green" if approved else "red")
    return approved
