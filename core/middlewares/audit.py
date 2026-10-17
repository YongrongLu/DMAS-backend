"""Audit trail of privacy decisions on a department device

Provides:
- record_denial:        log one denied or blocked request and show the 🔒 line on the device terminal

Key constraints:
- the 🔒 line goes to stderr of the agent process, so it shows on the
  department terminal (the audience sees the refusal happen on that device)
  and never mixes with a skill's JSON on stdout
"""

import sys

from utils.logging import get_logger

logger = get_logger(__name__)


def record_denial(department: str, source: str, reason: str, detail: str = "") -> None:
    """Record one privacy decision.

    Args:
        department:     the department whose policy decided.
        source:         what decided, e.g. "shell_executor", "data-access-request", "egress_guard".
        reason:         why, shown on the terminal.
        detail:         the request that was refused, logged truncated.
    """
    logger.debug("policy_denied", department=department, source=source, reason=reason, detail=detail[:200])
    print(f"🔒 POLICY DENIED [{department} · {source}] {reason}", file=sys.stderr, flush=True)
