---
name: period-comparison
description: One metric in period A vs period B - in total with a volume x rate split, or per group with each group's contribution and whether it stopped, is new or continued. Use for "what changed and who drove it".
departments: [sales, customer, product]
---
## When to use
- How much did a metric change between two periods, and was it volume or rate (e.g. orders vs AOV)?
- Which groups (markets, segments, categories, SKUs) drove the change?
- Did groups disappear or appear (e.g. products stopped / new lines)? Did prices change per SKU?

## Usage
python skills/period-comparison/scripts/compare.py --metric <metric> --period-a <START:END> --period-b <START:END>
    [--group-by <dim>] [--status all|stopped|new|continuing] [--sort decline|growth|abs]
    [--only-continuing <dim>] [--filter "<dim>=<value>"]... [--limit 10]
Periods: 2010-02:2010-04 means 1 Feb to 30 Apr 2010. A is the baseline, B the period under review.

## Reading the result
- Total: rows for the metric and, when it has one, its volume and rate parts plus "effect of ..."
  rows whose deltas add up to the total change.
- By group: period_a, period_b, delta, pct_change, share_of_change, cum_share and status.
  notes summarise how many groups stopped / are new / continued and their net effect - check these
  before blaming a change in the range. For per-SKU metrics like median_price, notes give the share
  of continuing groups that went up, down or stayed unchanged.
- --only-continuing stock_code compares only products sold in both periods.
