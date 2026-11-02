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
def get_dashboard_summary_metrics(db: Session) -> Dict[str, Any]:
    """Comprehensive summary metrics for executive dashboard cards."""
    total_res = get_total_revenue(db)
    counts = db.query(
        func.count(func.distinct(SalesTransaction.product)).label("prods"),
        func.count(func.distinct(SalesTransaction.region)).label("regs"),
        func.count(func.distinct(SalesTransaction.category)).label("cats"),
    ).one()

    return {
        "total_gross_revenue": total_res["total_gross_revenue"],
        "total_net_revenue": total_res["total_net_revenue"],
        "total_discounts": total_res["total_discounts"],
        "total_quantity": total_res["total_quantity_sold"],
        "total_transactions": total_res["total_records"],
        "eligible_transactions": total_res["eligible_transaction_count"],
        "excluded_transactions": total_res["excluded_record_count"],
        "unique_products": counts.prods or 0,
        "unique_regions": counts.regs or 0,
        "unique_categories": counts.cats or 0,
        "average_order_value": total_res["average_order_value"],
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

