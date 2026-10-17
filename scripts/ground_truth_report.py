"""Ground-truth numbers of the demo story, computed from the department views only

Each section reads nothing but its own device's CSV, the same data that
department agent can see, so it proves the department can find its piece of
the story on its own. Use the numbers to check agent answers; never put them
into a prompt (PRD §7: findings must come from the analysis, not be hardcoded).

Usage:
    ./.venv/bin/python scripts/ground_truth_report.py
    ./.venv/bin/python scripts/ground_truth_report.py --period-a 2010-02-01:2010-04-30 --period-b 2011-02-01:2011-04-30

Key constraints:
- periods are inclusive day ranges; A is the baseline, B the period under review
- revenue counts valid sales only; returns are reported separately
"""

import argparse
import os

import pandas as pd


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEVICES_DIR = os.path.join(PROJECT_ROOT, "data", "devices")

DEFAULT_PERIOD_A = "2010-02-01:2010-04-30"
DEFAULT_PERIOD_B = "2011-02-01:2011-04-30"
TOP_SKUS_LAST_YEAR = 200


def _load(department: str) -> pd.DataFrame:
    """Load one department view with its ids kept as strings."""
    path = os.path.join(DEVICES_DIR, department, "shared", f"{department}_data.csv")
    df = pd.read_csv(path, dtype={"invoice_id": str, "customer_id": str, "stock_code": str})
    df["invoice_date"] = pd.to_datetime(df["invoice_date"])
    return df


def _window(df: pd.DataFrame, period: tuple[pd.Timestamp, pd.Timestamp]) -> pd.DataFrame:
    """Rows inside an inclusive day range."""
    start, end = period
    return df[(df["invoice_date"] >= start) & (df["invoice_date"] < end + pd.Timedelta(days=1))]


def _pct(before: float, after: float) -> str:
    """Format a relative change."""
    return f"{after / before - 1:+.1%}" if before else "n/a"


def sales_section(a, b) -> None:
    """What happened to revenue, orders, AOV and markets."""
    df = _load("sales")
    valid = df[df["is_valid_sale"]]
    A, B = _window(valid, a), _window(valid, b)

    rev_a, rev_b = A["line_amount"].sum(), B["line_amount"].sum()
    ord_a, ord_b = A["invoice_id"].nunique(), B["invoice_id"].nunique()
    days_a, days_b = A["invoice_date"].dt.date.nunique(), B["invoice_date"].dt.date.nunique()
    print("== Sales")
    print(f"revenue {rev_a:,.0f} -> {rev_b:,.0f} ({_pct(rev_a, rev_b)}), trading days {days_a} -> {days_b}")
    print(f"orders {ord_a} -> {ord_b} ({_pct(ord_a, ord_b)}), "
          f"AOV {rev_a / ord_a:,.0f} -> {rev_b / ord_b:,.0f} ({_pct(rev_a / ord_a, rev_b / ord_b)})")

    monthly = valid.groupby(valid["invoice_date"].dt.to_period("M"))["line_amount"].sum()
    for month in pd.period_range(b[0], b[1], freq="M"):
        last_year = month - 12
        print(f"  {month}: {monthly.get(month, 0):,.0f} vs {last_year}: {monthly.get(last_year, 0):,.0f} "
              f"({_pct(monthly.get(last_year, 0), monthly.get(month, 0))})")

    by_country = pd.concat([A.groupby("country")["line_amount"].sum().rename("A"),
                            B.groupby("country")["line_amount"].sum().rename("B")], axis=1).fillna(0)
    uk = by_country.loc["United Kingdom"]
    rest = by_country.drop("United Kingdom").sum()
    print(f"UK {_pct(uk['A'], uk['B'])} (share of revenue in A {uk['A'] / rev_a:.0%}, "
          f"share of the decline {(uk['B'] - uk['A']) / (rev_b - rev_a):.0%}), rest of world {_pct(rest['A'], rest['B'])}")
    by_country["delta"] = by_country["B"] - by_country["A"]
    worst = by_country[by_country["A"] > 5000].assign(pct=lambda x: x["B"] / x["A"] - 1).sort_values("pct").head(3)
    print("largest relative drops (markets > 5k in A): "
          + ", ".join(f"{c} {r.pct:+.0%}" for c, r in worst.iterrows()))


