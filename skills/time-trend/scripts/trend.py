"""time-trend: a metric over time, with period-over-period and year-over-year change

Usage:
    python skills/time-trend/scripts/trend.py --metric revenue --freq month --start 2010-12 --end 2011-04
    python skills/time-trend/scripts/trend.py --metric revenue --freq month --group-by category --top-groups 5
"""

import pandas as pd

from core.data import analysis, cli, metrics, output, periods, policy
from core.data.constants import DEFAULT_TOP_GROUPS, MAX_RESULT_ROWS, MAX_TOP_GROUPS
from core.data.errors import SkillError

SKILL = "time-trend"
FREQS = ("day", "week", "month")
FREQ_KEY = {"day": "date", "week": "week", "month": "month"}


def build_parser():
    """Arguments of this skill."""
    parser = cli.build_parser(SKILL, "A metric over time.")
    cli.add_metric(parser)
    parser.add_argument("--freq", default="month", choices=FREQS, help="time grain")
    cli.add_group_by(parser)
    parser.add_argument("--top-groups", type=int, default=DEFAULT_TOP_GROUPS, help="series to show when grouped")
    cli.add_filters(parser)
    cli.add_range(parser)
    return parser


def _last_year(month: str) -> str:
    """"2011-03" -> "2010-03"."""
    return str(pd.Period(month, freq="M") - 12)


def _single_series(ctx, frame_all, period, metric, freq_key) -> tuple[list[str], list[list], list[str]]:
    """One series: value, change vs previous period, change vs last year (monthly), trading days."""
    spec = ctx.spec
    table = metrics.compute(frame_all, spec, [metric], [freq_key])[metric].sort_index()
    in_range = periods.in_period(frame_all, spec.date_column, period)
    shown = sorted(in_range[freq_key].unique())
    days = in_range.groupby(freq_key)[spec.date_column].agg(lambda d: d.dt.normalize().nunique())

    counts = policy.entity_counts(frame_all, spec, [freq_key])
    small = set() if counts is None else set(counts[counts < spec.k_anon_min].index)

    columns = ["period", metric] + (["change_vs_last_year"] if freq_key == "month" else []) + ["change_vs_previous", "trading_days"]
    rows = []
    previous = None
    for key in sorted(table.index):
        value = table[key]
        if key in shown:
            hidden = key in small
            row = [key, None if hidden else value]
            if freq_key == "month":
                last = table.get(_last_year(key))
                row.append(None if hidden else output.pct(last, value))
            row.append(None if hidden or previous is None else output.pct(previous, value))
            row.append(int(days.get(key, 0)))
            rows.append([output.clean(v) for v in row])
        previous = value
    notes = [f"{len(small & set(shown))} period(s) suppressed for privacy"] if small & set(shown) else []
    return columns, rows, notes


def _grouped_series(ctx, frame, metric, freq_key, group_key, top) -> tuple[list[str], list[list], list[str]]:
    """Several series side by side: one column per group, one row per period."""
    spec = ctx.spec
    groups = analysis.rank_groups(ctx, frame, group_key, metric, top)
    subset = frame[frame[group_key].astype(str).isin(groups)]
    table = metrics.compute(subset, spec, [metric], [freq_key, group_key])[metric]

    counts = policy.entity_counts(subset, spec, [freq_key, group_key])
    if counts is not None:
        table = table.astype(object)
        table[counts.reindex(table.index).fillna(0) < spec.k_anon_min] = None

    wide = table.unstack(group_key).reindex(columns=groups).sort_index()
    columns = ["period", *[str(g) for g in wide.columns]]
    rows = [[key, *[output.clean(v) for v in values]] for key, values in zip(wide.index, wide.to_numpy())]
    return columns, rows, [f"series: the top {len(groups)} {group_key} values by {metric if spec.metrics[metric].additive else 'number of lines'}"]


def run(ctx: cli.Context, args) -> dict:
    """The metric per period, alone or for the largest groups."""
    spec = ctx.spec
    metrics.resolve(spec, [args.metric])
    group_keys = analysis.parse_group_by(ctx, args.group_by, 1, allow_time=False)
    if not 1 <= args.top_groups <= MAX_TOP_GROUPS:
        raise SkillError(f"--top-groups must be between 1 and {MAX_TOP_GROUPS}")

    freq_key = FREQ_KEY[args.freq]
    filters = cli.parse_filters(ctx, args.filter)
    period = periods.period_from_bounds(args.start, args.end, ctx.dates)
    frame_all = analysis.scoped(ctx, filters, [freq_key])

    if group_keys:
        frame = periods.in_period(frame_all, spec.date_column, period)
        columns, rows, extra = _grouped_series(ctx, frame, args.metric, freq_key, group_keys[0], args.top_groups)
    else:
        columns, rows, extra = _single_series(ctx, frame_all, period, args.metric, freq_key)

    notes = [*analysis.period_notes(ctx, period, frame_all), *analysis.filter_note(filters), *extra]
    if len(rows) > MAX_RESULT_ROWS:
        notes.append(f"showing the last {MAX_RESULT_ROWS} of {len(rows)} periods; narrow --start/--end or use a coarser --freq")
        rows = rows[-MAX_RESULT_ROWS:]
    by = f" by {group_keys[0]}" if group_keys else ""
    return output.ok(SKILL, spec, f"{args.metric} per {args.freq}{by}, {period.label}", columns, rows, notes)


if __name__ == "__main__":
    cli.run_skill(SKILL, build_parser(), run)
