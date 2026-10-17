"""Product department: categories, SKUs, prices and returns"""

from core.departments.base import LINES, ORDERS, REVENUE, UNITS, DepartmentSpec, Metric


PRODUCT = DepartmentSpec(
    name="product",
    display_name="Product Department",
    csv_name="product_data.csv",
    dimensions={
        "stock_code": "product (SKU); results also show its description",
        "category": "product category (keyword-based)",
    },
    metrics={
        "revenue": REVENUE,
        "units": UNITS,
        "orders": ORDERS,
        "lines": LINES,
        "returned_units": Metric("returned_units", "sum", column="quantity", rows="returns", negate=True,
                                 description="units on return lines"),
        "return_rate": Metric("return_rate", "ratio", numerator="returned_units", denominator="units",
                              description="returned units / units sold"),
        "avg_price": Metric("avg_price", "ratio", numerator="revenue", denominator="units",
                            description="revenue / units; moves with the product mix"),
        "median_price": Metric("median_price", "median", column="unit_price",
                               description="median unit price of the lines; use per SKU to check price changes"),
        "units_per_line": Metric("units_per_line", "ratio", numerator="units", denominator="lines",
                                 description="units per order line = units / lines"),
        "active_skus": Metric("active_skus", "nunique", column="stock_code",
                              description="distinct SKUs with a valid sale"),
    },
    label_columns={"stock_code": "description"},
    restricted_columns={"invoice_id": "a row-level identifier"},
    decompositions={"revenue": ("units", "avg_price"), "units": ("lines", "units_per_line")},
    record_label="transaction-level",
    capability=(
        "Owns product-level sales lines: SKU, description, category, quantity, unit price and returns. "
        "Answers which categories and products drove a change, whether the product range or prices "
        "changed, and whether return rates explain it."
    ),
    example_questions=(
        "Which categories and SKUs drove the decline?",
        "Did the product range change (lines stopped vs new lines)?",
        "Did prices or return rates change?",
    ),
)
