"""
Analytics Engine Module
-----------------------
Implements deterministic SQL aggregations and calculations for all business questions:
- Five mandatory core questions (Total Revenue, Top Product, Monthly Trend, Top Region, Month Comparison)
- 14 approved additional analytical capabilities
- Safe SQL execution via SQLAlchemy ORM and parameterized queries
- Never guesses or allows LLMs to calculate business numbers.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import numpy as np
from sqlalchemy import func, desc, asc, case, text
from sqlalchemy.orm import Session
from backend.models import SalesTransaction
from backend.cache import cached_query


@cached_query("analytics", ttl=60.0)
def get_total_revenue(db: Session) -> Dict[str, Any]:
    """
    Mandatory Question A: Total Revenue
    Returns total gross revenue, net revenue, total discounts, and transaction counts.
    """
    # Realized revenue from eligible completed transactions
    stats = (
        db.query(
            func.coalesce(func.sum(SalesTransaction.gross_revenue), 0.0).label("gross_rev"),
            func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("net_rev"),
            func.coalesce(func.sum(SalesTransaction.discount_amount), 0.0).label("total_disc"),
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("total_qty"),
            func.count(SalesTransaction.transaction_id).label("eligible_count"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .one()
    )

    excluded_count = (
        db.query(func.count(SalesTransaction.transaction_id))
        .filter(SalesTransaction.is_eligible == False)
        .scalar()
        or 0
    )

    gross = round(float(stats.gross_rev), 2)
    net = round(float(stats.net_rev), 2)
    disc = round(float(stats.total_disc), 2)
    qty = int(stats.total_qty)
    eligible_count = int(stats.eligible_count)
    total_count = eligible_count + excluded_count
    aov = round(net / eligible_count, 2) if eligible_count > 0 else 0.0

    return {
        "title": "Total Realized Sales Revenue",
        "total_gross_revenue": gross,
        "total_net_revenue": net,
        "total_discounts": disc,
        "total_quantity_sold": qty,
        "eligible_transaction_count": eligible_count,
        "excluded_record_count": excluded_count,
        "total_records": total_count,
        "average_order_value": aov,
        "currency": "INR",
        "supporting_data": [
            {"metric": "Gross Revenue", "value": gross, "unit": "INR"},
            {"metric": "Total Discounts Given", "value": disc, "unit": "INR"},
            {"metric": "Realized Net Revenue", "value": net, "unit": "INR"},
            {"metric": "Eligible Completed Orders", "value": eligible_count, "unit": "orders"},
            {"metric": "Excluded Records", "value": excluded_count, "unit": "records"},
        ],
        "chart_type": "metric",
    }


@cached_query("analytics", ttl=60.0)
def get_highest_revenue_product(db: Session, limit: int = 1) -> Dict[str, Any]:
    """
    Mandatory Question B: Highest-revenue product.
    Ranks products by total net revenue and returns the top product with full supporting breakdown.
    """
    rows = (
        db.query(
            SalesTransaction.product,
            func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("total_net"),
            func.coalesce(func.sum(SalesTransaction.gross_revenue), 0.0).label("total_gross"),
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("total_qty"),
            func.count(SalesTransaction.transaction_id).label("order_count"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .group_by(SalesTransaction.product)
        .order_by(desc("total_net"))
        .all()
    )

    ranking = []
    for rank, r in enumerate(rows, start=1):
        ranking.append({
            "rank": rank,
            "product": r.product,
            "net_revenue": round(float(r.total_net), 2),
            "gross_revenue": round(float(r.total_gross), 2),
            "quantity_sold": int(r.total_qty),
            "order_count": int(r.order_count),
        })

    top = ranking[0] if ranking else None

    return {
        "title": "Highest Revenue Generating Product",
        "top_product": top["product"] if top else "N/A",
        "top_product_net_revenue": top["net_revenue"] if top else 0.0,
        "top_product_quantity": top["quantity_sold"] if top else 0,
        "ranking": ranking,
        "supporting_data": ranking,
        "chart_type": "bar",
        "chart_x": "product",
        "chart_y": "net_revenue",
    }


@cached_query("analytics", ttl=60.0)
def get_monthly_revenue_trend(
    db: Session,
    region: Optional[str] = None,
    product: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Mandatory Question C: Monthly revenue trend.
    Aggregates revenue and volume chronologically by month (YYYY-MM).
    Supports optional region and product filters for conversational context.
    """
    # SQLite strftime('%Y-%m', order_date)
    month_expr = func.strftime("%Y-%m", SalesTransaction.order_date)

    query = (
        db.query(
            month_expr.label("month"),
            func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("net_revenue"),
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("quantity"),
            func.count(SalesTransaction.transaction_id).label("transaction_count"),
        )
        .filter(SalesTransaction.is_eligible == True)
    )

    title_suffix = ""
    if region:
        query = query.filter(func.lower(SalesTransaction.region) == region.strip().lower())
        title_suffix += f" for {region.title()} Region"
    if product:
        query = query.filter(func.lower(SalesTransaction.product) == product.strip().lower())
        title_suffix += f" for {product.title()}"

    rows = query.group_by(month_expr).order_by(asc("month")).all()

    trend = []
    prev_revenue = None
    best_month = None
    max_rev = -1.0

    for r in rows:
        rev = round(float(r.net_revenue), 2)
        qty = int(r.quantity)
        cnt = int(r.transaction_count)
        
        growth_pct = None
        if prev_revenue is not None and prev_revenue > 0:
            growth_pct = round(((rev - prev_revenue) / prev_revenue) * 100, 2)
        prev_revenue = rev

        if rev > max_rev:
            max_rev = rev
            best_month = r.month

        trend.append({
            "month": r.month,
            "net_revenue": rev,
            "quantity_sold": qty,
            "transaction_count": cnt,
            "growth_percentage": growth_pct,
        })

    return {
        "title": f"Monthly Revenue Trend{title_suffix}",
        "filtered_region": region,
        "filtered_product": product,
        "monthly_trend": trend,
        "best_performing_month": best_month,
        "best_month_revenue": max_rev,
        "supporting_data": trend,
        "chart_type": "line",
        "chart_x": "month",
        "chart_y": "net_revenue",
    }


