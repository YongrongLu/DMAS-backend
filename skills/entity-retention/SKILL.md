---
name: entity-retention
description: Retention between two periods for any entity (customers, suppliers, accounts) - retained, churned and new, their value, purchase frequency, and whether churn or existing entities explain a change.
---
## Template
```python
a = rows_a; b = rows_b                                 # filtered to valid rows of each period
ids_a, ids_b = set(a["<entity_col>"].dropna()), set(b["<entity_col>"].dropna())
retained, churned, new = ids_a & ids_b, ids_a - ids_b, ids_b - ids_a
val = lambda df, ids: df[df["<entity_col>"].isin(ids)]["<amount_col>"].sum()
print("active", len(ids_a), "->", len(ids_b), "| retained", len(retained), "churned", len(churned), "new", len(new))
print("retained value", val(a, retained), "->", val(b, retained))
print("churned value (A)", val(a, churned), "| new value (B)", val(b, new))
freq = lambda df: df["<order_id_col>"].nunique() / df["<entity_col>"].nunique()
print("orders per active entity", round(freq(a), 2), "->", round(freq(b), 2))
```
Repeat per segment / market with groupby when asked "which group changed most".

## Reading it
- Revenue bridge: total change = retained change - churned value + new value.
- Churn is a driver only if it is NOT offset by new entities: compare (new value - churned value) with the
  retained change.
- Fewer orders per active entity = existing entities buying less often.

## Privacy
Report counts and sums only; never list entity ids; omit groups with fewer than 5 entities.
