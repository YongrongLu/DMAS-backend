---
name: customer-retention
description: Retained, churned and new customers between two periods, their revenue, and orders per active customer, overall and by segment or country. Use for "are we losing customers or are they buying less".
departments: [customer]
---
## When to use
- Separate churn (customers leaving) from existing customers buying less.
- Check how often each segment orders (purchase frequency), or whether a market lost customers.

## Usage
python skills/customer-retention/scripts/retention.py --period-a <START:END> --period-b <START:END>
    [--group-by segment|country] [--filter "<dim>=<value>"]... [--limit 10]

## Reading the result
- First row ALL, then one row per group (largest in period A first).
- retained / churned / new are customer counts; retained_revenue_a -> _b shows whether the customers
  who stayed are spending less; orders_per_active_a -> _b is purchase frequency.
- notes include a revenue bridge: retained customers' change vs churned vs new customers. Churn is only a
  driver if it is not offset by new customers - always check the net before blaming churn.
- Groups with fewer than 5 customers are suppressed. Guest orders are not included.
- Never list individual customers; this skill only returns counts and sums.
