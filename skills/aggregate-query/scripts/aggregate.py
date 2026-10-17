"""aggregate-query: filter, group, aggregate, sort and take the top N

Usage:
    python skills/aggregate-query/scripts/aggregate.py --metrics revenue,orders --group-by country \
        --start 2011-02 --end 2011-04 --limit 10
"""

from core.data import analysis, cli, metrics, output, periods, policy
from core.data.constants import MAX_GROUP_BY
from core.data.errors import SkillError

SKILL = "aggregate-query"


def build_parser():
    """Arguments of this skill."""
    parser = cli.build_parser(SKILL, "Aggregate metrics, optionally grouped.")
    cli.add_metric(parser, many=True)
    cli.add_group_by(parser)
    cli.add_filters(parser)
    cli.add_range(parser)
    parser.add_argument("--sort-by", default="", help="metric to sort by (default: the first metric)")
    parser.add_argument("--ascending", action="store_true", help="smallest first")
    cli.add_limit(parser)
    return parser


def run(ctx: cli.Context, args) -> dict:
    """Aggregate the requested metrics over the period and filters."""
    spec = ctx.spec
    names = cli.split_list(args.metrics)
    metrics.resolve(spec, names)
    keys = analysis.parse_group_by(ctx, args.group_by, MAX_GROUP_BY)
    sort_by = args.sort_by or names[0]
    if sort_by not in names:
        raise SkillError(f"--sort-by must be one of the requested metrics {names}")

    filters = cli.parse_filters(ctx, args.filter)
    period = periods.period_from_bounds(args.start, args.end, ctx.dates)
    frame = periods.in_period(analysis.scoped(ctx, filters, keys), spec.date_column, period)

    table = metrics.compute(frame, spec, names, keys)
    if keys and spec.metrics[sort_by].additive:
        total = table[sort_by].sum()
        table[f"share_of_{sort_by}"] = [output.share(v, total) for v in table[sort_by]]
    value_columns = list(table.columns)
    table, suppressed = policy.suppress_small_groups(
        table, policy.entity_counts(frame, spec, keys), spec, value_columns)
    table = table.sort_values(sort_by, ascending=args.ascending, na_position="last", key=lambda s: s.astype(float))
    table, capped = policy.cap_rows(table, args.limit)

    columns, rows = output.table_rows(analysis.with_labels(table, ctx, keys))
    by = f" by {', '.join(keys)}" if keys else ""
    return output.ok(
        SKILL, spec, f"{', '.join(names)}{by}, {period.label}", columns, rows,
        [*analysis.period_notes(ctx, period, frame), *analysis.filter_note(filters), *capped,
         *policy.suppression_note(suppressed, spec)],
    )


if __name__ == "__main__":
    cli.run_skill(SKILL, build_parser(), run)
