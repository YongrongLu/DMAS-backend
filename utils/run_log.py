"""Automatic run logs

Every process copies its terminal output into logs/.sessions/<name>.log while
still printing it as usual. When the orchestrator finishes a run it stitches
its own session and the local department sessions into logs/rita-<N>.log:

    ------------------------------------------------------------ (124 dashes)
    Orchestrator
    ------------------------------------------------------------
    <terminal output>
    ------------------------------------------------------------

Provides:
- SessionLog:       the capture of one process; rotate() starts a new segment
- capture:          install the capture on stdout and stderr
- write_run_log:    stitch the sessions of one run into the next logs/rita-<N>.log

Key constraints:
- install the capture before setup_logging, which binds stderr once
- color codes are stripped from the files
- a department session is only found when that agent runs on this machine;
  remote departments get a placeholder section
"""

import io
import os
import re
import sys
import time
from datetime import datetime

LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
SESSIONS_DIR = os.path.join(LOGS_DIR, ".sessions")
RUN_LOG_PREFIX = "rita"
RULE = "-" * 124
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class _Tee(io.TextIOBase):
    """Write to the original stream and to the session file."""

    def __init__(self, stream, session: "SessionLog"):
        self._stream, self._session = stream, session

    def write(self, text: str) -> int:
        self._stream.write(text)
        self._session.append(text)
        return len(text)

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        return self._stream.isatty()

    def fileno(self) -> int:
        return self._stream.fileno()


class SessionLog:
    """The terminal output of one process, written to logs/.sessions/<name>.log."""

    def __init__(self, name: str):
        self.name = name
        self.started_at = time.time()
        self.path = os.path.join(SESSIONS_DIR, f"{name}.log")
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        self._file = open(self.path, "w", encoding="utf-8", buffering=1)

    def append(self, text: str) -> None:
        self._file.write(_ANSI_RE.sub("", text))

    def rotate(self, first_line: str = "") -> None:
        """Start a new segment, e.g. when an agent connects to a new orchestrator run."""
        self._file.close()
        self._file = open(self.path, "w", encoding="utf-8", buffering=1)
        if first_line:
            self.append(first_line.rstrip("\n") + "\n")

    def text(self) -> str:
        self._file.flush()
        with open(self.path, encoding="utf-8") as f:
            return f.read()


def capture(name: str, module: str) -> SessionLog:
    """Copy this process's stdout and stderr into logs/.sessions/<name>.log.

    Args:
        name:       the session name, e.g. "orchestrator" or "agent-sales".
        module:     the module that was started, shown as the command line.
    """
    session = SessionLog(name)
    sys.stdout = _Tee(sys.stdout, session)
    sys.stderr = _Tee(sys.stderr, session)
    session.append(f"{datetime.now():%Y-%m-%d %H:%M:%S} $ python -m {module} {' '.join(sys.argv[1:])}\n")
    return session


def _next_path() -> str:
    """logs/rita-<N>.log with N one above the highest existing number."""
    numbers = [int(m.group(1)) for f in os.listdir(LOGS_DIR)
               if (m := re.fullmatch(rf"{RUN_LOG_PREFIX}-(\d+)\.log", f))]
    return os.path.join(LOGS_DIR, f"{RUN_LOG_PREFIX}-{max(numbers, default=0) + 1}.log")


def _section(title: str, body: str) -> str:
    return f"{RULE}\n{title}\n{RULE}\n{body.rstrip()}\n{RULE}\n\n\n"


def write_run_log(orchestrator: SessionLog, departments: dict[str, str]) -> str:
    """Write logs/rita-<N>.log from the orchestrator session and the local department sessions.

    Args:
        orchestrator:   the orchestrator's session.
        departments:    session name -> section title, e.g. {"agent-sales": "Sales Department"}.

    Returns:
        the path written.
    """
    parts = [_section("Orchestrator", orchestrator.text())]
    for name, title in departments.items():
        path = os.path.join(SESSIONS_DIR, f"{name}.log")
        # 早于这次运行开始的记录属于上一轮（例如那个 Agent 这次没连上），不拼进来
        if os.path.isfile(path) and os.path.getmtime(path) >= orchestrator.started_at:
            with open(path, encoding="utf-8") as f:
                body = f.read()
        else:
            body = "(no session for this run on this machine: the agent was offline or runs on another device)"
        parts.append(_section(title, body))

    path = _next_path()
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    return path
