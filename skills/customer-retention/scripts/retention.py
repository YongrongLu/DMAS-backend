"""customer-retention: retained, churned and new customers between two periods

Customer ids are only used inside this script to build the sets; the result
holds counts and sums, and groups with too few customers are suppressed.

Usage:
    python skills/customer-retention/scripts/retention.py --period-a 2010-02:2010-04 --period-b 2011-02:2011-04 \
        --group-by segment
"""

import pandas as pd

from core.data import analysis, cli, output, periods, policy
from core.data.errors import SkillError

SKILL = "customer-retention"
TOTAL = "ALL"
COLUMNS = [
    "active_a", "active_b", "retained", "churned", "new", "retention_rate",
    "revenue_a", "revenue_b", "retained_revenue_a", "retained_revenue_b",
    "orders_per_active_a", "orders_per_active_b",
]


def build_parser():
    """Arguments of this skill."""
    parser = cli.build_parser(SKILL, "Retention between two periods.")
    cli.add_periods(parser)
    cli.add_group_by(parser)
    cli.add_filters(parser)
    cli.add_limit(parser)
    return parser


def _stats(a: pd.DataFrame, b: pd.DataFrame, entity: str) -> dict:
    """Retention numbers of one group; a and b hold valid sales only."""
    ids_a, ids_b = set(a[entity]), set(b[entity])
    retained = ids_a & ids_b
    keep_a, keep_b = a[a[entity].isin(retained)], b[b[entity].isin(retained)]
    return {
        "active_a": len(ids_a),
        "active_b": len(ids_b),
        "retained": len(retained),
        "churned": len(ids_a - ids_b),
        "new": len(ids_b - ids_a),
        "retention_rate": output.share(len(retained), len(ids_a)),
        "revenue_a": a["line_amount"].sum(),
        "revenue_b": b["line_amount"].sum(),
        "retained_revenue_a": keep_a["line_amount"].sum(),
        "retained_revenue_b": keep_b["line_amount"].sum(),
        "orders_per_active_a": a["invoice_id"].nunique() / len(ids_a) if ids_a else None,
        "orders_per_active_b": b["invoice_id"].nunique() / len(ids_b) if ids_b else None,
        "_entities": len(ids_a | ids_b),
    }


def _revenue_bridge(total: dict) -> str:
    """Split the revenue change into retained customers, churned customers and new customers."""
    retained = total["retained_revenue_b"] - total["retained_revenue_a"]
    churned = total["revenue_a"] - total["retained_revenue_a"]
    new = total["revenue_b"] - total["retained_revenue_b"]
    change = total["revenue_b"] - total["revenue_a"]
    return (f"revenue bridge A -> B: total {output.clean(change)} = retained customers {output.clean(retained)} "
            f"+ churned customers -{output.clean(churned)} + new customers +{output.clean(new)}; churn and new "
            f"customers net to {output.clean(new - churned)}, so compare that net with the retained change before "
            f"calling churn a driver")


def run(ctx: cli.Context, args) -> dict:
    """Retention overall and per group."""
    spec = ctx.spec
    entity = spec.entity_column
    if entity is None:
        raise SkillError(f"customer-retention needs customer identities, which the {spec.name} view does not have")
    keys = analysis.parse_group_by(ctx, args.group_by, 1, allow_time=False)

    filters = cli.parse_filters(ctx, args.filter)
    period_a, period_b = periods.parse_period(args.period_a), periods.parse_period(args.period_b)
    frame = analysis.scoped(ctx, filters)
    valid = frame[frame["is_valid_sale"]]
    a = periods.in_period(valid, spec.date_column, period_a)
    b = periods.in_period(valid, spec.date_column, period_b)

    records = [{"group": TOTAL, **_stats(a, b, entity)}]
    bridge = _revenue_bridge(records[0])
    if keys:
        key = keys[0]
        groups = sorted(set(a[key]) | set(b[key]), key=lambda g: -a.loc[a[key] == g, "line_amount"].sum())
        records += [{"group": g, **_stats(a[a[key] == g], b[b[key] == g], entity)} for g in groups]

    table = pd.DataFrame(records).set_index("group")
    counts = table.pop("_entities")
    table, suppressed = policy.suppress_small_groups(table, counts, spec, COLUMNS)
    table, capped = policy.cap_rows(table, args.limit + 1)
    table.index.name = keys[0] if keys else "group"
    columns, rows = output.table_rows(table)

    notes = [
        *analysis.period_notes(ctx, period_a, frame, "period A"),
        *analysis.period_notes(ctx, period_b, frame, "period B"),
        *analysis.filter_note(filters),
        "retained = bought in both periods; churned = bought in A only; new = bought in B only (new to this "
        "comparison, not necessarily first-time buyers)",
        "orders_per_active = orders / active customers in that period (purchase frequency)",
        bridge,
        "guest orders without a customer id are not included",
        *capped, *policy.suppression_note(suppressed, spec),
    ]
    by = f" by {keys[0]}" if keys else ""
    return output.ok(SKILL, spec, f"customer retention{by}: B {period_b.label} vs A {period_a.label}", columns, rows, notes)


if __name__ == "__main__":
    cli.run_skill(SKILL, build_parser(), run)
