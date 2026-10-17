---
name: aggregate-query
description: Totals and rankings - filter, group by up to 2 dimensions, sum/count/average, sort and take the top N. Use for "which X is largest / highest", e.g. top markets, highest return rates.
departments: [sales, customer, product]
---
## When to use
- Rank groups by a metric, or get totals for one period.
- For change between two periods use period-comparison instead.

## Usage
python skills/aggregate-query/scripts/aggregate.py --metrics <m1>[,<m2>] [--group-by <dim>[,<dim2>]]
    [--start YYYY-MM] [--end YYYY-MM] [--filter "<dim>=<value>"]... [--sort-by <metric>] [--ascending] [--limit 10]

## Arguments
- metrics and dimensions: names from the data card in your instructions; month / week / date can also be grouped by.
- --filter is repeatable: "<dim>=<v>", "<dim>!=<v>", "<dim> in <v1>,<v2>".
- --start / --end are inclusive; a bare month means the whole month.

## Reading the result
- One row per group; share_of_<metric> is the group's share of the total.
- notes list the period, trading days, filters, and any groups suppressed for privacy.
