"""Egress guard -- the last check on a department's conclusion before it leaves the device

Called by the finish node of every department graph, right before the
result is handed back for sending to the orchestrator.

Provides:
- EgressVerdict:        what the guard decided and the text to send
- guard_text:           check one conclusion
- apply_egress_guard:   check a conclusion and audit the decision

Key constraints:
- identifiers are matched against the real values of the sensitive columns
  listed in the department card (e.g. customer ids), never against a pattern alone
- numbers are not identifiers: "£15,616", "15616.5" and "15616%" are skipped
- fewer than EGRESS_MAX_ID_HITS identifiers are redacted; that many or more,
  or more than EGRESS_MAX_TABLE_LINES raw CSV-like lines, blocks the whole
  conclusion; markdown tables of aggregates pass; an over-long conclusion is truncated
- every redaction or block is audited with the 🔒 line on the device terminal
"""

import re
from dataclasses import dataclass

import os
from functools import lru_cache

import pandas as pd

from core.departments import DepartmentCard
from core.middlewares.audit import record_denial
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


def guard_text(text: str, card: DepartmentCard, restricted_values: frozenset[str]) -> EgressVerdict:
    """Check one department conclusion.

    Args:
        text:               the conclusion about to leave the device.
        card:               the department.
        restricted_values:  the identifiers of this device's sensitive columns.
    """
    hits = [m for m in _TOKEN_RE.finditer(text) if m.group(0) in restricted_values]
    if len({m.group(0) for m in hits}) >= EGRESS_MAX_ID_HITS:
        reason = f"{len(hits)} restricted identifiers in the conclusion"
        return EgressVerdict("blocked", f"[Blocked by the {card.display_name} egress guard: {reason}] "
                                        f"{card.denial_message}", (reason,))
    if _table_lines(text) > EGRESS_MAX_TABLE_LINES:
        reason = "the conclusion looks like a raw data dump"
        return EgressVerdict("blocked", f"[Blocked by the {card.display_name} egress guard: {reason}] "
                                        f"{card.denial_message}", (reason,))

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


@lru_cache(maxsize=16)
def _column_values(path: str, mtime_ns: int, column: str) -> frozenset[str]:
    """Distinct values of one column of a CSV or Excel file; cached until the file changes."""
    reader = pd.read_excel if path.endswith((".xlsx", ".xls")) else pd.read_csv
    try:
        values = reader(path, usecols=[column], dtype=str)[column].dropna().unique()
    except (ValueError, KeyError):
        return frozenset()
    return frozenset(values)


def load_sensitive_values(card: DepartmentCard) -> frozenset[str]:
    """Every value of the sensitive columns listed in the department card."""
    values: set[str] = set()
    for item in card.sensitive:
        path = os.path.join(card.shared_dir, item["file"])
        if os.path.isfile(path):
            values |= _column_values(path, os.stat(path).st_mtime_ns, item["column"])
    return frozenset(values)


def apply_egress_guard(text: str, card: DepartmentCard) -> EgressVerdict:
    """Check a department conclusion against this device's sensitive values, auditing any change."""
    verdict = guard_text(text, card, load_sensitive_values(card))
    if verdict.action in ("redacted", "blocked"):
        record_denial(card.name, "egress_guard", "; ".join(verdict.reasons))
    return verdict
