---
name: change-analysis
description: Explain a change between two periods - year-over-year comparison, which groups drove it (contribution), volume vs rate split, groups that stopped or are new, and unusual periods.
---
## 1. Compare like with like
- Compare period B with the same period a year earlier (year-over-year). Month-on-month changes are
  mostly seasonal; do not present them as the trend.
- Count trading days (distinct dates) in each period; a shorter or partial period explains part of a change.

## 2. Total change and volume x rate split
If total = volume x rate (e.g. amount = orders x average order value):
```python
effect_volume = (vol_b - vol_a) * rate_a
effect_rate   = (rate_b - rate_a) * vol_b          # the two add up to total_b - total_a
```
This tells whether the change came from how many or from how much each.

## 3. Which groups drove it
```python
a = rows_a.groupby("<dim>")["<amount_col>"].sum(); b = rows_b.groupby("<dim>")["<amount_col>"].sum()
t = pd.concat({"a": a, "b": b}, axis=1).fillna(0)
t["delta"] = t.b - t.a
t["own_change"] = t.b / t.a - 1                     # the group vs itself
t["share_of_total_change"] = t.delta / t.delta.sum() # the group's part of the total change
t["status"] = "continuing"; t.loc[t.b == 0, "status"] = "stopped"; t.loc[t.a == 0, "status"] = "new"
print(t.sort_values("delta").head(10).round(3).to_string())
print(t.groupby("status")[["a", "b", "delta"]].sum())
```
- "X% of the decline" is share_of_total_change, not own_change.
- Stopped vs new groups: compare their VALUE (stopped value in A vs new value in B), not their counts.
  If new value offsets stopped value, the turnover itself is not the cause - look at continuing groups.

## Prices
- Compare prices only for items sold in both periods (continuing), per item: median or average unit price
  in A vs B. Report the share of items whose price went up / down / stayed the same, and the
  revenue-weighted average change.
- Never average per-item % changes without weights, and never compare an all-items average price across
  periods: both mostly reflect the mix of items sold, not price changes.

## 4. Unusual periods
Monthly or weekly series, change vs previous period, z-score of the changes; flag |z| >= 2, and check
whether a flagged period is just short (holiday, partial month) before reporting it.

## 5. Conclude
Rank causes by their net effect in money or units; say which candidate causes were checked and ruled out.
