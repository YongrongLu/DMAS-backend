"""Customer department: who buys, how often, and which segments changed"""

from core.departments.base import AOV, ORDERS, REVENUE, DepartmentSpec, Metric


CUSTOMER = DepartmentSpec(
    name="customer",
    display_name="Customer Department",
    csv_name="customer_data.csv",
    dimensions={
        "country": "country of the customer",
        "segment": "value tier as of 2011-01-31: high_value / mid_value / low_value / lapsed / new",
    },
    metrics={
        "revenue": REVENUE,
        "orders": ORDERS,
        "aov": AOV,
        "active_customers": Metric("active_customers", "nunique", column="customer_id",
                                   description="distinct customers with a valid sale"),
        "revenue_per_customer": Metric("revenue_per_customer", "ratio", numerator="revenue",
                                       denominator="active_customers",
                                       description="revenue / active customers"),
        "orders_per_customer": Metric("orders_per_customer", "ratio", numerator="orders",
                                      denominator="active_customers",
                                      description="orders / active customers (purchase frequency)"),
    },
    restricted_columns={
        "customer_id": "personal data",
        "invoice_id": "a row-level identifier",
    },
    entity_column="customer_id",
    k_anon_min=5,
    decompositions={"revenue": ("orders", "aov")},
    record_label="customer-level",
    capability=(
        "Owns purchase history of identified customers with their country and value segment. Answers "
        "whether customers churned or bought less, how often they order, and which segments changed. "
        "Results are aggregated; groups with fewer than 5 customers are suppressed."
    ),
    example_questions=(
        "Are we losing important customers, or are existing customers buying less?",
        "How did order frequency change for high-value customers?",
        "Which segments or markets changed the most?",
    ),
)
