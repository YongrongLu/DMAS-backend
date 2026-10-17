---
name: anomaly-detection
description: Finds weeks or months whose change vs the previous period is unusually large (z-score), for the total or the largest groups. Use for "are there abnormal drops or spikes".
departments: [sales, customer, product]
---
## When to use
- Look for sudden drops or spikes rather than a slow trend.
- Check whether one market, segment or category had an abnormal period.

## Usage
python skills/anomaly-detection/scripts/anomalies.py --metric <metric> [--freq week|month]
    [--start YYYY-MM] [--end YYYY-MM] [--group-by <dim>] [--top-groups 5] [--threshold 2.0]
    [--filter "<dim>=<value>"]... [--limit 10]

## Reading the result
- One row per unusual period: value, previous, change, z_score, direction (drop / spike).
- A note "overlaps a trading closure" or "only N trading days" means the period was cut short
  (e.g. holidays) - not a real business change. Check it before reporting the anomaly.
- Use a range of at least 6 periods; shorter series are not scored.