@cached_query("analytics", ttl=60.0)
def get_highest_revenue_region(db: Session, limit: int = 1) -> Dict[str, Any]:
    """
    Mandatory Question D: Highest-revenue region.
    Ranks regions by net revenue and calculates regional market share.
    """
    rows = (
        db.query(
            SalesTransaction.region,
            func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("net_revenue"),
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("quantity"),
            func.count(SalesTransaction.transaction_id).label("transaction_count"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .group_by(SalesTransaction.region)
        .order_by(desc("net_revenue"))
        .all()
    )

    total_net = sum(float(r.net_revenue) for r in rows) or 1.0

    regions = []
    for rank, r in enumerate(rows, start=1):
        rev = round(float(r.net_revenue), 2)
        share = round((rev / total_net) * 100, 1)
        regions.append({
            "rank": rank,
            "region": r.region,
            "net_revenue": rev,
            "quantity_sold": int(r.quantity),
            "transaction_count": int(r.transaction_count),
            "revenue_share_percentage": share,
        })

    top = regions[0] if regions else None

    return {
        "title": "Highest Revenue Generating Region",
        "top_region": top["region"] if top else "N/A",
        "top_region_revenue": top["net_revenue"] if top else 0.0,
        "top_region_quantity": top["quantity_sold"] if top else 0,
        "regions": regions,
        "supporting_data": regions,
        "chart_type": "bar",
        "chart_x": "region",
        "chart_y": "net_revenue",
    }


def normalize_month_input(month_input: str) -> Optional[str]:
    """
    Normalizes month strings to 'YYYY-MM' format.
    Accepts: '2026-03', '03-2026', 'March 2026', 'Jan', 'January', '01', '1', etc.
    Defaulting to year 2026 if year is unspecified.
    """
    if not month_input:
        return None
    val = month_input.strip()

    # If already YYYY-MM
    if len(val) == 7 and val[4] == "-" and val[:4].isdigit() and val[5:].isdigit():
        return val

    # Try standard date parsing
    for fmt in ["%Y-%m", "%m-%Y", "%B %Y", "%b %Y", "%B", "%b", "%m"]:
        try:
            dt = datetime.strptime(val, fmt)
            year = dt.year if "%Y" in fmt else 2026
            return f"{year:04d}-{dt.month:02d}"
        except ValueError:
            continue

    return None


@cached_query("analytics", ttl=60.0)
def compare_two_months(db: Session, month_1: str, month_2: str) -> Dict[str, Any]:
    """
    Mandatory Question E: Comparison between two months.
    Compares net revenue, volume, and percentage growth between month_1 and month_2.
    Handles zero baseline safely.
    """
    norm_m1 = normalize_month_input(month_1)
    norm_m2 = normalize_month_input(month_2)

    if not norm_m1 or not norm_m2:
        return {
            "error": "Invalid or unparseable month parameters.",
            "provided": {"month_1": month_1, "month_2": month_2},
            "clarification_needed": True,
        }

    month_expr = func.strftime("%Y-%m", SalesTransaction.order_date)

    stats = (
        db.query(
            month_expr.label("month"),
            func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("net_revenue"),
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("quantity"),
            func.count(SalesTransaction.transaction_id).label("transaction_count"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .filter(month_expr.in_([norm_m1, norm_m2]))
        .group_by(month_expr)
        .all()
    )

    data = {r.month: {
        "net_revenue": round(float(r.net_revenue), 2),
        "quantity": int(r.quantity),
        "transactions": int(r.transaction_count),
    } for r in stats}

    rev_1 = data.get(norm_m1, {}).get("net_revenue", 0.0)
    qty_1 = data.get(norm_m1, {}).get("quantity", 0)
    tx_1 = data.get(norm_m1, {}).get("transactions", 0)

    rev_2 = data.get(norm_m2, {}).get("net_revenue", 0.0)
    qty_2 = data.get(norm_m2, {}).get("quantity", 0)
    tx_2 = data.get(norm_m2, {}).get("transactions", 0)

    abs_diff = round(rev_2 - rev_1, 2)
    if rev_1 > 0:
        pct_diff = round((abs_diff / rev_1) * 100, 2)
    else:
        pct_diff = 100.0 if rev_2 > 0 else 0.0

    if abs_diff > 0:
        trend = "increased"
    elif abs_diff < 0:
        trend = "decreased"
    else:
        trend = "remained constant"

    supporting = [
        {"period": norm_m1, "net_revenue": rev_1, "quantity_sold": qty_1, "orders": tx_1},
        {"period": norm_m2, "net_revenue": rev_2, "quantity_sold": qty_2, "orders": tx_2},
        {"metric": "Absolute Difference", "value": abs_diff, "unit": "INR"},
        {"metric": "Percentage Growth", "value": pct_diff, "unit": "%"},
    ]

    return {
        "title": f"Monthly Revenue Comparison: {norm_m1} vs {norm_m2}",
        "month_1": norm_m1,
        "month_1_revenue": rev_1,
        "month_2": norm_m2,
        "month_2_revenue": rev_2,
        "absolute_difference": abs_diff,
        "percentage_difference": pct_diff,
        "trend_direction": trend,
        "supporting_data": supporting,
        "chart_type": "bar",
        "chart_x": "period",
        "chart_y": "net_revenue",
    }


# =========================================================================
# Additional Analytical Capabilities (Extensibility Beyond The 5)
# =========================================================================

def get_top_quantity_product(db: Session, limit: int = 1) -> Dict[str, Any]:
    """Additional Tool 1: Product with highest units sold."""
    rows = (
        db.query(
            SalesTransaction.product,
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("total_qty"),
            func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("net_revenue"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .group_by(SalesTransaction.product)
        .order_by(desc("total_qty"))
        .all()
    )
    ranking = [
        {"rank": idx, "product": r.product, "quantity_sold": int(r.total_qty), "net_revenue": round(float(r.net_revenue), 2)}
        for idx, r in enumerate(rows, start=1)
    ]
    top = ranking[0] if ranking else None
    return {
        "title": "Highest Quantity Selling Product",
        "top_product": top["product"] if top else "N/A",
        "total_units_sold": top["quantity_sold"] if top else 0,
        "associated_revenue": top["net_revenue"] if top else 0.0,
        "supporting_data": ranking,
        "chart_type": "bar",
        "chart_x": "product",
        "chart_y": "quantity_sold",
    }


def get_lowest_quantity_product(db: Session, limit: int = 1) -> Dict[str, Any]:
    """Additional Tool 2: Product with lowest units sold."""
    rows = (
        db.query(
            SalesTransaction.product,
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("total_qty"),
            func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("net_revenue"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .group_by(SalesTransaction.product)
        .order_by(asc("total_qty"))
        .all()
    )
    ranking = [
        {"rank": idx, "product": r.product, "quantity_sold": int(r.total_qty), "net_revenue": round(float(r.net_revenue), 2)}
        for idx, r in enumerate(rows, start=1)
    ]
    lowest = ranking[0] if ranking else None
    return {
        "title": "Lowest Quantity Selling Product",
        "lowest_product": lowest["product"] if lowest else "N/A",
        "units_sold": lowest["quantity_sold"] if lowest else 0,
        "associated_revenue": lowest["net_revenue"] if lowest else 0.0,
        "supporting_data": ranking,
        "chart_type": "bar",
        "chart_x": "product",
        "chart_y": "quantity_sold",
    }


@cached_query("analytics", ttl=60.0)
def get_category_revenue_breakdown(db: Session) -> Dict[str, Any]:
    """Additional Tool 3: Category-wise revenue and contribution share."""
    rows = (
        db.query(
            SalesTransaction.category,
            func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("net_revenue"),
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("quantity"),
            func.count(SalesTransaction.transaction_id).label("transaction_count"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .group_by(SalesTransaction.category)
        .order_by(desc("net_revenue"))
        .all()
    )
    total_rev = sum(float(r.net_revenue) for r in rows) or 1.0
    categories = []
    for rank, r in enumerate(rows, start=1):
        rev = round(float(r.net_revenue), 2)
        categories.append({
            "rank": rank,
            "category": r.category,
            "net_revenue": rev,
            "quantity_sold": int(r.quantity),
            "transaction_count": int(r.transaction_count),
            "percentage_share": round((rev / total_rev) * 100, 1),
        })
    return {
        "title": "Category Revenue Breakdown",
        "categories": categories,
        "supporting_data": categories,
        "chart_type": "donut",
        "chart_labels": "category",
        "chart_values": "net_revenue",
    }


@cached_query("analytics", ttl=60.0)
def get_sales_channel_comparison(db: Session) -> Dict[str, Any]:
    """Additional Tool 4: Comparison between Online and Retail sales channels."""
    rows = (
        db.query(
            SalesTransaction.sales_channel,
            func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("net_revenue"),
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("quantity"),
            func.count(SalesTransaction.transaction_id).label("orders"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .group_by(SalesTransaction.sales_channel)
        .order_by(desc("net_revenue"))
        .all()
    )
    total_rev = sum(float(r.net_revenue) for r in rows) or 1.0
    channels = []
    for r in rows:
        rev = round(float(r.net_revenue), 2)
        channels.append({
            "sales_channel": r.sales_channel,
            "net_revenue": rev,
            "quantity_sold": int(r.quantity),
            "transaction_count": int(r.orders),
            "revenue_share_percentage": round((rev / total_rev) * 100, 1),
        })
    return {
        "title": "Sales Channel Performance Comparison",
        "channels": channels,
        "best_channel": channels[0]["sales_channel"] if channels else "N/A",
        "supporting_data": channels,
        "chart_type": "donut",
        "chart_labels": "sales_channel",
        "chart_values": "net_revenue",
    }


def get_average_transaction_value(db: Session) -> Dict[str, Any]:
    """Additional Tool 5: Average order/transaction value across eligible transactions."""
    total_res = get_total_revenue(db)
    aov = total_res["average_order_value"]
    return {
        "title": "Average Transaction Value",
        "average_transaction_value": aov,
        "eligible_orders": total_res["eligible_transaction_count"],
        "total_net_sales": total_res["total_net_revenue"],
        "supporting_data": [
            {"metric": "Average Order Value", "value": aov, "unit": "INR"},
            {"metric": "Total Realized Sales", "value": total_res["total_net_revenue"], "unit": "INR"},
            {"metric": "Total Eligible Orders", "value": total_res["eligible_transaction_count"], "unit": "orders"},
        ],
        "chart_type": "metric",
    }


def get_product_quantity_analysis(db: Session) -> Dict[str, Any]:
    """Additional Tool 6: Comprehensive quantity analysis across all products."""
    return get_top_quantity_product(db, limit=100)


def get_region_transaction_counts(db: Session) -> Dict[str, Any]:
    """Additional Tool 7: Regional order volume distribution."""
    reg_res = get_highest_revenue_region(db)
    return {
        "title": "Regional Transaction Volume",
        "regional_breakdown": reg_res["regions"],
        "supporting_data": reg_res["regions"],
        "chart_type": "bar",
        "chart_x": "region",
        "chart_y": "transaction_count",
    }


def get_monthly_growth_rate(db: Session) -> Dict[str, Any]:
    """Additional Tool 8: Month-over-month percentage growth rates."""
    return get_monthly_revenue_trend(db)


def get_revenue_contribution_by_category(db: Session) -> Dict[str, Any]:
    """Additional Tool 9: Category percentage contribution to overall revenue."""
    return get_category_revenue_breakdown(db)


def compare_products(db: Session, product_1: str, product_2: str) -> Dict[str, Any]:
    """Additional Tool 10: Head-to-head comparison of two specific products."""
    p1_clean = product_1.strip().lower()
    p2_clean = product_2.strip().lower()

    rows = (
        db.query(
            SalesTransaction.product,
            func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("net_revenue"),
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("quantity"),
            func.count(SalesTransaction.transaction_id).label("orders"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .filter(func.lower(SalesTransaction.product).in_([p1_clean, p2_clean]))
        .group_by(SalesTransaction.product)
        .all()
    )

    data = {r.product.lower(): {
        "product": r.product,
        "net_revenue": round(float(r.net_revenue), 2),
        "quantity": int(r.quantity),
        "orders": int(r.orders),
    } for r in rows}

    prod1_data = data.get(p1_clean, {"product": product_1, "net_revenue": 0.0, "quantity": 0, "orders": 0})
    prod2_data = data.get(p2_clean, {"product": product_2, "net_revenue": 0.0, "quantity": 0, "orders": 0})

    diff_rev = round(prod1_data["net_revenue"] - prod2_data["net_revenue"], 2)

    supporting = [
        prod1_data,
        prod2_data,
        {"metric": f"Revenue Difference ({prod1_data['product']} - {prod2_data['product']})", "value": diff_rev, "unit": "INR"},
    ]

    return {
        "title": f"Product Comparison: {prod1_data['product']} vs {prod2_data['product']}",
        "product_1": prod1_data,
        "product_2": prod2_data,
        "revenue_difference": diff_rev,
        "supporting_data": supporting,
        "chart_type": "bar",
        "chart_x": "product",
        "chart_y": "net_revenue",
    }


def compare_regions(db: Session, region_1: str, region_2: str) -> Dict[str, Any]:
    """Head-to-head comparison of two specific regions."""
    r1_clean = region_1.strip().lower()
    r2_clean = region_2.strip().lower()

    rows = (
        db.query(
            SalesTransaction.region,
            func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("net_revenue"),
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("quantity"),
            func.count(SalesTransaction.transaction_id).label("orders"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .filter(func.lower(SalesTransaction.region).in_([r1_clean, r2_clean]))
        .group_by(SalesTransaction.region)
        .all()
    )

    data = {r.region.lower(): {
        "region": r.region,
        "net_revenue": round(float(r.net_revenue), 2),
        "quantity": int(r.quantity),
        "orders": int(r.orders),
    } for r in rows}

    reg1_data = data.get(r1_clean, {"region": region_1.title(), "net_revenue": 0.0, "quantity": 0, "orders": 0})
    reg2_data = data.get(r2_clean, {"region": region_2.title(), "net_revenue": 0.0, "quantity": 0, "orders": 0})

    diff_rev = round(reg1_data["net_revenue"] - reg2_data["net_revenue"], 2)
    pct_diff = round((diff_rev / reg2_data["net_revenue"]) * 100, 2) if reg2_data["net_revenue"] > 0 else 0.0

    supporting = [
        reg1_data,
        reg2_data,
        {"metric": f"Revenue Difference ({reg1_data['region']} - {reg2_data['region']})", "value": diff_rev, "unit": "INR"},
        {"metric": "Percentage Difference", "value": pct_diff, "unit": "%"},
    ]

    return {
        "title": f"Region Comparison: {reg1_data['region']} vs {reg2_data['region']}",
        "region_1": reg1_data,
        "region_2": reg2_data,
        "revenue_difference": diff_rev,
        "percentage_difference": pct_diff,
        "supporting_data": supporting,
        "chart_type": "bar",
        "chart_x": "region",
        "chart_y": "net_revenue",
    }


def get_lowest_performing_product(db: Session) -> Dict[str, Any]:
    """Identifies the product with the lowest realized net sales revenue."""
    rows = (
        db.query(
            SalesTransaction.product,
            func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("total_net"),
            func.coalesce(func.sum(SalesTransaction.gross_revenue), 0.0).label("total_gross"),
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("total_qty"),
            func.count(SalesTransaction.transaction_id).label("order_count"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .group_by(SalesTransaction.product)
        .order_by(asc("total_net"))
        .all()
    )

    if not rows:
        return {"title": "Lowest Performing Product", "lowest_product": "N/A", "net_revenue": 0.0, "supporting_data": []}

    lowest = rows[0]
    return {
        "title": "Lowest Performing Product by Revenue",
        "lowest_product": lowest.product,
        "lowest_product_net_revenue": round(float(lowest.total_net), 2),
        "lowest_product_gross_revenue": round(float(lowest.total_gross), 2),
        "quantity_sold": int(lowest.total_qty),
        "order_count": int(lowest.order_count),
        "supporting_data": [
            {"product": r.product, "net_revenue": round(float(r.total_net), 2), "quantity": int(r.total_qty)}
            for r in rows
        ],
        "chart_type": "bar",
        "chart_x": "product",
        "chart_y": "net_revenue",
    }


def get_transaction_status_breakdown(db: Session) -> Dict[str, Any]:
    """Additional Tool 11: Breakdown of all records by status (Completed, Returned, etc.)."""
    rows = (
        db.query(
            SalesTransaction.status,
            func.count(SalesTransaction.transaction_id).label("record_count"),
            func.coalesce(func.sum(SalesTransaction.quantity), 0).label("total_quantity"),
        )
        .group_by(SalesTransaction.status)
        .all()
    )
    breakdown = [
        {"status": r.status, "record_count": int(r.record_count), "total_quantity": int(r.total_quantity)}
        for r in rows
    ]
    return {
        "title": "Transaction Status Distribution",
        "status_breakdown": breakdown,
        "supporting_data": breakdown,
        "chart_type": "donut",
        "chart_labels": "status",
        "chart_values": "record_count",
    }


def get_discount_analysis(db: Session) -> Dict[str, Any]:
    """Additional Tool 12: Discount metrics, total discount, average discount per order."""
    stats = (
        db.query(
            func.coalesce(func.sum(SalesTransaction.discount_amount), 0.0).label("total_disc"),
            func.coalesce(func.sum(SalesTransaction.gross_revenue), 0.0).label("total_gross"),
            func.count(SalesTransaction.transaction_id).label("eligible_orders"),
            func.count(case((SalesTransaction.discount_amount > 0, 1))).label("discounted_orders"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .one()
    )
    total_disc = round(float(stats.total_disc), 2)
    total_gross = round(float(stats.total_gross), 2)
    disc_rate = round((total_disc / total_gross) * 100, 2) if total_gross > 0 else 0.0
    discounted_orders = int(stats.discounted_orders)

    return {
        "title": "Sales Discount Analysis",
        "total_discounts": total_disc,
        "total_gross_revenue": total_gross,
        "discount_rate_percentage": disc_rate,
        "discounted_orders_count": discounted_orders,
        "supporting_data": [
            {"metric": "Total Discounts", "value": total_disc, "unit": "INR"},
            {"metric": "Gross Sales", "value": total_gross, "unit": "INR"},
            {"metric": "Effective Discount Rate", "value": disc_rate, "unit": "%"},
            {"metric": "Orders With Discount", "value": discounted_orders, "unit": "orders"},
        ],
        "chart_type": "metric",
    }


def get_best_sales_channel(db: Session) -> Dict[str, Any]:
    """Additional Tool 13: Best-performing sales channel."""
    return get_sales_channel_comparison(db)


def get_top_n_products_by_revenue(db: Session, n: int = 5) -> Dict[str, Any]:
    """Additional Tool 14: Top N products ranked by revenue."""
    full_prod = get_highest_revenue_product(db)
    ranking = full_prod["ranking"][:n]
    return {
        "title": f"Top {n} Products by Revenue",
        "top_n_products": ranking,
        "supporting_data": ranking,
        "chart_type": "bar",
        "chart_x": "product",
        "chart_y": "net_revenue",
    }


@cached_query("analytics", ttl=60.0)
def get_dashboard_summary_metrics(
    db: Session,
    region: Optional[str] = None,
    category: Optional[str] = None,
    channel: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Comprehensive summary metrics for executive dashboard cards with optional filtering.
    When no filters are provided, aggregates across the entire eligible dataset.
    """
    query = db.query(
        func.coalesce(func.sum(SalesTransaction.gross_revenue), 0.0).label("gross_rev"),
        func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0).label("net_rev"),
        func.coalesce(func.sum(SalesTransaction.discount_amount), 0.0).label("total_disc"),
        func.coalesce(func.sum(SalesTransaction.quantity), 0).label("total_qty"),
        func.count(SalesTransaction.transaction_id).label("eligible_count"),
    ).filter(SalesTransaction.is_eligible == True)

    all_query = db.query(func.count(SalesTransaction.transaction_id))
    ex_query = db.query(func.count(SalesTransaction.transaction_id)).filter(SalesTransaction.is_eligible == False)

    dist_query = db.query(
        func.count(func.distinct(SalesTransaction.product)).label("prods"),
        func.count(func.distinct(SalesTransaction.region)).label("regs"),
        func.count(func.distinct(SalesTransaction.category)).label("cats"),
    ).filter(SalesTransaction.is_eligible == True)

    # Apply optional filters
    if region and region.strip().lower() != "all":
        reg_val = region.strip()
        query = query.filter(SalesTransaction.region.ilike(f"%{reg_val}%"))
        all_query = all_query.filter(SalesTransaction.region.ilike(f"%{reg_val}%"))
        ex_query = ex_query.filter(SalesTransaction.region.ilike(f"%{reg_val}%"))
        dist_query = dist_query.filter(SalesTransaction.region.ilike(f"%{reg_val}%"))

    if category and category.strip().lower() != "all":
        cat_val = category.strip()
        query = query.filter(SalesTransaction.category.ilike(f"%{cat_val}%"))
        all_query = all_query.filter(SalesTransaction.category.ilike(f"%{cat_val}%"))
        ex_query = ex_query.filter(SalesTransaction.category.ilike(f"%{cat_val}%"))
        dist_query = dist_query.filter(SalesTransaction.category.ilike(f"%{cat_val}%"))

    if channel and channel.strip().lower() != "all":
        chan_val = channel.strip()
        query = query.filter(SalesTransaction.sales_channel.ilike(f"%{chan_val}%"))
        all_query = all_query.filter(SalesTransaction.sales_channel.ilike(f"%{chan_val}%"))
        ex_query = ex_query.filter(SalesTransaction.sales_channel.ilike(f"%{chan_val}%"))
        dist_query = dist_query.filter(SalesTransaction.sales_channel.ilike(f"%{chan_val}%"))

    if start_date:
        query = query.filter(SalesTransaction.order_date >= start_date)
        all_query = all_query.filter(SalesTransaction.order_date >= start_date)
        ex_query = ex_query.filter(SalesTransaction.order_date >= start_date)
        dist_query = dist_query.filter(SalesTransaction.order_date >= start_date)

    if end_date:
        query = query.filter(SalesTransaction.order_date <= end_date)
        all_query = all_query.filter(SalesTransaction.order_date <= end_date)
        ex_query = ex_query.filter(SalesTransaction.order_date <= end_date)
        dist_query = dist_query.filter(SalesTransaction.order_date <= end_date)

    stats = query.one()
    total_records = all_query.scalar() or 0
    excluded_records = ex_query.scalar() or 0
    counts = dist_query.one()

    gross = round(float(stats.gross_rev), 2)
    net = round(float(stats.net_rev), 2)
    disc = round(float(stats.total_disc), 2)
    qty = int(stats.total_qty)
    eligible_count = int(stats.eligible_count)
    aov = round(net / eligible_count, 2) if eligible_count > 0 else 0.0

    return {
        "total_gross_revenue": gross,
        "total_net_revenue": net,
        "total_discounts": disc,
        "total_quantity": qty,
        "total_transactions": total_records,
        "eligible_transactions": eligible_count,
        "excluded_transactions": excluded_records,
        "unique_products": counts.prods or 0,
        "unique_regions": counts.regs or 0,
        "unique_categories": counts.cats or 0,
        "average_order_value": aov,
        "currency": "INR",
    }


@cached_query("analytics", ttl=60.0)
def get_data_quality_summary(db: Session) -> Dict[str, Any]:
    """Summary of dataset quality, record eligibility, and audit counts."""
    counts = db.query(
        func.count(SalesTransaction.transaction_id).label("total"),
        func.sum(case((SalesTransaction.is_eligible == True, 1), else_=0)).label("eligible"),
    ).one()
    total_records = counts.total or 0
    eligible_count = int(counts.eligible or 0)
    excluded_records = total_records - eligible_count
    cleanliness = round((eligible_count / total_records) * 100, 2) if total_records > 0 else 0.0
    return {
        "total_records": total_records,
        "eligible_records": eligible_count,
        "excluded_records": excluded_records,
        "cleanliness_percentage": cleanliness,
    }


@cached_query("analytics", ttl=60.0)
def get_data_quality_audit(db: Session) -> Dict[str, Any]:
    """
    Detailed audit of data quality issues, excluded records, and cleanliness rate.
    Returns structured metrics and row-level excluded items with exact policy violation reasons.
    """
    total_records = db.query(SalesTransaction).count()
    eligible_count = db.query(SalesTransaction).filter(SalesTransaction.is_eligible == True).count()
    excluded_rows = db.query(SalesTransaction).filter(SalesTransaction.is_eligible == False).all()
    cleanliness = round((eligible_count / total_records) * 100, 2) if total_records > 0 else 0.0

    supporting_data = []
    for r in excluded_rows:
        supporting_data.append({
            "Transaction ID": r.transaction_id,
            "Date": r.order_date.isoformat() if r.order_date else "N/A",
            "Product": r.product or "N/A",
            "Quantity": r.quantity,
            "Unit Price": f"₹{r.unit_price:,.2f}" if r.unit_price is not None else "Missing",
            "Status": r.status,
            "Exclusion Reason": r.exclusion_reason or "Business Policy Violation",
        })

    return {
        "title": f"Data Quality Audit: {len(excluded_rows)} Issues Flagged ({cleanliness}% Cleanliness)",
        "total_records": total_records,
        "eligible_records": eligible_count,
        "excluded_records": len(excluded_rows),
        "cleanliness_percentage": cleanliness,
        "supporting_data": supporting_data,
        "chart_type": "table",
    }


# ======================================================================
# Phase 2 – Package B: Advanced Analytics
# ======================================================================

@cached_query("analytics", ttl=60.0)
def detect_anomalies(
    db: Session,
    z_threshold: float = 2.5,
) -> Dict[str, Any]:
    """
    Advanced Anomaly Detection (IQR and Z-score methods).
    Technical Constraint: Strictly distinguishes empirical statistical outliers
    (high/low value eligible transactions) from confirmed data-quality errors
    (excluded transactions with missing data, negative values, or cancellations).
    """
    # 1. Eligible transactions for statistical outlier analysis
    eligible_txs = (
        db.query(SalesTransaction)
        .filter(SalesTransaction.is_eligible == True)
        .all()
    )

    if not eligible_txs:
        return {
            "title": "Anomaly Detection Analysis",
            "statistical_outliers_count": 0,
            "confirmed_data_quality_errors_count": 0,
            "message": "No eligible transactions available for statistical analysis.",
            "statistical_outliers": [],
            "data_quality_errors": [],
            "supporting_data": [],
            "chart_type": "table",
        }

    revenues = np.array([float(t.net_revenue) for t in eligible_txs])
    mean_rev = float(np.mean(revenues))
    std_rev = float(np.std(revenues))
    q25, q75 = np.percentile(revenues, [25, 75])
    iqr = float(q75 - q25)
    iqr_lower = float(q25 - 1.5 * iqr)
    iqr_upper = float(q75 + 1.5 * iqr)

    # Detect statistical outliers
    statistical_outliers = []
    for t in eligible_txs:
        net = float(t.net_revenue)
        z_score = float((net - mean_rev) / std_rev) if std_rev > 0 else 0.0
        is_iqr_outlier = (net < iqr_lower or net > iqr_upper)
        is_z_outlier = (abs(z_score) >= z_threshold)

        if is_iqr_outlier or is_z_outlier:
            outlier_type = []
            if is_iqr_outlier:
                outlier_type.append("IQR Outlier (1.5x IQR)")
            if is_z_outlier:
                outlier_type.append(f"Z-Score (|z| >= {z_threshold})")

            statistical_outliers.append({
                "transaction_id": t.transaction_id,
                "order_date": t.order_date.isoformat() if t.order_date else "N/A",
                "product": t.product,
                "category": t.category,
                "region": t.region,
                "sales_channel": t.sales_channel,
                "quantity": t.quantity,
                "unit_price": t.unit_price,
                "net_revenue": round(net, 2),
                "z_score": round(z_score, 2),
                "outlier_methods": " + ".join(outlier_type),
                "classification": "Statistical Outlier (Eligible Transaction)",
            })

    # Sort statistical outliers by net revenue descending
    statistical_outliers.sort(key=lambda x: x["net_revenue"], reverse=True)

    # 2. Retrieve confirmed data-quality errors
    excluded_txs = (
        db.query(SalesTransaction)
        .filter(SalesTransaction.is_eligible == False)
        .order_by(SalesTransaction.transaction_id.asc())
        .all()
    )

    data_quality_errors = []
    for t in excluded_txs:
        data_quality_errors.append({
            "transaction_id": t.transaction_id,
            "order_date": t.order_date.isoformat() if t.order_date else "N/A",
            "product": t.product or "N/A",
            "category": t.category or "N/A",
            "region": t.region or "N/A",
            "quantity": t.quantity,
            "unit_price": t.unit_price,
            "status": t.status,
            "exclusion_reason": t.exclusion_reason or "Policy Violation",
            "classification": "Confirmed Data Quality Error (Excluded Transaction)",
        })

    # Combined supporting data table
    supporting_data = []
    for s in statistical_outliers:
        supporting_data.append({
            "ID": s["transaction_id"],
            "Classification": "Statistical Outlier",
            "Product": s["product"],
            "Net Revenue": f"₹{s['net_revenue']:,.2f}",
            "Details": f"Z-Score: {s['z_score']}, {s['outlier_methods']}",
        })
    for dq in data_quality_errors:
        supporting_data.append({
            "ID": dq["transaction_id"],
            "Classification": "Data Quality Error",
            "Product": dq["product"],
            "Net Revenue": "Excluded (₹0.00)",
            "Details": f"Reason: {dq['exclusion_reason']} (Status: {dq['status']})",
        })

    return {
        "title": f"Anomaly Detection: {len(statistical_outliers)} Statistical Outliers & {len(data_quality_errors)} Data Quality Errors",
        "eligible_transactions_analyzed": len(eligible_txs),
        "mean_transaction_revenue": round(mean_rev, 2),
        "std_dev_revenue": round(std_rev, 2),
        "iqr": round(iqr, 2),
        "iqr_lower_bound": round(iqr_lower, 2),
        "iqr_upper_bound": round(iqr_upper, 2),
        "statistical_outliers_count": len(statistical_outliers),
        "confirmed_data_quality_errors_count": len(data_quality_errors),
        "statistical_outliers": statistical_outliers,
        "data_quality_errors": data_quality_errors,
        "supporting_data": supporting_data,
        "chart_type": "table",
    }


@cached_query("analytics", ttl=60.0)
def get_pareto_revenue_concentration(
    db: Session,
    top_pct_cutoff: float = 80.0,
) -> Dict[str, Any]:
    """
    Pareto 80/20 Revenue Concentration Analysis.
    Technical Constraint: Calculations use eligible transactions and clearly state the denominator.
    """
    rows = (
        db.query(
            SalesTransaction.product,
            func.sum(SalesTransaction.net_revenue).label("net_rev"),
            func.sum(SalesTransaction.gross_revenue).label("gross_rev"),
            func.sum(SalesTransaction.quantity).label("total_qty"),
            func.count(SalesTransaction.transaction_id).label("order_count"),
        )
        .filter(SalesTransaction.is_eligible == True)
        .group_by(SalesTransaction.product)
        .order_by(desc("net_rev"))
        .all()
    )

    if not rows:
        return {
            "title": "Pareto 80/20 Revenue Concentration",
            "total_products": 0,
            "vital_few_count": 0,
            "denominator_total_eligible_net_revenue": 0.0,
            "denominator_description": "Total Realized Net Revenue from eligible completed transactions",
            "ranking": [],
            "supporting_data": [],
            "chart_type": "bar",
        }

    total_eligible_net = float(sum(r.net_rev for r in rows))
    denominator = round(total_eligible_net, 2)

    ranking = []
    cum_rev = 0.0
    vital_few_count = 0

    for idx, r in enumerate(rows, start=1):
        net_val = float(r.net_rev)
        cum_rev += net_val
        share_pct = round((net_val / total_eligible_net) * 100.0, 2) if total_eligible_net > 0 else 0.0
        cum_pct = round((cum_rev / total_eligible_net) * 100.0, 2) if total_eligible_net > 0 else 0.0

        prev_cum = ranking[-1]["cumulative_share_percentage"] if ranking else 0.0
        is_vital = (cum_pct <= top_pct_cutoff) or (prev_cum < top_pct_cutoff)
        if is_vital:
            vital_few_count = idx

        ranking.append({
            "rank": idx,
            "product": r.product,
            "net_revenue": round(net_val, 2),
            "revenue_share_percentage": share_pct,
            "cumulative_revenue": round(cum_rev, 2),
            "cumulative_share_percentage": cum_pct,
            "in_vital_80_cohort": is_vital,
            "quantity_sold": int(r.total_qty),
            "order_count": int(r.order_count),
        })

    for item in ranking:
        item["in_vital_80_cohort"] = item["rank"] <= vital_few_count

    vital_pct_products = round((vital_few_count / len(ranking)) * 100.0, 2) if ranking else 0.0
    vital_revenue = round(ranking[vital_few_count - 1]["cumulative_revenue"], 2) if vital_few_count > 0 else 0.0
    vital_rev_pct = round(ranking[vital_few_count - 1]["cumulative_share_percentage"], 2) if vital_few_count > 0 else 0.0

    supporting_data = [
        {
            "Rank": item["rank"],
            "Product": item["product"],
            "Net Revenue": f"₹{item['net_revenue']:,.2f}",
            "Share (%)": f"{item['revenue_share_percentage']:.1f}%",
            "Cumulative (%)": f"{item['cumulative_share_percentage']:.1f}%",
            "80/20 Cohort": "Top 80% Driver" if item["in_vital_80_cohort"] else "Remaining Long Tail",
        }
        for item in ranking
    ]

    return {
        "title": f"Pareto 80/20 Analysis: Top {vital_few_count} Products Drive {vital_rev_pct}% of Net Revenue",
        "total_products": len(ranking),
        "vital_few_count": vital_few_count,
        "vital_few_product_percentage": vital_pct_products,
        "vital_revenue_achieved": vital_revenue,
        "vital_revenue_share_percentage": vital_rev_pct,
        "denominator_total_eligible_net_revenue": denominator,
        "denominator_description": "Total Realized Net Revenue from all eligible completed transactions (excludes returned/invalid orders)",
        "concentration_summary": (
            f"The top {vital_few_count} of {len(ranking)} products ({vital_pct_products}% of the catalog) "
            f"account for ₹{vital_revenue:,.2f} ({vital_rev_pct}%) of the total realized net revenue denominator of ₹{denominator:,.2f}."
        ),
        "ranking": ranking,
        "supporting_data": supporting_data,
        "chart_type": "bar",
    }


@cached_query("analytics", ttl=60.0)
def simulate_what_if_revenue(
    db: Session,
    price_change_pct: float = 0.0,
    volume_change_pct: float = 0.0,
    discount_adjustment_pct: float = 0.0,
    category: Optional[str] = None,
    channel: Optional[str] = None,
) -> Dict[str, Any]:
    """
    What-If Revenue Simulation Model.
    Technical Constraint: Models top-line net revenue adjustments strictly from
    unit price, quantity sold, and discount adjustments. Does not invent product costs
    or operating margins since costs are not present in the empirical sales dataset.
    """
    query = db.query(SalesTransaction).filter(SalesTransaction.is_eligible == True)
    if category and category.strip():
        query = query.filter(func.lower(SalesTransaction.category) == category.strip().lower())
    if channel and channel.strip():
        query = query.filter(func.lower(SalesTransaction.sales_channel) == channel.strip().lower())

    txs = query.all()
    if not txs:
        return {
            "title": "What-If Revenue Simulation",
            "message": "No eligible transactions match the specified scenario filters.",
            "baseline_net_revenue": 0.0,
            "simulated_net_revenue": 0.0,
            "net_revenue_delta": 0.0,
            "net_revenue_delta_percentage": 0.0,
            "supporting_data": [],
            "chart_type": "bar",
        }

    p_mult = 1.0 + (price_change_pct / 100.0)
    v_mult = 1.0 + (volume_change_pct / 100.0)
    d_mult = 1.0 + (discount_adjustment_pct / 100.0)

    base_gross_total = 0.0
    base_disc_total = 0.0
    base_net_total = 0.0

    sim_gross_total = 0.0
    sim_disc_total = 0.0
    sim_net_total = 0.0

    product_breakdown = {}

    for t in txs:
        base_gross = float(t.quantity * t.unit_price)
        base_disc = float(t.discount_amount)
        base_net = float(t.net_revenue)

        base_gross_total += base_gross
        base_disc_total += base_disc
        base_net_total += base_net

        sim_qty = t.quantity * v_mult
        sim_price = t.unit_price * p_mult
        sim_gross = sim_qty * sim_price
        sim_disc = base_disc * d_mult
        sim_net = max(0.0, sim_gross - sim_disc)

        sim_gross_total += sim_gross
        sim_disc_total += sim_disc
        sim_net_total += sim_net

        prod = t.product
        if prod not in product_breakdown:
            product_breakdown[prod] = {"base_net": 0.0, "sim_net": 0.0}
        product_breakdown[prod]["base_net"] += base_net
        product_breakdown[prod]["sim_net"] += sim_net

    delta_net = sim_net_total - base_net_total
    delta_pct = (delta_net / base_net_total * 100.0) if base_net_total > 0 else 0.0

    supporting_data = [
        {"Metric": "Baseline Net Revenue", "Value": f"₹{base_net_total:,.2f}", "Change": "Baseline (0%)"},
        {"Metric": "Simulated Net Revenue", "Value": f"₹{sim_net_total:,.2f}", "Change": f"{delta_pct:+.2f}%"},
        {"Metric": "Net Revenue Delta", "Value": f"₹{delta_net:+,.2f}", "Change": f"₹{delta_net:+,.2f}"},
        {"Metric": "Simulated Gross Revenue", "Value": f"₹{sim_gross_total:,.2f}", "Change": f"Price: {price_change_pct:+.1f}%, Vol: {volume_change_pct:+.1f}%"},
        {"Metric": "Simulated Discounts", "Value": f"₹{sim_disc_total:,.2f}", "Change": f"Discount Adj: {discount_adjustment_pct:+.1f}%"},
    ]

    breakdown_list = [
        {
            "product": k,
            "baseline_net": round(v["base_net"], 2),
            "simulated_net": round(v["sim_net"], 2),
            "delta": round(v["sim_net"] - v["base_net"], 2),
        }
        for k, v in sorted(product_breakdown.items(), key=lambda item: item[1]["sim_net"], reverse=True)
    ]

    return {
        "title": f"What-If Simulation: Net Revenue Projected at ₹{sim_net_total:,.2f} ({delta_pct:+.2f}%)",
        "scenario_parameters": {
            "price_change_percentage": price_change_pct,
            "volume_change_percentage": volume_change_pct,
            "discount_adjustment_percentage": discount_adjustment_pct,
            "category_filter": category or "All",
            "channel_filter": channel or "All",
        },
        "baseline_net_revenue": round(base_net_total, 2),
        "simulated_net_revenue": round(sim_net_total, 2),
        "net_revenue_delta": round(delta_net, 2),
        "net_revenue_delta_percentage": round(delta_pct, 2),
        "cost_model_disclaimer": "Technical Notice: What-if model projects top-line revenues only. Operating costs and profit margins are omitted because product cost data is not present in the empirical dataset.",
        "product_breakdown": breakdown_list[:10],
        "supporting_data": supporting_data,
        "chart_type": "bar",
    }


@cached_query("analytics", ttl=60.0)
def get_sales_target_pacing(
    db: Session,
    monthly_target: float = 500000.0,
    target_year: Optional[int] = None,
    target_month: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Sales Target & Quota Pacing Analysis.
    Technical Constraint: Strictly distinguishes user/executive configured targets
    from empirical sales data.
    """
    tx_query = db.query(SalesTransaction).filter(SalesTransaction.is_eligible == True)

    if target_year is not None and target_month is not None:
        start_date = datetime(target_year, target_month, 1)
        if target_month == 12:
            end_date = datetime(target_year + 1, 1, 1)
        else:
            end_date = datetime(target_year, target_month + 1, 1)
        tx_query = tx_query.filter(
            SalesTransaction.order_date >= start_date,
            SalesTransaction.order_date < end_date,
        )
        period_label = start_date.strftime("%B %Y")
    else:
        latest_date = db.query(func.max(SalesTransaction.order_date)).filter(SalesTransaction.is_eligible == True).scalar()
        if latest_date:
            target_year = latest_date.year
            target_month = latest_date.month
            start_date = datetime(target_year, target_month, 1)
            if target_month == 12:
                end_date = datetime(target_year + 1, 1, 1)
            else:
                end_date = datetime(target_year, target_month + 1, 1)
            tx_query = tx_query.filter(
                SalesTransaction.order_date >= start_date,
                SalesTransaction.order_date < end_date,
            )
            period_label = start_date.strftime("%B %Y")
        else:
            period_label = "Current Period"

    # Days in month calculation
    if target_month in (1, 3, 5, 7, 8, 10, 12):
        days_in_month = 31
    elif target_month == 2:
        days_in_month = 29 if (target_year and target_year % 4 == 0) else 28
    else:
        days_in_month = 30

    actual_revenue = float(
        tx_query.with_entities(func.coalesce(func.sum(SalesTransaction.net_revenue), 0.0)).scalar() or 0.0
    )
    actual_orders = tx_query.count()

    latest_tx_date = tx_query.with_entities(func.max(SalesTransaction.order_date)).scalar()
    elapsed_days = latest_tx_date.day if latest_tx_date else days_in_month
    elapsed_days = max(1, min(elapsed_days, days_in_month))

    target = round(float(monthly_target), 2)
    actual = round(actual_revenue, 2)
    attainment_pct = round((actual / target) * 100.0, 2) if target > 0 else 0.0

    run_rate_projected = round((actual / elapsed_days) * days_in_month, 2)
    projected_attainment_pct = round((run_rate_projected / target) * 100.0, 2) if target > 0 else 0.0
    variance_to_target = round(actual - target, 2)

    if projected_attainment_pct >= 105.0:
        pacing_status = "Ahead of Pace"
    elif projected_attainment_pct >= 95.0:
        pacing_status = "On Track"
    else:
        pacing_status = "Behind Pace"

    supporting_data = [
        {
            "Metric": "Configured Target (Quota)",
            "Value": f"₹{target:,.2f}",
            "Source": "Configured Business Target",
        },
        {
            "Metric": "Actual Realized Net Revenue",
            "Value": f"₹{actual:,.2f}",
            "Source": "Empirical Sales Transactions",
        },
        {
            "Metric": "Current Quota Attainment",
            "Value": f"{attainment_pct:.1f}%",
            "Source": "Calculated (Actual / Target)",
        },
        {
            "Metric": "Run-Rate Projected Month-End",
            "Value": f"₹{run_rate_projected:,.2f} ({projected_attainment_pct:.1f}%)",
            "Source": f"Run-Rate Projection ({elapsed_days}/{days_in_month} Days Elapsed)",
        },
        {
            "Metric": "Pacing Status",
            "Value": pacing_status,
            "Source": "Projected Attainment vs Target",
        },
    ]

    return {
        "title": f"Sales Quota Pacing ({period_label}): {attainment_pct:.1f}% Attained ({pacing_status})",
        "period": period_label,
        "configured_target": {
            "amount": target,
            "currency": "INR",
            "source": "Configured Business Target (Not from empirical dataset)",
        },
        "empirical_actuals": {
            "actual_revenue": actual,
            "actual_orders": actual_orders,
            "currency": "INR",
            "source": "Empirical SQLite Database (Eligible completed transactions)",
        },
        "pacing_metrics": {
            "elapsed_days": elapsed_days,
            "total_days_in_period": days_in_month,
            "attainment_percentage": attainment_pct,
            "run_rate_projected_revenue": run_rate_projected,
            "projected_attainment_percentage": projected_attainment_pct,
            "variance_to_target": variance_to_target,
            "status": pacing_status,
        },
        "supporting_data": supporting_data,
        "chart_type": "metric",
    }

