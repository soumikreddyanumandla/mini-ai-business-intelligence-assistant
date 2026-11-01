"""
Automated Tests for Analytics Engine
------------------------------------
Validates the mathematical accuracy of SQL aggregations for:
- All five core mandatory analytical questions
- Additional registered analytical capabilities
- Safe handling of edge cases and comparisons.
"""

import pytest
from backend.analytics import (
    get_total_revenue,
    get_highest_revenue_product,
    get_monthly_revenue_trend,
    get_highest_revenue_region,
    compare_two_months,
    get_top_quantity_product,
    get_category_revenue_breakdown,
    get_sales_channel_comparison,
    get_average_transaction_value,
    get_discount_analysis,
)


def test_total_revenue_calculation(db_session):
    """Test 1: Verify total gross revenue, net revenue, discounts, and counts."""
    res = get_total_revenue(db_session)
    assert res["total_gross_revenue"] == 1443700.0
    assert res["total_net_revenue"] == 1439200.0
    assert res["total_discounts"] == 4500.0
    assert res["eligible_transaction_count"] == 48
    assert res["excluded_record_count"] == 3
    assert res["total_records"] == 51
    assert res["average_order_value"] == 29983.33


def test_highest_revenue_product(db_session):
    """Test 2: Verify the highest revenue generating product is Monitor."""
    res = get_highest_revenue_product(db_session)
    assert res["top_product"] == "Monitor"
    assert res["top_product_net_revenue"] == 473000.0
    assert res["top_product_quantity"] == 50
    assert len(res["ranking"]) == 7
    # Verify second product is Desk
    assert res["ranking"][1]["product"] == "Desk"
    assert res["ranking"][1]["net_revenue"] == 222500.0


def test_monthly_revenue_trend(db_session):
    """Test 3: Verify monthly trend spans 6 months with May 2026 as peak."""
    res = get_monthly_revenue_trend(db_session)
    trend = res["monthly_trend"]
    assert len(trend) == 6
    assert trend[0]["month"] == "2026-01"
    assert trend[0]["net_revenue"] == 210250.0
    assert res["best_performing_month"] == "2026-05"
    assert res["best_month_revenue"] == 318500.0


def test_highest_revenue_region(db_session):
    """Test 4: Verify South is the top-performing sales region."""
    res = get_highest_revenue_region(db_session)
    assert res["top_region"] == "South"
    assert res["top_region_revenue"] == 411200.0
    assert res["top_region_quantity"] == 182
    assert len(res["regions"]) == 4


def test_month_to_month_comparison_jan_feb(db_session):
    """Test 5: Verify head-to-head comparison between January and February 2026."""
    res = compare_two_months(db_session, "2026-01", "2026-02")
    assert res["month_1_revenue"] == 210250.0
    assert res["month_2_revenue"] == 234600.0
    assert res["absolute_difference"] == 24350.0
    assert res["percentage_difference"] == 11.58
    assert res["trend_direction"] == "increased"


def test_month_to_month_comparison_with_names(db_session):
    """Test 5b: Verify month parsing works with month names ('March' vs 'May')."""
    res = compare_two_months(db_session, "March", "May")
    assert res["month_1"] == "2026-03"
    assert res["month_2"] == "2026-05"
    assert res["month_1_revenue"] == 223900.0
    assert res["month_2_revenue"] == 318500.0
    assert res["absolute_difference"] == 94600.0
    assert res["trend_direction"] == "increased"


def test_highest_quantity_selling_product(db_session):
    """Test 6: Verify Wireless Mouse is the highest volume product."""
    res = get_top_quantity_product(db_session)
    assert res["top_product"] == "Wireless Mouse"
    assert res["total_units_sold"] == 228
    assert res["associated_revenue"] == 148200.0


def test_category_revenue_breakdown(db_session):
    """Test 7: Verify category revenue hierarchy (Accessories, Electronics, Furniture)."""
    res = get_category_revenue_breakdown(db_session)
    cats = res["categories"]
    assert len(cats) == 3
    assert cats[0]["category"] == "Accessories"
    assert cats[0]["net_revenue"] == 533100.0
    assert cats[1]["category"] == "Electronics"
    assert cats[1]["net_revenue"] == 473000.0
    assert cats[2]["category"] == "Furniture"
    assert cats[2]["net_revenue"] == 433100.0


def test_sales_channel_comparison(db_session):
    """Test 8: Verify Online vs Retail sales channel split."""
    res = get_sales_channel_comparison(db_session)
    channels = {c["sales_channel"]: c["net_revenue"] for c in res["channels"]}
    assert channels["Online"] == 746750.0
    assert channels["Retail"] == 692450.0
    assert res["best_channel"] == "Online"


def test_average_transaction_value(db_session):
    """Test 9: Verify average order value calculation."""
    res = get_average_transaction_value(db_session)
    assert res["average_transaction_value"] == 29983.33
    assert res["eligible_orders"] == 48


def test_discount_analysis(db_session):
    """Test 10: Verify total discounts and effective discount percentage."""
    res = get_discount_analysis(db_session)
    assert res["total_discounts"] == 4500.0
    assert res["total_gross_revenue"] == 1443700.0
    assert res["discount_rate_percentage"] == 0.31
