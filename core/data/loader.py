"""Read-only loading of a department view

Provides:
- load_frame:                   load and validate one department view
- load_restricted_values:       the values of the restricted columns, for output scanning

Key constraints:
- the file is opened read-only and never written back
- identifier and text columns are read as strings, so "12346" stays "12346"
- results are cached per (path, mtime): a rebuilt view is reloaded automatically
"""

import os
from functools import lru_cache

import pandas as pd

from core.data.errors import SkillError
from core.departments.base import FLAG_COLUMNS, DepartmentSpec


# 这些列按字符串读，避免 customer_id / stock_code 被转成数字
STRING_COLUMNS = ("invoice_id", "customer_id", "stock_code", "description", "category", "segment", "country")
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


@lru_cache(maxsize=4)
def _read(path: str, mtime_ns: int, columns: tuple[str, ...], date_column: str) -> pd.DataFrame:
    """Read the needed columns of a view and parse its dates; cached until the file changes."""
    header = pd.read_csv(path, nrows=0).columns
    missing = sorted(set(columns) - set(header))
    if missing:
        raise SkillError(f"data file {os.path.basename(path)} is missing columns {missing}")

    dtypes = {c: str for c in STRING_COLUMNS if c in columns}
    dtypes.update({c: bool for c in FLAG_COLUMNS if c in columns})
    df = pd.read_csv(path, usecols=list(columns), dtype=dtypes)
    df[date_column] = pd.to_datetime(df[date_column], format=DATE_FORMAT)
    return df


def load_frame(spec: DepartmentSpec, path: str) -> pd.DataFrame:
    """Load one department view with its date column parsed.

    Args:
        spec:   the department the view belongs to.
        path:   the view's CSV path.

    Returns:
        a DataFrame with exactly spec.required_columns; callers must not modify it in place.

    Raises:
        SkillError: when the file is missing or lacks a required column.
    """
    if not os.path.isfile(path):
        raise SkillError(f"data file not found: {path}")

    return _read(path, os.stat(path).st_mtime_ns, tuple(spec.required_columns), spec.date_column)


@lru_cache(maxsize=8)
def _restricted_values(path: str, mtime_ns: int, columns: tuple[str, ...]) -> frozenset[str]:
    """Read the distinct values of the given columns; cached until the file changes."""
    df = pd.read_csv(path, usecols=list(columns), dtype=str)
    values: set[str] = set()
    for column in columns:
        values.update(df[column].dropna().unique())
    return frozenset(values)


def load_restricted_values(spec: DepartmentSpec, path: str) -> frozenset[str]:
    """Return every value of the view's restricted columns (customer ids, invoice ids, ...).

    Used to scan results and summaries for leaked identifiers before they
    leave the skill or the device. Empty when the view has no restricted column.
    """
    if not spec.restricted_columns or not os.path.isfile(path):
        return frozenset()
    return _restricted_values(path, os.stat(path).st_mtime_ns, tuple(sorted(spec.restricted_columns)))
