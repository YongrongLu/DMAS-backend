"""dataset-profile: what the department view contains, without returning raw rows

Usage:
    python skills/dataset-profile/scripts/profile.py
    python skills/dataset-profile/scripts/profile.py --values country --limit 15
"""

from core.data import analysis, cli, metrics, output, periods, policy
from core.data.constants import MAX_RESULT_ROWS
from core.departments.base import TIME_DIMENSIONS

SKILL = "dataset-profile"


def build_parser():
    """Arguments of this skill."""
    parser = cli.build_parser(SKILL, "Profile the department view.")
    parser.add_argument("--values", default="", help="list the values of one dimension")
    cli.add_limit(parser, default=MAX_RESULT_ROWS)
    return parser


def _metric_definition(metric) -> str:
    """How a metric is computed, in a few words."""
    rows = "return lines" if metric.rows == "returns" else "valid sales"
    if metric.kind == "ratio":
        return f"{metric.numerator} / {metric.denominator}"
    if metric.kind == "count":
        return f"count of {rows} lines"
    return f"{metric.kind} of {metric.column} on {rows}"


def _list_values(ctx: cli.Context, dimension: str, limit: int) -> dict:
    """The values of one dimension with their size, largest first."""
    spec = ctx.spec
    policy.check_columns(spec, [dimension], purpose="list values of", allowed=spec.dimensions)
    size_metric = "revenue" if "revenue" in spec.metrics else next(iter(spec.metrics))
    table = metrics.compute(ctx.df, spec, [size_metric], [dimension])
    total = table[size_metric].sum()
    table["share"] = [output.share(v, total) for v in table[size_metric]]
    table = table.sort_values(size_metric, ascending=False)
    table, suppressed = policy.suppress_small_groups(
        table, policy.entity_counts(ctx.df, spec, [dimension]), spec, [size_metric, "share"])
    table, capped = policy.cap_rows(table, limit)
    columns, rows = output.table_rows(analysis.with_labels(table, ctx, [dimension]))
    return output.ok(SKILL, spec, f"values of {dimension} by {size_metric}", columns, rows,
                     [f"{ctx.df[dimension].nunique()} distinct values", *capped,
                      *policy.suppression_note(suppressed, spec)])


def run(ctx: cli.Context, args) -> dict:
    """Describe the view, or list the values of one dimension."""
    if args.values:
        return _list_values(ctx, args.values, args.limit)

    spec, df = ctx.spec, ctx.df
    rows = []
    for name, description in spec.dimensions.items():
        top = df[name].value_counts().head(3).index.tolist()
        rows.append([name, "dimension", description, f"{df[name].nunique()} values, e.g. {', '.join(map(str, top))}"])
    for name, description in TIME_DIMENSIONS.items():
        rows.append([name, "time", description, "derived from the order timestamp"])
    for name, metric in spec.metrics.items():
        rows.append([name, "metric", metric.description, _metric_definition(metric)])

    first, last = ctx.dates.min(), ctx.dates.max()
    notes = [
        f"data covers {first:%Y-%m-%d}..{last:%Y-%m-%d}, {periods.trading_days(df, spec.date_column)} trading days",
        f"{int(df['is_valid_sale'].sum())} valid sale lines, {int(df['is_return'].sum())} return lines, "
        f"{int(df['is_cancellation'].sum())} cancellation lines",
        *periods.coverage_notes(ctx.dates, periods.Period(first.normalize(), last.normalize()), "the data"),
        "restricted (never leave this device): "
        + ", ".join(f"{c} ({why})" for c, why in spec.restricted_columns.items()),
    ]
    if spec.entity_column:
        notes.append(f"groups with fewer than {spec.k_anon_min} {spec.entity_column} values are suppressed")
    return output.ok(SKILL, spec, f"profile of {spec.csv_name}", ["name", "kind", "description", "detail"], rows, notes)


if __name__ == "__main__":
    cli.run_skill(SKILL, build_parser(), run)
