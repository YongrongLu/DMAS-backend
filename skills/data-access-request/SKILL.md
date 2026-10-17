---
name: data-access-request
description: The only way to handle a request for raw data (full tables, CSV exports, lists of individual records). Submits it to this device's data policy and returns the decision.
departments: [sales, customer, product]
---
## When to use
- Someone asks for the raw file, a full table, an export, or a list of individual customers or transactions.
- Never try to read or print the data file yourself; that is blocked and logged.

## Usage
python skills/data-access-request/scripts/request_export.py --scope "<what is requested>" [--reason "<why>"]

## Reading the result
- status "denied" with the message to pass on word for word, plus what this department can answer instead.
- Reply with that message, then offer one or two aggregate questions you can answer.
