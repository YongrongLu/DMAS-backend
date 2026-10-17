"""Egress guard -- the last check on a department's conclusion before it leaves the device

Called by the finish node of every department graph, right before the
result is handed back for sending to the orchestrator.

Provides:
- EgressVerdict:        what the guard decided and the text to send
- guard_text:           check one conclusion
- apply_egress_guard:   check a conclusion and audit the decision

Key constraints:
- identifiers are matched against the real restricted values of this
  device's view (e.g. customer ids), never against a pattern alone
- numbers are not identifiers: "£15,616", "15616.5" and "15616%" are skipped
- fewer than EGRESS_MAX_ID_HITS identifiers are redacted; that many or more,
  or more than EGRESS_MAX_TABLE_LINES raw CSV-like lines, blocks the whole
  conclusion; markdown tables of aggregates pass; an over-long conclusion is truncated
- every redaction or block is audited with the 🔒 line on the device terminal
"""

import re
from dataclasses import dataclass

from core.data.audit import record_denial
from core.data.loader import load_restricted_values
from core.data.policy import denial_message
from core.departments.base import DepartmentSpec
from core.middlewares.constants import (
    EGRESS_MAX_CHARS,
    EGRESS_MAX_ID_HITS,
    EGRESS_MAX_TABLE_LINES,
    EGRESS_REDACTED,
)


# 前后紧挨着数字标点或货币符号的不算标识符，例如 "£15,616" 里的 "15" 和 "616"
_TOKEN_RE = re.compile(r"(?<![\w.,£$€])[A-Za-z0-9]+(?![\w%]|[.,]\d)")


@dataclass(frozen=True)
class EgressVerdict:
    """The guard's decision on one conclusion.

    Attributes:
        action:     "pass", "redacted", "truncated" or "blocked".
        text:       the text to send; equal to the input on "pass".
        reasons:    why the text was changed.
    """
    action: str
    text: str
    reasons: tuple[str, ...] = ()


# 不算千分位的逗号："£1,669,893" 里的逗号后面正好跟三位数字
_FIELD_COMMA_RE = re.compile(r",(?!\d{3}(?!\d))")


def _table_lines(text: str) -> int:
    """Lines that look like raw CSV rows (4+ field-separating commas); markdown tables of aggregates do not count."""
    return sum(1 for line in text.splitlines() if len(_FIELD_COMMA_RE.findall(line)) >= 4)


def guard_text(text: str, spec: DepartmentSpec, restricted_values: frozenset[str]) -> EgressVerdict:
    """Check one department conclusion.

    Args:
        text:               the conclusion about to leave the device.
        spec:               the department.
        restricted_values:  the identifiers of this device's view.
    """
    hits = [m for m in _TOKEN_RE.finditer(text) if m.group(0) in restricted_values]
    if len({m.group(0) for m in hits}) >= EGRESS_MAX_ID_HITS:
        reason = f"{len(hits)} restricted identifiers in the conclusion"
        return EgressVerdict("blocked", f"[Blocked by the {spec.display_name} egress guard: {reason}] "
                                        f"{denial_message(spec)}", (reason,))
    if _table_lines(text) > EGRESS_MAX_TABLE_LINES:
        reason = "the conclusion looks like a raw data dump"
        return EgressVerdict("blocked", f"[Blocked by the {spec.display_name} egress guard: {reason}] "
                                        f"{denial_message(spec)}", (reason,))

    action, reasons = "pass", []
    if hits:
        # 从后往前替换，前面匹配到的位置不会被打乱
        for m in reversed(hits):
            text = text[:m.start()] + EGRESS_REDACTED + text[m.end():]
        action, reasons = "redacted", [f"{len(hits)} restricted identifier(s) redacted"]
    if len(text) > EGRESS_MAX_CHARS:
        text = text[:EGRESS_MAX_CHARS] + " ... [truncated by the egress guard]"
        action = "truncated" if action == "pass" else action
        reasons.append(f"conclusion truncated to {EGRESS_MAX_CHARS} chars")
    return EgressVerdict(action, text, tuple(reasons))


def apply_egress_guard(text: str, spec: DepartmentSpec, data_path: str) -> EgressVerdict:
    """Check a department conclusion against this device's restricted values, auditing any change."""
    verdict = guard_text(text, spec, load_restricted_values(spec, data_path))
    if verdict.action in ("redacted", "blocked"):
        record_denial(spec.name, "egress_guard", "; ".join(verdict.reasons))
    return verdict
