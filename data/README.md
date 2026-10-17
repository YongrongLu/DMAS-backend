# Retail Rescue datasets

All department data is derived from the **UCI Online Retail II** open dataset
(<https://archive.ics.uci.edu/dataset/502/online+retail+ii>, CC BY 4.0 per the UCI page):
transactions of a UK-based online gift retailer that mostly sells to wholesalers,
2009-12-01 to 2011-12-09.

## Files

| Path | What it is |
|---|---|
| `raw/original_dataset.xlsx` | The original UCI workbook (two sheets) |
| `processed/cleaned_transactions.csv.gz` | All transactions, cleaned and flagged; 1,033,036 rows |
| `devices/<department>/shared/<department>_data.csv` | The view one department device is allowed to read |
| `devices/manifest.json` | Window, row counts, columns and sha256 of every view |

`processed/cleaned_transactions.csv.gz` is gzip-compressed because the CSV exceeds GitHub's 100 MB per-file limit.
SHA-256 of the decompressed CSV: `e613ad4dbce2a046f409168ea0fccee7becd3b8e3f2953c9458284d4ec00865d`.

```sh
gzip -dc data/processed/cleaned_transactions.csv.gz > data/processed/cleaned_transactions.csv
```

## Rebuilding the department views

```sh
./.venv/bin/python scripts/build_department_views.py
```

The build is deterministic: the same source gives byte-identical CSVs (check against `devices/manifest.json`).

## Window

The views cover **2009-12-01 to 2011-04-30**. The demo treats early May 2011 as "today": Feb–Apr 2011 is
the period under review and Feb–Apr 2010 the same period last year. Later months are left out on purpose,
because the open data rebounds from May 2011.

## Cleaning rules

- Non-merchandise lines are dropped from every view: postage (`POST`, `DOT`, `C2`, `C3`), manual adjustments
  (`M`, `m`, `ADJUST`, `ADJUST2`), discounts (`D`), samples (`S`), bad debt (`B`), bank and Amazon fees,
  gift vouchers (`gift_*`, `GIFT`), `PADS` and test products. Revenue therefore means merchandise revenue.
- `line_amount` = `quantity` × `unit_price`, rounded to 2 decimals.
- `is_cancellation`: the invoice starts with `C`. `is_return`: negative quantity (all cancellations, plus
  stock adjustments). `is_valid_sale`: neither, with a positive price and quantity.
- Each `stock_code` gets one description: its most frequent one in the source (the raw data spells
  1,200+ products several ways).

## Department views

Each view has exactly one dimension the other two do not have, so no single department can answer the
business question alone.

| View | Rows | Unique dimension | Columns |
|---|---|---|---|
| `sales_data.csv` | 663,024 | `country` | invoice_id, invoice_date, country, quantity, line_amount, flags |
| `customer_data.csv` | 512,616 | `customer_id` | invoice_id, invoice_date, customer_id, country, segment, quantity, line_amount, flags |
| `product_data.csv` | 663,024 | `stock_code` | invoice_id, invoice_date, stock_code, description, category, quantity, unit_price, line_amount, flags |

Derived columns:

- `segment` (customer): value tier **as of 2011-01-31**, from each customer's merchandise revenue in the
  12 months before it. `high_value` = top 10% of customers with positive revenue, `mid_value` = next 40%,
  `low_value` = the rest, `lapsed` = bought only before that window, `new` = first purchase after 2011-01-31.
- `category` (product): keyword heuristic on the description (first matching rule wins, see
  `CATEGORY_KEYWORDS` in the build script); about 6% of revenue stays `Other`.

## Known gaps

- About 23% of the lines (13% of merchandise revenue) are guest orders without a Customer ID. They appear in the sales and product
  views but not in the customer view, so customer revenue is lower than sales revenue.
- The shop does not trade from 2010-12-24 to 2011-01-03.
- The source has no cost data, so margins cannot be computed.

## Access rules for the demo

Each department device receives **only** its own `devices/<department>/shared/` directory. Never mount
`raw/`, `processed/`, another department's directory or any `private/` directory in an agent's authorized
data root. GitHub storage does not enforce this per-device policy, so copy the shared directory to each
device instead of relying on a clone of this repository.

`devices/finance/` is left over from the first data cut (sales / customer / finance, Nov–Dec 2010) and is not
used by the current three departments. Its `private/employee_salaries.csv` and `shared/approved_budget.json`
are synthetic fixtures.
