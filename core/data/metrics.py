"""Named metric computation over a department view

Provides:
- resolve:          validate metric names against a department
- compute:          compute metrics for a frame, optionally grouped

Key constraints:
- every base metric is computed on its own row set (valid sales or returns)
  and the groups are then aligned; a group missing from one row set gets 0
  for sum / count / nunique and NaN for median
- ratios divide the summed base metrics; a zero denominator gives NaN
- without group keys the result has a single row indexed "all"
"""

import numpy as np
import pandas as pd

from core.data.errors import SkillError
from core.departments.base import DepartmentSpec, Metric


TOTAL_KEY = "all"


def resolve(spec: DepartmentSpec, names) -> list[Metric]:
    """Return the Metric objects for the given names.

    Raises:
        SkillError: on an unknown name; the message lists the department's metrics.
    """
    metrics = []
    for name in names:
        if name not in spec.metrics:
            raise SkillError(f"unknown metric {name!r} for {spec.name}; available: {sorted(spec.metrics)}")
        metrics.append(spec.metrics[name])
    return metrics


def _base_names(spec: DepartmentSpec, metrics: list[Metric]) -> list[str]:
    """The non-ratio metrics needed to compute the given metrics, in first-use order."""
    names: list[str] = []
    for metric in metrics:
        parts = [metric.numerator, metric.denominator] if metric.kind == "ratio" else [metric.name]
        for part in parts:
            if part not in names:
                names.append(part)
    return names


def _rows(df: pd.DataFrame, metric: Metric) -> pd.DataFrame:
    """The row set a base metric is computed on."""
    return df[df["is_return"]] if metric.rows == "returns" else df[df["is_valid_sale"]]


def _base_series(df: pd.DataFrame, metric: Metric, keys: list[str]) -> pd.Series:
    """Compute one base metric, grouped by keys or as a single total."""
    rows = _rows(df, metric)
    if keys:
        grouped = rows.groupby(keys, observed=True, sort=False)
        values = grouped.size() if metric.kind == "count" else grouped[metric.column].agg(metric.kind)
    else:
        if metric.kind == "count":
            total = len(rows)
        elif metric.kind == "nunique":
            total = rows[metric.column].nunique()
        elif metric.kind == "median":
            total = rows[metric.column].median() if len(rows) else np.nan
        else:
            total = rows[metric.column].sum()
        values = pd.Series([total], index=pd.Index([TOTAL_KEY], name="group"))
    values = values.astype(float)
    return -values if metric.negate else values


def compute(df: pd.DataFrame, spec: DepartmentSpec, names, keys=()) -> pd.DataFrame:
    """Compute named metrics.

    Args:
        df:     rows already restricted to the period and filters.
        spec:   the department, for metric definitions.
        names:  metric names, in output order.
        keys:   group-by columns; empty for a single total row.

    Returns:
        one column per metric name, indexed by the group keys (or "all").
    """
    keys = list(keys)
    metrics = resolve(spec, names)
    base = {}
    for name in _base_names(spec, metrics):
        metric = spec.metrics[name]
        base[name] = _base_series(df, metric, keys)

    table = pd.concat(base, axis=1)
    for name, metric in spec.metrics.items():
        if name in base and metric.kind != "median":
            table[name] = table[name].fillna(0.0)

    for metric in metrics:
        if metric.kind == "ratio":
            denominator = table[metric.denominator].replace(0, np.nan)
            table[metric.name] = table[metric.numerator] / denominator
    return table[[m.name for m in metrics]]
