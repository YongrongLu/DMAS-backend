"""Time periods, time keys and coverage notes

Provides:
- Period:               an inclusive day range
- parse_bound:          parse YYYY-MM or YYYY-MM-DD into a period start or end
- parse_period:         parse "start:end" into a Period
- period_from_bounds:   a Period from optional --start / --end, defaulting to the data range
- in_period:            rows of a frame inside a Period
- add_time_keys:        add date / week / month key columns to a frame
- trading_days:         number of distinct days with at least one row
- key_bounds:           the first and last day of a date / week / month key
- closures:             gaps of CLOSURE_MIN_DAYS or more days without trading
- coverage_notes:       notes about a period the agent must not overlook

Key constraints:
- periods are inclusive on both ends; a bare month means the whole month
- coverage notes flag periods that run CLOSURE_MIN_DAYS or more past the data,
  and trading closures (gaps of CLOSURE_MIN_DAYS or more without any row) inside a period
"""

from dataclasses import dataclass

import pandas as pd

from core.data.constants import CLOSURE_MIN_DAYS
from core.data.errors import SkillError
from core.departments.base import TIME_DIMENSIONS


@dataclass(frozen=True)
class Period:
    """An inclusive day range."""
    start: pd.Timestamp
    end: pd.Timestamp

    @property
    def label(self) -> str:
        """e.g. "2010-02-01..2010-04-30"."""
        return f"{self.start:%Y-%m-%d}..{self.end:%Y-%m-%d}"


def parse_bound(text: str, *, is_end: bool) -> pd.Timestamp:
    """Parse a period bound.

    Args:
        text:       YYYY-MM or YYYY-MM-DD.
        is_end:     True for the last day of a period; a bare month then
                    means its last day.

    Raises:
        SkillError: when the text is not a valid date or month.
    """
    text = str(text).strip()
    try:
        if len(text) == 7:
            month = pd.Period(text, freq="M")
            return (month.end_time if is_end else month.start_time).normalize()
        if len(text) == 10:
            return pd.Timestamp(text).normalize()
    except (ValueError, TypeError):
        pass
    raise SkillError(f"invalid date {text!r}; use YYYY-MM or YYYY-MM-DD")


def parse_period(text: str) -> Period:
    """Parse "start:end", e.g. "2010-02:2010-04" or "2010-02-01:2010-04-30".

    Raises:
        SkillError: when the format is wrong or start is after end.
    """
    parts = str(text).split(":")
    if len(parts) != 2:
        raise SkillError(f"invalid period {text!r}; use START:END, e.g. 2010-02:2010-04")
    period = Period(parse_bound(parts[0], is_end=False), parse_bound(parts[1], is_end=True))
    if period.start > period.end:
        raise SkillError(f"invalid period {text!r}: start is after end")
    return period


def period_from_bounds(start: str | None, end: str | None, dates: pd.Series) -> Period:
    """Build a Period from optional bounds; a missing bound defaults to the data range."""
    first = parse_bound(start, is_end=False) if start else dates.min().normalize()
    last = parse_bound(end, is_end=True) if end else dates.max().normalize()
    if first > last:
        raise SkillError(f"--start {start} is after --end {end}")
    return Period(first, last)


def in_period(df: pd.DataFrame, date_column: str, period: Period) -> pd.DataFrame:
    """Rows whose date falls inside the period (both ends included)."""
    dates = df[date_column]
    return df[(dates >= period.start) & (dates < period.end + pd.Timedelta(days=1))]


def add_time_keys(df: pd.DataFrame, date_column: str, keys) -> pd.DataFrame:
    """Return a copy with the requested time key columns (date / week / month) added."""
    wanted = [k for k in keys if k in TIME_DIMENSIONS]
    if not wanted:
        return df
    out = df.copy()
    days = out[date_column].dt.normalize()
    for key in wanted:
        if key == "date":
            base, fmt = days, "%Y-%m-%d"
        elif key == "week":
            base, fmt = days - pd.to_timedelta(days.dt.weekday, unit="D"), "%Y-%m-%d"
        else:
            base, fmt = days - pd.to_timedelta(days.dt.day - 1, unit="D"), "%Y-%m"
        # 只格式化不重复的日期（几百个）：逐行 strftime 在 macOS 沙箱里慢到 50 秒以上
        out[key] = base.map({d: d.strftime(fmt) for d in base.unique()})
    return out


def key_bounds(key: str, freq_key: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The first and last day covered by a time key produced by add_time_keys."""
    if freq_key == "month":
        month = pd.Period(key, freq="M")
        return month.start_time.normalize(), month.end_time.normalize()
    start = pd.Timestamp(key)
    return start, start + pd.Timedelta(days=6 if freq_key == "week" else 0)


def trading_days(df: pd.DataFrame, date_column: str) -> int:
    """Number of distinct days with at least one row."""
    return int(df[date_column].dt.normalize().nunique())


def closures(dates: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Gaps of CLOSURE_MIN_DAYS or more days without any row, as (first, last) closed days."""
    days = pd.Series(sorted(dates.dt.normalize().unique()))
    gaps = []
    for previous, current in zip(days[:-1], days[1:]):
        if (current - previous).days - 1 >= CLOSURE_MIN_DAYS:
            gaps.append((previous + pd.Timedelta(days=1), current - pd.Timedelta(days=1)))
    return gaps


def coverage_notes(all_dates: pd.Series, period: Period, name: str = "period") -> list[str]:
    """Notes about a period: whether it runs past the data, and closures inside it.

    Args:
        all_dates:  the date column of the whole view, not just the period.
        period:     the period to check.
        name:       how to call the period in the notes, e.g. "period A".
    """
    notes = []
    first, last = all_dates.min().normalize(), all_dates.max().normalize()
    # 两头差几天不提示（例如数据最后一笔是 4 月 28 日，29 日是银行假日），差出一段才算超出数据范围
    if (first - period.start).days >= CLOSURE_MIN_DAYS or (period.end - last).days >= CLOSURE_MIN_DAYS:
        notes.append(f"{name} {period.label} extends beyond the data ({first:%Y-%m-%d}..{last:%Y-%m-%d}); "
                     f"only the covered days are counted")
    for gap_start, gap_end in closures(all_dates):
        if gap_start <= period.end and gap_end >= period.start:
            notes.append(f"no trading {gap_start:%Y-%m-%d}..{gap_end:%Y-%m-%d} (closure) inside {name}")
    return notes
