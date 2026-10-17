"""Data access policy of a department device

Provides:
- check_columns:            deny restricted columns, reject unknown ones
- entity_counts:            distinct entities per group, for k-anonymity
- suppress_small_groups:    blank out groups with fewer than k entities
- cap_rows:                 enforce MAX_RESULT_ROWS
- denial_message:           the PRD §9 answer to a raw-data request
- check_output:             scan a finished skill result before it reaches the model

Key constraints:
- restricted columns (personal data, row-level identifiers) can never be
  grouped by, filtered by or returned; asking for one is "denied", not "error"
- k-anonymity only applies to departments with an entity_column (customer);
  a suppressed group keeps its label but loses every number
- check_output is the last gate inside the executor: it rejects results with
  too many rows and any string that contains a restricted value
"""

import re

import pandas as pd

from core.data.constants import DENIAL_MESSAGE, MAX_RESULT_ROWS
from core.data.errors import PolicyDenied, SkillError
from core.departments.base import DepartmentSpec


SUPPRESSED = "suppressed"
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def check_columns(spec: DepartmentSpec, columns, *, purpose: str, allowed) -> None:
    """Check that every column may be used for the given purpose.

    Args:
        spec:       the department.
        columns:    the requested columns.
        purpose:    "group by" / "filter by", used in the messages.
        allowed:    the columns valid for this purpose.

    Raises:
        PolicyDenied:   a column is restricted.
        SkillError:     a column is not allowed for this purpose.
    """
    for column in columns:
        if column in spec.restricted_columns:
            raise PolicyDenied(
                f"'{column}' is {spec.restricted_columns[column]} and cannot be used to {purpose} "
                f"or leave this device; use an aggregate over {sorted(spec.dimensions)} instead"
            )
        if column not in allowed:
            raise SkillError(f"cannot {purpose} {column!r}; available: {sorted(allowed)}")


def entity_counts(df: pd.DataFrame, spec: DepartmentSpec, keys) -> pd.Series | None:
    """Distinct entities (e.g. customers) per group, on every row in scope.

    Returns:
        None when the department has no entity column; otherwise counts
        indexed like metrics.compute output.
    """
    if spec.entity_column is None:
        return None
    keys = list(keys)
    if not keys:
        return pd.Series([df[spec.entity_column].nunique()], index=pd.Index(["all"], name="group"))
    return df.groupby(keys, observed=True, sort=False)[spec.entity_column].nunique()


def suppress_small_groups(table: pd.DataFrame, counts: pd.Series | None, spec: DepartmentSpec,
                          value_columns) -> tuple[pd.DataFrame, int]:
    """Blank out the values of groups with fewer than spec.k_anon_min entities.

    Args:
        table:          metric table indexed like counts.
        counts:         entity_counts output, or None (nothing to suppress).
        spec:           the department.
        value_columns:  the columns to blank out.

    Returns:
        the table (copied when changed) and how many groups were suppressed.
    """
    if counts is None:
        return table, 0
    small = counts.reindex(table.index).fillna(0) < spec.k_anon_min
    if not small.any():
        return table, 0
    table = table.copy()
    table[list(value_columns)] = table[list(value_columns)].astype(object)
    table.loc[small, list(value_columns)] = None
    return table, int(small.sum())


def suppression_note(count: int, spec: DepartmentSpec) -> list[str]:
    """The note explaining suppressed groups, empty when none were suppressed."""
    if not count:
        return []
    return [f"{count} group(s) with fewer than {spec.k_anon_min} {spec.entity_column} values were "
            f"suppressed for privacy (shown without numbers)"]


def cap_rows(table: pd.DataFrame, limit: int) -> tuple[pd.DataFrame, list[str]]:
    """Keep at most min(limit, MAX_RESULT_ROWS) rows.

    Returns:
        the capped table and a note when rows were dropped.
    """
    if limit < 1:
        raise SkillError(f"--limit must be at least 1, got {limit}")
    keep = min(limit, MAX_RESULT_ROWS)
    if len(table) <= keep:
        return table, []
    return table.head(keep), [f"showing {keep} of {len(table)} rows"]


def denial_message(spec: DepartmentSpec) -> str:
    """The answer to a raw-data export request."""
    return DENIAL_MESSAGE.format(record_label=spec.record_label, department=spec.name)


def _strings(value):
    """Yield every string inside a JSON-like value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def check_output(result: dict, restricted_values: frozenset[str]) -> str | None:
    """Scan a skill result before the executor hands it to the model.

    Numbers are not scanned: a revenue of 15616 must not be mistaken for a
    customer id. Identifiers only leak as strings (a group label, a note).

    Returns:
        the reason the result must be denied, or None when it may pass.
    """
    rows = result.get("rows")
    if isinstance(rows, list) and len(rows) > MAX_RESULT_ROWS:
        return f"result has {len(rows)} rows, more than the {MAX_RESULT_ROWS} allowed"

    if restricted_values:
        for text in _strings({k: v for k, v in result.items() if k != "source"}):
            for token in _TOKEN_RE.findall(text):
                if token in restricted_values:
                    return "result contains a restricted identifier"
    return None
