"""scripts/build_department_views.py: column split, segments, categories"""

import pandas as pd

from tests.conftest import ICELAND, UK_CHURNED, UK_NEW, UK_RETAINED


def _read(path):
    return pd.read_csv(path, dtype=str)


def test_each_view_keeps_only_its_own_unique_dimension(views):
    sales, customer, product = (_read(views[d]) for d in ("sales", "customer", "product"))
    assert "country" in sales and "customer_id" not in sales and "stock_code" not in sales
    assert "customer_id" in customer and "stock_code" not in customer
    assert "stock_code" in product and "customer_id" not in product and "country" not in product


def test_guest_orders_only_reach_sales_and_product(views, source):
    guests = source["customer_id"].isna().sum()
    assert len(_read(views["sales"])) == len(source)
    assert len(_read(views["product"])) == len(source)
    assert len(_read(views["customer"])) == len(source) - guests


def test_segments_follow_the_trailing_window(views):
    segment = _read(views["customer"]).drop_duplicates("customer_id").set_index("customer_id")["segment"]
    assert set(segment[UK_NEW]) == {"new"}
    # 14 位客户在基准期有消费：前 10%（四舍五入 1 位）是 high_value，接下来 40%（6 位）是 mid_value
    tiers = segment[UK_RETAINED + UK_CHURNED + ICELAND].value_counts()
    assert tiers["high_value"] == 1 and tiers["mid_value"] == 6 and tiers["low_value"] == 7


def test_categories_use_word_start_keywords(views):
    category = _read(views["product"]).drop_duplicates("stock_code").set_index("stock_code")["category"]
    assert category["10001"] == "Lighting & Candles"
    assert category["10002"] == "Home Decor"
    assert category["10003"] == "Kitchen & Dining"
    assert category["10004"] == "Lighting & Candles"
