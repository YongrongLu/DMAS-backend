# Customer data

`customer_data.csv` - one row per order line of an identified customer (guest orders are not included).

| Column | Meaning |
|---|---|
| invoice_id | order number; starts with C for a cancellation |
| invoice_date | order timestamp, YYYY-MM-DD HH:MM:SS |
| customer_id | customer identifier (personal data: never report it) |
| country | country of the customer |
| segment | value tier as of 2011-01-31: high_value, mid_value, low_value, lapsed, new |
| quantity | units on the line; negative on returns |
| line_amount | quantity x unit price, GBP |
| is_cancellation / is_return / is_valid_sale | row flags; use is_valid_sale rows for sales figures |

An order is a distinct `invoice_id`; an active customer is a distinct `customer_id` with a valid sale.
