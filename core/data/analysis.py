"""Building blocks shared by the skill scripts

Provides:
- parse_group_by:   validate --group-by against the department's group columns
- scoped:           the view's rows after filters, with the requested time keys added
- with_labels:      add display columns (e.g. description next to stock_code)
- rank_groups:      the largest groups of a dimension, for grouped trends
- period_notes:     the standard notes describing a period

Key constraints:
- group-by goes through policy.check_columns, so a restricted column is
  denied before any computation happens
"""

import pandas as pd

from core.data import periods, policy
from core.data.cli import Context, split_list
from core.data.errors import SkillError
from core.data.filters import apply_filters
from core.data.metrics import compute


def parse_group_by(ctx: Context, text: str, max_keys: int = 1, *, allow_time: bool = True) -> list[str]:
    """Validate --group-by.

    Raises:
        PolicyDenied:   a restricted column was requested.
        SkillError:     too many keys or an unknown column.
    """
    keys = split_list(text)
    if len(keys) > max_keys:
        raise SkillError(f"--group-by takes at most {max_keys} dimension(s), got {keys}")
    allowed = ctx.spec.group_columns if allow_time else ctx.spec.dimensions
    policy.check_columns(ctx.spec, keys, purpose="group by", allowed=allowed)
    return keys


def scoped(ctx: Context, filters: list, keys=()) -> pd.DataFrame:
    """The view's rows matching every filter, with time keys for the requested group columns."""
    frame = apply_filters(ctx.df, filters)
    return periods.add_time_keys(frame, ctx.spec.date_column, keys)


def with_labels(table: pd.DataFrame, ctx: Context, keys) -> pd.DataFrame:
    """Turn the group index into columns and insert label columns right after their key.

    e.g. a stock_code column gets the matching description next to it.
    """
    frame = table.reset_index() if any(name is not None for name in table.index.names) else table.copy()
    for key in keys:
        label = ctx.spec.label_columns.get(key)
        if not label or key not in frame.columns:
            continue
        names = ctx.df.drop_duplicates(key).set_index(key)[label]
        frame.insert(frame.columns.get_loc(key) + 1, label, frame[key].map(names))
    return frame


def rank_groups(ctx: Context, frame: pd.DataFrame, key: str, metric: str, top: int) -> list[str]:
    """The `top` groups of `key`: by the metric when it adds up, otherwise by number of lines."""
    spec = ctx.spec
    by = metric if spec.metrics[metric].additive else "lines" if "lines" in spec.metrics else None
    if by is None:
        sizes = frame[frame["is_valid_sale"]].groupby(key).size()
    else:
        sizes = compute(frame, spec, [by], [key])[by]
    return [str(g) for g in sizes.sort_values(ascending=False).head(top).index]


def period_notes(ctx: Context, period: periods.Period, frame: pd.DataFrame, name: str = "period") -> list[str]:
    """Label, trading days and coverage notes of one period."""
    rows = periods.in_period(frame, ctx.spec.date_column, period)
    notes = [f"{name}: {period.label}, {periods.trading_days(rows, ctx.spec.date_column)} trading days"]
    return notes + periods.coverage_notes(ctx.dates, period, name)


def filter_note(filters: list) -> list[str]:
    """One note listing the filters, empty when there are none."""
    return [f"filters: {'; '.join(f.label for f in filters)}"] if filters else []
