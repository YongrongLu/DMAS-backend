---
name: explore-data
description: First step on any question - find out what data you have, its format, columns, size and coverage, before analysing it.
---
## Steps
1. List everything: glob_tool pattern='**/*' path='data'.
2. Read any README, data dictionary or schema file (view_file).
3. For each file you may need, check its shape with a short script - never print the whole file:

```python
import pandas as pd
df = pd.read_csv("data/<file>.csv")          # read_excel / read_parquet / read_json for other formats
print(df.shape)
print(df.dtypes)
print(df.head(5).to_string())                # a few rows only, to see the format
print(df.describe(include="all").T.head(30).to_string())
```

4. Note for later: the date column and its range, identifier columns, flag/status columns,
   amount and quantity columns, and the grain (one row = what?).
5. Check date coverage: first and last date, and gaps (e.g. holidays) that would make a period partial.

## Pitfalls
- Read ids as strings (dtype={"<id_col>": str}) so leading zeros and codes survive.
- Large files: load only the columns you need (usecols=[...]).
- Not tabular? Load the other-formats skill.
