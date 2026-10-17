"""Sales department: revenue, orders and markets over time"""

from core.departments.base import AOV, ORDERS, REVENUE, UNITS, DepartmentSpec, Metric


SALES = DepartmentSpec(
    name="sales",
    display_name="Sales Department",
    csv_name="sales_data.csv",
    dimensions={"country": "market of the order"},
    metrics={
        "revenue": REVENUE,
        "orders": ORDERS,
        "units": UNITS,
        "aov": AOV,
        "units_per_order": Metric("units_per_order", "ratio", numerator="units", denominator="orders",
                                  description="units per order = units / orders"),
    },
    restricted_columns={"invoice_id": "a row-level identifier"},
    decompositions={"revenue": ("orders", "aov")},
    record_label="transaction-level",
    capability=(
        "Owns order-level sales by market (country) and time. Answers when sales changed, which periods "
        "and markets drove the change, and whether the change came from order volume or order value."
    ),
    example_questions=(
        "How did revenue, orders and AOV change between two periods?",
        "Which markets contributed most to the decline?",
        "Which weeks or months show unusual changes?",
    ),
)
