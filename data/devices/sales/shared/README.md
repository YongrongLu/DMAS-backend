# Sales data

`sales_data.csv` - one row per order line.

| Column | Meaning |
|---|---|
| invoice_id | order number; starts with C for a cancellation |
| invoice_date | order timestamp, YYYY-MM-DD HH:MM:SS |
| country | market of the order |
| quantity | units on the line; negative on returns |
| line_amount | quantity x unit price, GBP |
| is_cancellation | the order was cancelled |
| is_return | negative quantity (returns and stock adjustments) |
| is_valid_sale | a real sale: not cancelled, not a return, positive price and quantity |

Use `is_valid_sale` rows for sales figures. An order is a distinct `invoice_id`.
