"""anomaly-detection: periods whose change vs the previous period is unusually large

Each series (the total, or each of the largest groups) gets the z-score of
its period-over-period changes; periods with |z| >= threshold are reported.

Usage:
    python skills/anomaly-detection/scripts/anomalies.py --metric revenue --freq week --start 2010-12 --end 2011-04
"""

import numpy as np
import pandas as pd

from core.data import analysis, cli, metrics, output, periods, policy
from core.data.constants import DEFAULT_TOP_GROUPS, DEFAULT_Z_THRESHOLD, MAX_TOP_GROUPS, MIN_ANOMALY_PERIODS
from core.data.errors import SkillError

SKILL = "anomaly-detection"
FREQ_KEY = {"week": "week", "month": "month"}
# 交易日少于典型值的这个比例，就提示是不完整的时间段
PARTIAL_PERIOD_SHARE = 0.8


def build_parser():
    """Arguments of this skill."""
    parser = cli.build_parser(SKILL, "Find unusual period-over-period changes.")
    cli.add_metric(parser)
    parser.add_argument("--freq", default="week", choices=tuple(FREQ_KEY), help="time grain")
    cli.add_group_by(parser)
    parser.add_argument("--top-groups", type=int, default=DEFAULT_TOP_GROUPS, help="series to scan when grouped")
    parser.add_argument("--threshold", type=float, default=DEFAULT_Z_THRESHOLD, help="|z| that counts as unusual")
    cli.add_filters(parser)
    cli.add_range(parser)
    cli.add_limit(parser)
    return parser


def _period_note(period: str, freq_key: str, days: pd.Series, gaps) -> str:
    """Why a period may not be a real business change: a closure or few trading days."""
    start, end = periods.key_bounds(period, freq_key)
    for gap_start, gap_end in gaps:
        if gap_start <= end and gap_end >= start:
            return f"overlaps a trading closure {gap_start:%Y-%m-%d}..{gap_end:%Y-%m-%d}"
    if days.get(period, 0) < PARTIAL_PERIOD_SHARE * days.median():
        return f"only {int(days.get(period, 0))} trading days"
    return ""


def _scan(series: pd.Series, days: pd.Series, threshold: float, group, freq_key: str, gaps) -> list[dict]:
    """Score one series; return its unusual periods."""
    series = series.sort_index()
    change = series.pct_change().replace([np.inf, -np.inf], np.nan)
    valid = change.dropna()
    if len(valid) < MIN_ANOMALY_PERIODS or valid.std() == 0:
        return []
    z = (change - valid.mean()) / valid.std()
    found = []
    for period in z.index:
        if pd.isna(z[period]) or abs(z[period]) < threshold:
            continue
        previous = series.index[series.index.get_loc(period) - 1]
        note = _period_note(period, freq_key, days, gaps)
        found.append({
            "period": period, "group": group, "value": series[period], "previous": series[previous],
            "change": output.pct(series[previous], series[period]), "z_score": round(float(z[period]), 2),
            "direction": "spike" if z[period] > 0 else "drop", "note": note,
        })
    return found


def run(ctx: cli.Context, args) -> dict:
    """Scan the total or the largest groups for unusual changes."""
    spec = ctx.spec
    metrics.resolve(spec, [args.metric])
    keys = analysis.parse_group_by(ctx, args.group_by, 1, allow_time=False)
    if not 1 <= args.top_groups <= MAX_TOP_GROUPS:
        raise SkillError(f"--top-groups must be between 1 and {MAX_TOP_GROUPS}")
    if args.threshold <= 0:
        raise SkillError("--threshold must be positive")

    freq_key = FREQ_KEY[args.freq]
    filters = cli.parse_filters(ctx, args.filter)
    period = periods.period_from_bounds(args.start, args.end, ctx.dates)
    frame = periods.in_period(analysis.scoped(ctx, filters, [freq_key]), spec.date_column, period)

    found, notes = [], []
    gaps = periods.closures(ctx.dates)
    if keys:
        key = keys[0]
        groups = analysis.rank_groups(ctx, frame, key, args.metric, args.top_groups)
        counts = policy.entity_counts(frame, spec, [key])
        if counts is not None:
            skipped = [g for g in groups if counts.get(g, 0) < spec.k_anon_min]
            groups = [g for g in groups if g not in skipped]
            notes.extend(policy.suppression_note(len(skipped), spec))
        for group in groups:
            subset = frame[frame[key].astype(str) == group]
            days = subset.groupby(freq_key)[spec.date_column].agg(lambda d: d.dt.normalize().nunique())
            series = metrics.compute(subset, spec, [args.metric], [freq_key])[args.metric]
            found += _scan(series, days, args.threshold, group, freq_key, gaps)
        notes.append(f"scanned the top {len(groups)} {key} values")
    else:
        days = frame.groupby(freq_key)[spec.date_column].agg(lambda d: d.dt.normalize().nunique())
        series = metrics.compute(frame, spec, [args.metric], [freq_key])[args.metric]
        found = _scan(series, days, args.threshold, None, freq_key, gaps)

    table = pd.DataFrame(found, columns=["period", "group", "value", "previous", "change", "z_score", "direction", "note"])
    if not keys:
        table = table.drop(columns="group")
    table = table.reindex(table["z_score"].abs().sort_values(ascending=False).index)
    table, capped = policy.cap_rows(table, args.limit)
    columns, rows = output.table_rows(table)
    notes = [
        *analysis.period_notes(ctx, period, frame), *analysis.filter_note(filters), *notes,
        f"method: z-score of {args.freq}-over-{args.freq} changes within each series; |z| >= {args.threshold}",
        f"{len(found)} unusual period(s) found" if found else "no unusual periods at this threshold",
        *capped,
    ]
    return output.ok(SKILL, spec, f"unusual {args.freq}ly changes in {args.metric}, {period.label}", columns, rows, notes)


if __name__ == "__main__":
    cli.run_skill(SKILL, build_parser(), run)
