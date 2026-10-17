"""Row filters given as --filter "<dimension><op><value>"

Provides:
- Filter:           one parsed filter
- parse_filter:     parse and validate one --filter argument
- apply_filters:    keep the rows matching every filter

Key constraints:
- operators: = != in "not in"; in / not in take comma-separated values,
  e.g. "country in Germany,France" or "category=Lighting & Candles";
  values that contain commas are separated with | instead
- only spec.dimensions may be filtered; restricted columns are denied by
  the policy, unknown columns and unknown values are errors that list the
  valid names, so the agent can correct itself
"""

import difflib
import re
from dataclasses import dataclass

import pandas as pd

from core.data import policy
from core.data.constants import MAX_SUGGESTIONS
from core.data.errors import SkillError
from core.departments.base import DepartmentSpec


# 先试 "in" / "not in"（两边必须有空格），再试 != 和 =；!= 写在 = 前面，避免被拆开
_IN_RE = re.compile(r"^\s*(?P<column>\w+)\s+(?P<op>not\s+in|in)\s+(?P<value>.+?)\s*$", re.IGNORECASE)
_EQ_RE = re.compile(r"^\s*(?P<column>\w+)\s*(?P<op>!=|=)\s*(?P<value>.+?)\s*$")


@dataclass(frozen=True)
class Filter:
    """One row filter."""
    column: str
    op: str
    values: tuple[str, ...]

    @property
    def label(self) -> str:
        """The filter as text, for result messages."""
        joined = ",".join(self.values)
        return f"{self.column} {self.op} {joined}" if self.op in ("in", "not in") else f"{self.column}{self.op}{joined}"


def parse_filter(text: str, spec: DepartmentSpec, df: pd.DataFrame) -> Filter:
    """Parse one --filter argument and check its column and values.

    Raises:
        PolicyDenied:   the column is restricted.
        SkillError:     bad syntax, a column that is not a dimension, or values not in the data.
    """
    match = _IN_RE.match(text) or _EQ_RE.match(text)
    if not match:
        raise SkillError(f"invalid filter {text!r}; use '<dimension>=<value>', '<dimension>!=<value>' "
                         f"or '<dimension> in <v1>,<v2>'")

    column = match["column"]
    op = " ".join(match["op"].lower().split())
    policy.check_columns(spec, [column], purpose="filter by", allowed=spec.dimensions)

    raw = match["value"].strip().strip("'\"")
    if op in ("in", "not in"):
        # 值本身带逗号时（如 "Toys, Kids & Crafts"）用 | 分隔
        values = tuple(v.strip().strip("'\"") for v in raw.split("|" if "|" in raw else ","))
    else:
        values = (raw,)
    known = set(df[column].dropna().unique())
    unknown = [v for v in values if v not in known]
    if unknown:
        hints = difflib.get_close_matches(unknown[0], sorted(known), n=MAX_SUGGESTIONS, cutoff=0.4)
        raise SkillError(f"{column} has no value {unknown[0]!r}"
                         + (f"; did you mean one of {hints}?" if hints else
                            "; run dataset-profile with --values to list valid values"))
    return Filter(column, op, values)


def apply_filters(df: pd.DataFrame, filters: list[Filter]) -> pd.DataFrame:
    """Keep the rows matching every filter."""
    mask = pd.Series(True, index=df.index)
    for f in filters:
        if f.op == "=":
            mask &= df[f.column] == f.values[0]
        elif f.op == "!=":
            mask &= df[f.column] != f.values[0]
        elif f.op == "in":
            mask &= df[f.column].isin(f.values)
        else:
            mask &= ~df[f.column].isin(f.values)
    return df[mask]
