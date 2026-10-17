"""core/data: metrics, filters, periods and the data policy"""

import pandas as pd
import pytest

from core.data import filters, metrics, periods, policy
from core.data.errors import PolicyDenied, SkillError
from core.departments import get_department


A = periods.parse_period("2010-02:2010-04")


# ---------- metrics ----------

def test_ratio_metrics_are_ratios_of_sums(context, source):
    ctx = context("sales")
    frame = periods.in_period(ctx.df, "invoice_date", A)
    table = metrics.compute(frame, ctx.spec, ["revenue", "orders", "aov"])
    valid = periods.in_period(source, "invoice_date", A).query("is_valid_sale")
    assert table.loc["all", "revenue"] == pytest.approx(valid["line_amount"].sum())
    assert table.loc["all", "orders"] == valid["invoice_id"].nunique()
    assert table.loc["all", "aov"] == pytest.approx(valid["line_amount"].sum() / valid["invoice_id"].nunique())


def test_return_metrics_use_return_lines_with_flipped_sign(context):
    ctx = context("product")
    table = metrics.compute(periods.in_period(ctx.df, "invoice_date", A), ctx.spec, ["returned_units", "return_rate", "units"])
    assert table.loc["all", "returned_units"] == 3
    assert table.loc["all", "return_rate"] == pytest.approx(3 / table.loc["all", "units"])


def test_grouped_metrics_and_median(context):
    ctx = context("product")
    table = metrics.compute(ctx.df, ctx.spec, ["median_price", "units"], ["stock_code"])
    assert table.loc["10002", "median_price"] == 5.0
    assert set(table.index) == {"10001", "10002", "10003", "10004"}


def test_unknown_metric_lists_available_ones():
    with pytest.raises(SkillError, match="available"):
        metrics.resolve(get_department("sales"), ["revenu"])


# ---------- filters ----------

@pytest.mark.parametrize("text, op, values", [
    ("country=Iceland", "=", ("Iceland",)),
    ("country != Iceland", "!=", ("Iceland",)),
    ("country in Iceland,United Kingdom", "in", ("Iceland", "United Kingdom")),
    ("country NOT IN Iceland", "not in", ("Iceland",)),
    ("country in Iceland|United Kingdom", "in", ("Iceland", "United Kingdom")),
])
def test_filter_syntax(context, text, op, values):
    ctx = context("sales")
    parsed = filters.parse_filter(text, ctx.spec, ctx.df)
    assert (parsed.op, parsed.values) == (op, values)


def test_filter_on_unknown_value_suggests_close_matches(context):
    ctx = context("sales")
    with pytest.raises(SkillError, match="Iceland"):
        filters.parse_filter("country=Icelnd", ctx.spec, ctx.df)


def test_filter_on_restricted_column_is_denied(context):
    ctx = context("customer")
    with pytest.raises(PolicyDenied, match="personal data"):
        filters.parse_filter("customer_id=20001", ctx.spec, ctx.df)


def test_filter_on_non_dimension_is_an_error(context):
    ctx = context("sales")
    with pytest.raises(SkillError, match="cannot filter by"):
        filters.parse_filter("quantity=6", ctx.spec, ctx.df)


def test_apply_filters(context):
    ctx = context("sales")
    kept = filters.apply_filters(ctx.df, [filters.parse_filter("country=Iceland", ctx.spec, ctx.df)])
    assert set(kept["country"]) == {"Iceland"}


# ---------- periods ----------

def test_bare_month_covers_the_whole_month():
    period = periods.parse_period("2010-02:2010-04")
    assert (period.start, period.end) == (pd.Timestamp("2010-02-01"), pd.Timestamp("2010-04-30"))


@pytest.mark.parametrize("text", ["2010-02", "2010-04:2010-02", "2010-13:2011-01", "yesterday:today"])
def test_bad_periods_are_errors(text):
    with pytest.raises(SkillError):
        periods.parse_period(text)


def test_closure_inside_a_period_is_noted(context):
    ctx = context("sales")
    # 合成数据每月只在 5 号前后交易，所以这里只核对圣诞那段停业的确切日期
    notes = periods.coverage_notes(ctx.dates, periods.parse_period("2010-12-21:2011-01-04"))
    assert notes == ["no trading 2010-12-21..2011-01-04 (closure) inside period"]


def test_period_far_beyond_the_data_is_noted(context):
    ctx = context("sales")
    notes = periods.coverage_notes(ctx.dates, periods.parse_period("2011-02:2011-08"))
    assert any("extends beyond the data" in n for n in notes)


# ---------- policy ----------

def test_group_by_restricted_column_is_denied():
    spec = get_department("customer")
    for column in ("customer_id", "invoice_id"):
        with pytest.raises(PolicyDenied):
            policy.check_columns(spec, [column], purpose="group by", allowed=spec.group_columns)


def test_small_groups_lose_their_numbers(context):
    ctx = context("customer")
    table = metrics.compute(ctx.df, ctx.spec, ["revenue"], ["country"])
    table, suppressed = policy.suppress_small_groups(
        table, policy.entity_counts(ctx.df, ctx.spec, ["country"]), ctx.spec, ["revenue"])
    assert suppressed == 1
    assert table.loc["Iceland", "revenue"] is None
    assert table.loc["United Kingdom", "revenue"] > 0


def test_departments_without_entities_are_not_suppressed(context):
    ctx = context("sales")
    assert policy.entity_counts(ctx.df, ctx.spec, ["country"]) is None


def test_cap_rows():
    table = pd.DataFrame({"x": range(40)})
    capped, notes = policy.cap_rows(table, 100)
    assert len(capped) == 25 and notes == ["showing 25 of 40 rows"]
    with pytest.raises(SkillError):
        policy.cap_rows(table, 0)


def test_check_output_finds_identifiers_in_strings_only():
    restricted = frozenset({"20001"})
    assert policy.check_output({"rows": [["20001", 5]], "notes": []}, restricted)
    assert policy.check_output({"rows": [["UK", 20001]], "notes": ["customer 20001"]}, restricted)
    assert policy.check_output({"rows": [["UK", 20001]], "notes": ["revenue 120001"]}, restricted) is None
    assert policy.check_output({"rows": [[i] for i in range(26)]}, frozenset())