def customer_section(a, b) -> None:
    """Whether the decline comes from churn or from customers buying less."""
    df = _load("customer")
    valid = df[df["is_valid_sale"]]
    A, B = _window(valid, a), _window(valid, b)

    ids_a, ids_b = set(A["customer_id"]), set(B["customer_id"])
    retained, churned, new = ids_a & ids_b, ids_a - ids_b, ids_b - ids_a
    rev_a = A.groupby("customer_id")["line_amount"].sum()
    rev_b = B.groupby("customer_id")["line_amount"].sum()
    ord_a = A.groupby("customer_id")["invoice_id"].nunique()
    ord_b = B.groupby("customer_id")["invoice_id"].nunique()

    print("== Customer")
    print(f"active customers {len(ids_a)} -> {len(ids_b)} ({_pct(len(ids_a), len(ids_b))}), "
          f"known-customer revenue {rev_a.sum():,.0f} -> {rev_b.sum():,.0f} ({_pct(rev_a.sum(), rev_b.sum())})")
    keep = sorted(retained)
    print(f"retained {len(retained)}: orders {ord_a[keep].sum()} -> {ord_b[keep].sum()} "
          f"({_pct(ord_a[keep].sum(), ord_b[keep].sum())}), revenue {rev_a[keep].sum():,.0f} -> {rev_b[keep].sum():,.0f} "
          f"({_pct(rev_a[keep].sum(), rev_b[keep].sum())})")
    print(f"churned {len(churned)} (revenue in A {rev_a[sorted(churned)].sum():,.0f}), "
          f"new {len(new)} (revenue in B {rev_b[sorted(new)].sum():,.0f})")

    segment = df.drop_duplicates("customer_id").set_index("customer_id")["segment"]
    for tier in ("high_value", "mid_value", "low_value"):
        members = segment[segment == tier].index
        in_a = A[A["customer_id"].isin(members)]
        in_b = B[B["customer_id"].isin(members)]
        print(f"  {tier:<10} ({len(members)}): active {in_a['customer_id'].nunique()} -> {in_b['customer_id'].nunique()}, "
              f"orders {in_a['invoice_id'].nunique()} -> {in_b['invoice_id'].nunique()} "
              f"({_pct(in_a['invoice_id'].nunique(), in_b['invoice_id'].nunique())}), "
              f"revenue {in_a['line_amount'].sum():,.0f} -> {in_b['line_amount'].sum():,.0f} "
              f"({_pct(in_a['line_amount'].sum(), in_b['line_amount'].sum())})")


def product_section(a, b) -> None:
    """Which products and categories drive the decline, and whether returns explain it."""
    df = _load("product")
    valid = df[df["is_valid_sale"]]
    A, B = _window(valid, a), _window(valid, b)
    total_delta = B["line_amount"].sum() - A["line_amount"].sum()

    print("== Product")
    by_cat = pd.concat([A.groupby("category")["line_amount"].sum().rename("A"),
                        B.groupby("category")["line_amount"].sum().rename("B")], axis=1).fillna(0)
    by_cat["delta"] = by_cat["B"] - by_cat["A"]
    for category, row in by_cat.sort_values("delta").head(4).iterrows():
        print(f"  {category:<24} {row['A']:,.0f} -> {row['B']:,.0f} ({_pct(row['A'], row['B'])}), "
              f"share of the decline {row['delta'] / total_delta:.0%}")

    sku_a = A.groupby("stock_code")["line_amount"].sum()
    sku_b = B.groupby("stock_code")["line_amount"].sum()
    top_last_year = sku_a.sort_values(ascending=False).head(TOP_SKUS_LAST_YEAR)
    gone = top_last_year[~top_last_year.index.isin(sku_b.index)]
    names = df.drop_duplicates("stock_code").set_index("stock_code")["description"]
    print(f"top-{TOP_SKUS_LAST_YEAR} SKUs of A with zero sales in B: {len(gone)}, their revenue in A "
          f"{gone.sum():,.0f} = {-gone.sum() / total_delta:.0%} of the decline")
    print("  e.g. " + "; ".join(names[code] for code in gone.head(5).index))

    delta = sku_b.reindex(sku_a.index.union(sku_b.index)).fillna(0) - sku_a.reindex(sku_a.index.union(sku_b.index)).fillna(0)
    drops = delta[delta < 0].sort_values()
    print(f"concentration: top 10 falling SKUs = {drops.head(10).sum() / drops.sum():.0%}, "
          f"top 50 = {drops.head(50).sum() / drops.sum():.0%} of the gross SKU decline")

    def return_rate(period):
        rows = _window(df, period)
        sold = rows[rows["is_valid_sale"]]["quantity"].sum()
        returned = -rows[rows["is_return"]]["quantity"].sum()
        return returned / sold

    print(f"return rate (units) {return_rate(a):.1%} -> {return_rate(b):.1%}")


def _parse_period(text: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Parse 'YYYY-MM-DD:YYYY-MM-DD' into an inclusive day range."""
    start, end = text.split(":")
    return pd.Timestamp(start), pd.Timestamp(end)


def main() -> None:
    """Print the three sections."""
    parser = argparse.ArgumentParser(description="Print the demo's ground-truth numbers.")
    parser.add_argument("--period-a", default=DEFAULT_PERIOD_A, help="baseline period (default: %(default)s)")
    parser.add_argument("--period-b", default=DEFAULT_PERIOD_B, help="period under review (default: %(default)s)")
    args = parser.parse_args()
    a, b = _parse_period(args.period_a), _parse_period(args.period_b)

    print(f"A = {args.period_a}   B = {args.period_b}\n")
    sales_section(a, b)
    print()
    customer_section(a, b)
    print()
    product_section(a, b)


if __name__ == "__main__":
    main()
