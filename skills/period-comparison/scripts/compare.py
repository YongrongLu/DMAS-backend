"""period-comparison: one metric in period A vs period B, in total or by group

Usage:
    python skills/period-comparison/scripts/compare.py --metric revenue \
        --period-a 2010-02:2010-04 --period-b 2011-02:2011-04
    python skills/period-comparison/scripts/compare.py --metric revenue --group-by stock_code \
        --period-a 2010-02:2010-04 --period-b 2011-02:2011-04 --status stopped --limit 10
"""

import pandas as pd

from core.data import analysis, cli, metrics, output, periods, policy
from core.data.constants import UNCHANGED_TOLERANCE
from core.data.errors import SkillError

SKILL = "period-comparison"
STATUSES = ("all", "stopped", "new", "continuing")
SORTS = ("decline", "growth", "abs")


def build_parser():
    """Arguments of this skill."""
    parser = cli.build_parser(SKILL, "Compare a metric between two periods.")
    cli.add_metric(parser)
    cli.add_periods(parser)
    cli.add_group_by(parser)
    cli.add_filters(parser)
    parser.add_argument("--status", default="all", choices=STATUSES, help="only groups with this status")
    parser.add_argument("--only-continuing", default="", help="keep only values of this dimension sold in both periods")
    parser.add_argument("--sort", default="decline", choices=SORTS, help="row order")
    cli.add_limit(parser)
    return parser


def _value(frame, spec, metric):
    """The metric's total on a frame."""
    return float(metrics.compute(frame, spec, [metric]).iloc[0, 0])


def _total_comparison(ctx, a, b, metric) -> tuple[list[str], list[list], list[str]]:
    """Total of A vs B, plus the volume x rate decomposition when the metric has one."""
    spec = ctx.spec
    va, vb = _value(a, spec, metric), _value(b, spec, metric)
    delta = vb - va
    columns = ["item", "period_a", "period_b", "delta", "own_change_pct", "share_of_total_change"]
    rows = [[metric, va, vb, delta, output.pct(va, vb), None]]
    notes = []

    if metric in spec.decompositions:
        volume, rate = spec.decompositions[metric]
        xa, xb = _value(a, spec, volume), _value(b, spec, volume)
        ra, rb = _value(a, spec, rate), _value(b, spec, rate)
        rows.append([volume, xa, xb, xb - xa, output.pct(xa, xb), None])
        rows.append([rate, ra, rb, rb - ra, output.pct(ra, rb), None])
        # 先算量的影响（按 A 期的率），再算率的影响（按 B 期的量），两者相加正好等于总变化
        volume_effect = (xb - xa) * ra
        rate_effect = (rb - ra) * xb
        rows.append([f"effect of {volume}", None, None, volume_effect, None, output.share(volume_effect, delta)])
        rows.append([f"effect of {rate}", None, None, rate_effect, None, output.share(rate_effect, delta)])
        notes.append(f"{metric} = {volume} x {rate}; the two effects add up to the total change")

    counts_a, counts_b = policy.entity_counts(a, spec, []), policy.entity_counts(b, spec, [])
    if counts_a is not None and min(counts_a.iloc[0], counts_b.iloc[0]) < spec.k_anon_min:
        rows = [[r[0], None, None, None, None, None] for r in rows]
        notes.extend(policy.suppression_note(len(rows), spec))
    return columns, [[output.clean(v) for v in row] for row in rows], notes


def _status(present_a: set, present_b: set, group) -> str:
    """stopped / new / continuing, from whether the group sold in each period."""
    if group in present_a and group in present_b:
        return "continuing"
    return "stopped" if group in present_a else "new"


