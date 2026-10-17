---
name: tabular-analysis
description: Aggregate tables with pandas - filter, group, totals, averages, counts, rankings, top N, and time buckets (day/week/month). Use for "how much / how many / which is largest".
---
## Template
```python
import pandas as pd
df = pd.read_csv("data/<file>.csv", dtype={"<id_col>": str}, parse_dates=["<date_col>"])
rows = df[df["<valid_flag>"]]                         # keep only the rows the data dictionary says count
rows = rows[(rows["<date_col>"] >= "2020-01-01") & (rows["<date_col>"] < "2020-04-01")]   # inclusive start, exclusive end

g = rows.groupby("<dimension>").agg(
    amount=("<amount_col>", "sum"),
    orders=("<order_id_col>", "nunique"),
    units=("<qty_col>", "sum"),
)
g["avg_order_value"] = g["amount"] / g["orders"]      # ratio of sums, never a mean of per-row ratios
g["share"] = g["amount"] / g["amount"].sum()
print(g.sort_values("amount", ascending=False).head(10).round(2).to_string())
```

Time buckets: `rows["month"] = rows["<date_col>"].dt.to_period("M")`, then group by "month".

## Rules
- Ratios (averages per order, per customer, rates) = sum / sum over the group, never mean of row ratios.
- Distinct counts (orders, customers) use nunique, not count.
- Always print the scope (filters, date range, row count) next to the result.
- Print at most ~20 rows; sort and take the top N.
