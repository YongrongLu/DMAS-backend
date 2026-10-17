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
        act_a, act_b = in_a["customer_id"].nunique(), in_b["customer_id"].nunique()
        o_a, o_b = in_a["invoice_id"].nunique(), in_b["invoice_id"].nunique()
        print(f"  {tier:<10} ({len(members)}): active {act_a} -> {act_b}, orders {o_a} -> {o_b} ({_pct(o_a, o_b)}), "
              f"orders per active customer {o_a / act_a:.2f} -> {o_b / act_b:.2f}, "
              f"revenue {in_a['line_amount'].sum():,.0f} -> {in_b['line_amount'].sum():,.0f} "
              f"({_pct(in_a['line_amount'].sum(), in_b['line_amount'].sum())})")

    # 第二轮追问的答案：高价值客户的放缓是不是英国特有、是不是逐月恶化
    high = segment[segment == "high_value"].index
    hv_a, hv_b = A[A["customer_id"].isin(high)], B[B["customer_id"].isin(high)]
    for label, is_uk in (("UK", True), ("non-UK", False)):
        o_a = hv_a[(hv_a["country"] == "United Kingdom") == is_uk]["invoice_id"].nunique()
        o_b = hv_b[(hv_b["country"] == "United Kingdom") == is_uk]["invoice_id"].nunique()
        print(f"  high_value {label}: orders {o_a} -> {o_b} ({_pct(o_a, o_b)})")
    by_month = [
        _pct(hv_a[hv_a["invoice_date"].dt.month == m]["invoice_id"].nunique(),
             hv_b[hv_b["invoice_date"].dt.month == m]["invoice_id"].nunique())
        for m in sorted(hv_b["invoice_date"].dt.month.unique())
    ]
    print(f"  high_value orders by month: {', '.join(by_month)}")


def product_section(a, b) -> None:
    """Whether range, price or volume drives the decline, which categories, and returns."""
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

    # 商品组合：停卖的（只在 A 有）、新上的（只在 B 有）、两年都在卖的
    sku_a = A.groupby("stock_code")["line_amount"].sum()
    sku_b = B.groupby("stock_code")["line_amount"].sum()
    stopped = sku_a[~sku_a.index.isin(sku_b.index)]
    new = sku_b[~sku_b.index.isin(sku_a.index)]
    continuing = sku_a.index.intersection(sku_b.index)
    print(f"range: stopped {len(stopped)} SKUs (A {stopped.sum():,.0f}), new {len(new)} SKUs (B {new.sum():,.0f}), "
          f"net {new.sum() - stopped.sum():+,.0f}")
    print(f"continuing {len(continuing)} SKUs: revenue {sku_a[continuing].sum():,.0f} -> {sku_b[continuing].sum():,.0f} "
          f"({_pct(sku_a[continuing].sum(), sku_b[continuing].sum())})")

    cont_a, cont_b = A[A["stock_code"].isin(continuing)], B[B["stock_code"].isin(continuing)]
    print(f"  units {cont_a['quantity'].sum():,} -> {cont_b['quantity'].sum():,} "
          f"({_pct(cont_a['quantity'].sum(), cont_b['quantity'].sum())}), "
          f"units per order line {cont_a['quantity'].mean():.1f} -> {cont_b['quantity'].mean():.1f}")
    price_a = cont_a.groupby("stock_code")["unit_price"].median()
    price_b = cont_b.groupby("stock_code")["unit_price"].median()
    change = price_b / price_a - 1
    same = change.abs() <= 0.001
    print(f"  median unit price per SKU: unchanged {same.mean():.0%}, higher {(change > 0.001).mean():.0%}, "
          f"lower {(change < -0.001).mean():.0%}; unchanged-price SKUs units "
          f"{_pct(cont_a[cont_a['stock_code'].isin(change[same].index)]['quantity'].sum(), cont_b[cont_b['stock_code'].isin(change[same].index)]['quantity'].sum())}")

    category = df.drop_duplicates("stock_code").set_index("stock_code")["category"]
    net_by_cat = (new.groupby(category.reindex(new.index)).sum()
                  .sub(stopped.groupby(category.reindex(stopped.index)).sum(), fill_value=0).sort_values())
    print("net range change by category (new - stopped): "
          + ", ".join(f"{c} {v:+,.0f}" for c, v in net_by_cat.head(3).items()))
    names = df.drop_duplicates("stock_code").set_index("stock_code")["description"]
    lighting_stopped = stopped[category.reindex(stopped.index) == "Lighting & Candles"].sort_values(ascending=False)
    print("  largest stopped lighting lines: " + "; ".join(names[c] for c in lighting_stopped.head(4).index))

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
