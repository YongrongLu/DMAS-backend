---
name: other-formats
description: Read data that is not a plain CSV - Excel, JSON, SQLite databases, Parquet, and documents (PDF, DOCX, TXT, Markdown).
---
## Excel
`pd.read_excel("data/x.xlsx", sheet_name=None)` returns every sheet as a dict; print sheet names and shapes first.

## JSON
```python
import json, pandas as pd
obj = json.load(open("data/x.json"))
print(type(obj), list(obj)[:20] if isinstance(obj, dict) else len(obj))
df = pd.json_normalize(obj if isinstance(obj, list) else obj.get("<records_key>", []))
```
Small JSON files (config, budgets, targets) can simply be read with view_file.

## SQLite
```bash
python -c "import sqlite3; c=sqlite3.connect('data/x.db'); print(c.execute(\"select name from sqlite_master where type='table'\").fetchall())"
```
Then aggregate in SQL (`select ..., sum(...) group by ...`) instead of loading whole tables.

## Parquet
`pd.read_parquet("data/x.parquet", columns=[...])`.

## Documents
- TXT / Markdown: view_file, grep_tool for keywords.
- PDF: `python -c "import pypdf"`; if available, extract text page by page and search it; if the library is
  missing, say so in your answer instead of guessing the content.
- DOCX: `python -c "import docx"` (python-docx), same rule.
Quote only short passages; summarise the rest.
