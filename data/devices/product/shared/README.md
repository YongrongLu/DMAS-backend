# Product data

`product_data.csv` - one row per order line.

| Column | Meaning |
|---|---|
| invoice_id | order number; starts with C for a cancellation |
| invoice_date | order timestamp, YYYY-MM-DD HH:MM:SS |
| stock_code | product (SKU) |
| description | product name |
| category | product category (keyword-based) |
| quantity | units on the line; negative on returns |
| unit_price | price per unit, GBP |
| line_amount | quantity x unit price, GBP |
| is_cancellation / is_return / is_valid_sale | row flags; use is_valid_sale rows for sales, is_return rows for returns |
