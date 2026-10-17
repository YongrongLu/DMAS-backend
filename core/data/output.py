"""Standard skill results

Every skill script prints exactly one JSON object, and shell_executor returns
the same object to the model:

    {"status": "ok" | "error" | "denied", "skill", "message",
     "columns", "rows", "notes", "source"}

Provides:
- ok / error / denied:      build a result
- table_rows:               turn a DataFrame into JSON-safe columns and rows
- pct:                      format a relative change, e.g. "-12.0%"
- emit:                     print a result as one compact JSON line

Key constraints:
- numbers are rounded to 2 decimals; NaN and missing values become null
- source always names the view and the open dataset it derives from
"""

import json
import math

import numpy as np
import pandas as pd

from core.data.constants import DATASET_NAME
from core.data.policy import denial_message
from core.departments.base import DepartmentSpec


def source_line(spec: DepartmentSpec | None) -> str:
    """e.g. "sales_data.csv · derived from UCI Online Retail II"."""
    return f"{spec.csv_name} · derived from {DATASET_NAME}" if spec else f"derived from {DATASET_NAME}"


def clean(value):
    """Convert one cell to a JSON-safe value."""
    if value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        if math.isnan(value) or math.isinf(value):
            return None
        rounded = round(float(value), 2)
        return int(rounded) if rounded.is_integer() and abs(rounded) < 1e15 else rounded
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def table_rows(table: pd.DataFrame) -> tuple[list[str], list[list]]:
    """Columns and rows of a DataFrame, index included as leading columns when named."""
    frame = table.reset_index() if any(name is not None for name in table.index.names) else table
    columns = [str(c) for c in frame.columns]
    rows = [[clean(v) for v in row] for row in frame.itertuples(index=False, name=None)]
    return columns, rows


def pct(before, after) -> str | None:
    """Relative change as text, e.g. "-12.0%"; None when undefined."""
    if before is None or after is None:
        return None
    try:
        before, after = float(before), float(after)
    except (TypeError, ValueError):
        return None
    if math.isnan(before) or math.isnan(after) or before == 0:
        return None
    return f"{after / before - 1:+.1%}"


def share(part, whole) -> str | None:
    """part / whole as text, e.g. "37%"; None when undefined."""
    try:
        part, whole = float(part), float(whole)
    except (TypeError, ValueError):
        return None
    if math.isnan(part) or math.isnan(whole) or whole == 0:
        return None
    return f"{part / whole:.0%}"


def ok(skill: str, spec: DepartmentSpec, message: str, columns: list[str], rows: list[list],
       notes=()) -> dict:
    """A successful result."""
    return {
        "status": "ok",
        "skill": skill,
        "message": message,
        "columns": columns,
        "rows": rows,
        "notes": [n for n in notes if n],
        "source": source_line(spec),
    }


def error(skill: str, message: str, spec: DepartmentSpec | None = None) -> dict:
    """An invalid request; the message tells the agent how to fix it."""
    return {"status": "error", "skill": skill, "message": message, "columns": [], "rows": [],
            "notes": [], "source": source_line(spec)}


def denied(skill: str, spec: DepartmentSpec | None, reason: str, notes=()) -> dict:
    """A request refused by the data policy."""
    return {
        "status": "denied",
        "skill": skill,
        "message": denial_message(spec) if spec else "Access denied.",
        "columns": [],
        "rows": [],
        "notes": [reason, *notes],
        "source": source_line(spec),
    }


def emit(result: dict) -> None:
    """Print a result as one compact JSON line."""
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
