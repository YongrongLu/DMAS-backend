---
name: time-trend
description: A metric over time (day/week/month) with change vs the previous period and, monthly, vs the same month last year. Use for "when did it start", "is it getting worse", "which months changed most".
departments: [sales, customer, product]
---
## When to use
- See how a metric moves over time, or whether a decline is accelerating.
- Compare a few groups over time (e.g. categories or segments side by side).

## Usage
python skills/time-trend/scripts/trend.py --metric <metric> [--freq month|week|day]
    [--start YYYY-MM] [--end YYYY-MM] [--filter "<dim>=<value>"]...
python skills/time-trend/scripts/trend.py --metric <metric> --freq month --group-by <dim> [--top-groups 5] ...

## Reading the result
- Single series: one row per period with change_vs_previous, change_vs_last_year (monthly only)
  and trading_days. Few trading days means a partial period or a closure - say so before concluding.
- Grouped: one row per period, one column per group (the largest groups); values only.
  For year-over-year change by group use period-comparison.
- At most 25 periods are shown; narrow the range or use a coarser --freq.
