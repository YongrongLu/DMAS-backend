---
name: dataset-profile
description: What your data contains - dimensions, metrics, date range, closures - or the valid values of one dimension. Use it first when unsure, or to find exact filter values.
departments: [sales, customer, product]
---
## When to use
- You are unsure which dimension or metric to use.
- You need the exact spelling of a value before filtering (e.g. a category or segment name).

## Usage
python skills/dataset-profile/scripts/profile.py
python skills/dataset-profile/scripts/profile.py --values <dimension> [--limit 25]

## Reading the result
- Without --values: one row per dimension, time key and metric, with a short definition.
  notes give the date range, trading closures and the restricted columns.
- With --values: the values of that dimension ranked by revenue, with their share.
- Raw rows are never returned.