def _grouped_comparison(ctx, a, b, metric, key, args) -> tuple[list[str], list[list], list[str]]:
    """A vs B per group, with status, contribution and a summary of the range changes."""
    spec = ctx.spec
    additive = spec.metrics[metric].additive
    table = pd.concat({
        "period_a": metrics.compute(a, spec, [metric], [key])[metric],
        "period_b": metrics.compute(b, spec, [metric], [key])[metric],
    }, axis=1)
    if additive:
        table = table.fillna(0.0)
    present_a = set(a[a["is_valid_sale"]][key])
    present_b = set(b[b["is_valid_sale"]][key])
    table["status"] = [_status(present_a, present_b, g) for g in table.index]
    table["delta"] = table["period_b"] - table["period_a"]
    table["own_change_pct"] = [output.pct(x, y) for x, y in zip(table["period_a"], table["period_b"])]

    total_a, total_b = _value(a, spec, metric), _value(b, spec, metric)
    total_delta = total_b - total_a
    notes = [f"total {metric}: {output.clean(total_a)} -> {output.clean(total_b)} ({output.pct(total_a, total_b)})"]
    notes.extend(_range_summary(table, additive, key))

    if args.status != "all":
        table = table[table["status"] == args.status]
    order = {"decline": table["delta"], "growth": -table["delta"], "abs": -table["delta"].abs()}[args.sort]
    table = table.loc[order.sort_values(na_position="last").index]

    if additive:
        table["share_of_total_change"] = [output.share(d, total_delta) for d in table["delta"]]
    counts = policy.entity_counts(pd.concat([a, b]), spec, [key])
    value_columns = [c for c in ("period_a", "period_b", "delta", "own_change_pct", "share_of_total_change") if c in table]
    table, suppressed = policy.suppress_small_groups(table, counts, spec, value_columns)
    table, capped = policy.cap_rows(table, args.limit)
    if additive:
        cumulative = pd.to_numeric(table["delta"], errors="coerce").fillna(0).cumsum()
        table["cumulative_share_of_total_change"] = [output.share(c, total_delta) for c in cumulative]

    ordered = ["period_a", "period_b", "delta", "own_change_pct",
               *(["share_of_total_change", "cumulative_share_of_total_change"] if additive else []), "status"]
    table.index.name = key
    columns, rows = output.table_rows(analysis.with_labels(table[ordered], ctx, [key]))
    return columns, rows, [*notes, *capped, *policy.suppression_note(suppressed, spec)]


def _range_summary(table: pd.DataFrame, additive: bool, key: str) -> list[str]:
    """How many groups stopped, started or continued, and what that means for the metric."""
    counts = table["status"].value_counts()
    if additive:
        stopped = table.loc[table["status"] == "stopped", "period_a"].sum()
        new = table.loc[table["status"] == "new", "period_b"].sum()
        cont = table[table["status"] == "continuing"]
        return [
            f"{key} that stopped (sold in A, not in B): {counts.get('stopped', 0)}, worth {output.clean(stopped)} in A",
            f"{key} that are new (sold in B, not in A): {counts.get('new', 0)}, worth {output.clean(new)} in B",
            f"net effect of stopped and new {key}: {output.clean(new - stopped)}",
            f"continuing {key}: {counts.get('continuing', 0)}, {output.clean(cont['period_a'].sum())} -> "
            f"{output.clean(cont['period_b'].sum())} ({output.pct(cont['period_a'].sum(), cont['period_b'].sum())})",
        ]
    cont = table[table["status"] == "continuing"].dropna(subset=["period_a", "period_b"])
    if cont.empty:
        return []
    change = cont["period_b"] / cont["period_a"].where(cont["period_a"] != 0) - 1
    up, down = (change > UNCHANGED_TOLERANCE).mean(), (change < -UNCHANGED_TOLERANCE).mean()
    return [f"continuing {key} ({len(cont)}): higher in B {up:.0%}, lower {down:.0%}, "
            f"unchanged {1 - up - down:.0%} (within {UNCHANGED_TOLERANCE:.1%})"]


def run(ctx: cli.Context, args) -> dict:
    """Compare the metric between the two periods."""
    spec = ctx.spec
    metrics.resolve(spec, [args.metric])
    keys = analysis.parse_group_by(ctx, args.group_by, 1, allow_time=False)
    if args.status != "all" and not keys:
        raise SkillError("--status needs --group-by")

    filters = cli.parse_filters(ctx, args.filter)
    period_a, period_b = periods.parse_period(args.period_a), periods.parse_period(args.period_b)
    frame = analysis.scoped(ctx, filters)
    a = periods.in_period(frame, spec.date_column, period_a)
    b = periods.in_period(frame, spec.date_column, period_b)

    extra = []
    if args.only_continuing:
        dim = args.only_continuing
        policy.check_columns(spec, [dim], purpose="restrict by", allowed=spec.dimensions)
        both = set(a[a["is_valid_sale"]][dim]) & set(b[b["is_valid_sale"]][dim])
        a, b = a[a[dim].isin(both)], b[b[dim].isin(both)]
        extra.append(f"only {dim} values sold in both periods ({len(both)})")

    if keys:
        columns, rows, notes = _grouped_comparison(ctx, a, b, args.metric, keys[0], args)
    else:
        columns, rows, notes = _total_comparison(ctx, a, b, args.metric)

    by = f" by {keys[0]}" if keys else ""
    return output.ok(
        SKILL, spec, f"{args.metric}{by}: B {period_b.label} vs A {period_a.label}", columns, rows,
        [*analysis.period_notes(ctx, period_a, frame, "period A"),
         *analysis.period_notes(ctx, period_b, frame, "period B"),
         *analysis.filter_note(filters), *extra, *notes],
    )


if __name__ == "__main__":
    cli.run_skill(SKILL, build_parser(), run)
