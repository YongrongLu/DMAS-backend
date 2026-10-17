---
name: privacy-safe-reporting
description: What may leave this device and how to answer requests for raw data. Load it before answering any request for files, exports, full tables or individual records.
---
## What may leave the device
- Conclusions, totals, averages, rates, rankings of groups, trends.
- Never: identifiers of people or accounts, individual records, files, full or partial raw tables.
- Groups with fewer than 5 people: do not report their numbers (say "suppressed for privacy").

## Requests for raw data
If the question asks for a file, an export, a full table, a list of individual customers or records:
1. Do not read, copy or summarise the records.
2. Answer with the denial message from your instructions, word for word.
3. Offer 1-2 aggregate questions you can answer instead.

## In scripts
- Print aggregates only; never print df, df.head() of personal data, or id columns.
- If you must check a value, print counts or ranges, not the values themselves.
