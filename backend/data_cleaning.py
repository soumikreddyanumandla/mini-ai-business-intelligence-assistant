"""
Data Cleaning and Validation Module
-----------------------------------
Implements documented business eligibility policy and data quality checks:
- Realized Net Revenue requires Status == 'Completed'
- Exclude 'Returned' transactions
- Reject zero or negative quantities
- Reject records with missing or invalid unit prices
- Ensure discount amounts are valid (>= 0 and <= gross revenue)
- Normalize dates to ISO format (YYYY-MM-DD)
- Track all exclusion reasons transparently without silently dropping records.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


class RecordValidationResult:
    def __init__(
        self,
        transaction_id: str,
        order_date: Optional[datetime.date],
        product: str,
        category: str,
        region: str,
        sales_channel: str,
        quantity: int,
        unit_price: Optional[float],
        discount_amount: float,
        gross_revenue: Optional[float],
        net_revenue: Optional[float],
        status: str,
        is_eligible: bool,
        exclusion_reasons: List[str],
    ):
        self.transaction_id = transaction_id
        self.order_date = order_date
        self.product = product
        self.category = category
        self.region = region
        self.sales_channel = sales_channel
        self.quantity = quantity
        self.unit_price = unit_price
        self.discount_amount = discount_amount
        self.gross_revenue = gross_revenue
        self.net_revenue = net_revenue
        self.status = status
        self.is_eligible = is_eligible
        self.exclusion_reasons = exclusion_reasons

    @property
    def exclusion_reason_str(self) -> Optional[str]:
        return "; ".join(self.exclusion_reasons) if self.exclusion_reasons else None


def parse_flexible_date(date_str: Any) -> Optional[datetime.date]:
    """
    Parses date strings across common business formats:
    - DD-MM-YYYY (e.g., 03-01-2026)
    - YYYY-MM-DD (e.g., 2026-01-03)
    - DD/MM/YYYY
    - YYYY/MM/DD
    """
    if not date_str:
        return None
    cleaned = str(date_str).strip()
    formats = ["%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def clean_and_validate_record(raw: Dict[str, Any]) -> RecordValidationResult:
    """
    Validates an individual raw transaction dictionary against the business eligibility policy.
    Returns a RecordValidationResult indicating whether it is eligible for sales KPIs
    and detailing any exclusion reasons.
    """
    reasons: List[str] = []

    # 1. Transaction ID
    raw_tid = str(raw.get("Transaction_Id", "")).strip()
    if not raw_tid:
        reasons.append("Missing Transaction_Id")

    # 2. Date parsing
    raw_date = raw.get("Order_date", "")
    parsed_date = parse_flexible_date(raw_date)
    if not parsed_date:
        reasons.append(f"Invalid or missing order date: '{raw_date}'")

    # 3. Categorical attributes
    product = str(raw.get("Product", "")).strip() or "Unknown Product"
    category = str(raw.get("Category", "")).strip() or "General"
    region = str(raw.get("Region", "")).strip() or "Unknown Region"
    sales_channel = str(raw.get("Sales_channel", "")).strip() or "Direct"

    # 4. Quantity validation
    raw_qty = raw.get("Quantity", "")
    quantity = 0
    try:
        quantity = int(str(raw_qty).strip())
        if quantity <= 0:
            reasons.append(f"Quantity must be positive; found {quantity}")
    except (ValueError, TypeError):
        reasons.append(f"Invalid non-integer quantity: '{raw_qty}'")

    # 5. Unit Price validation
    raw_price = raw.get("Unit_price", "")
    unit_price: Optional[float] = None
    if raw_price is None or str(raw_price).strip() == "":
        reasons.append("Missing unit price")
    else:
        try:
            val = float(str(raw_price).strip())
            if val <= 0:
                reasons.append(f"Unit price must be positive; found {val}")
            else:
                unit_price = val
        except ValueError:
            reasons.append(f"Invalid numerical unit price: '{raw_price}'")

    # 6. Discount Amount validation
    raw_discount = raw.get("Discount_amount", "0")
    discount_amount = 0.0
    try:
        d_val = float(str(raw_discount).strip() or "0")
        if d_val < 0:
            reasons.append(f"Discount amount cannot be negative; found {d_val}")
        else:
            discount_amount = d_val
    except ValueError:
        reasons.append(f"Invalid numerical discount amount: '{raw_discount}'")

    # 7. Status validation
    status = str(raw.get("Status", "")).strip()
    if not status:
        reasons.append("Missing transaction status")
    elif status.lower() == "returned":
        reasons.append("Status is 'Returned' (excluded from realized net revenue)")
    elif status.lower() != "completed":
        reasons.append(f"Status is '{status}' (only 'Completed' transactions realize revenue)")

    # 8. Revenue calculations
    gross_revenue: Optional[float] = None
    net_revenue: Optional[float] = None

    if unit_price is not None and quantity > 0:
        gross_revenue = round(quantity * unit_price, 2)
        if discount_amount > gross_revenue:
            reasons.append(
                f"Discount ({discount_amount}) exceeds gross revenue ({gross_revenue})"
            )
            net_revenue = 0.0
        else:
            net_revenue = round(gross_revenue - discount_amount, 2)

    is_eligible = len(reasons) == 0

    return RecordValidationResult(
        transaction_id=raw_tid,
        order_date=parsed_date,
        product=product,
        category=category,
        region=region,
        sales_channel=sales_channel,
        quantity=quantity,
        unit_price=unit_price,
        discount_amount=discount_amount,
        gross_revenue=gross_revenue,
        net_revenue=net_revenue,
        status=status,
        is_eligible=is_eligible,
        exclusion_reasons=reasons,
    )


# ======================================================================
# Phase 3 – Package C: Data Quality Index (DQI) & Ingestion Profiling
# ======================================================================

VALID_CATEGORIES = {"electronics", "office supplies", "furniture", "accessories"}
VALID_REGIONS = {"north", "south", "east", "west", "central"}
VALID_CHANNELS = {"online", "retail", "direct", "wholesale"}
VALID_STATUSES = {"completed", "returned", "pending", "cancelled"}

MANDATORY_FIELDS = [
    "Transaction_Id", "Order_date", "Product", "Category",
    "Region", "Sales_channel", "Quantity", "Unit_price",
    "Discount_amount", "Status"
]


def calculate_data_quality_index(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes a Multi-Dimensional Data Quality Index (DQI) score (0-100) across 5 dimensions:
    1. Completeness (25% weight): Ratio of populated mandatory fields.
    2. Validity (25% weight): Ratio of records with positive quantities, positive prices, valid status.
    3. Consistency (20% weight): Ratio of records with mathematically sound revenue & discount relations.
    4. Uniqueness (15% weight): Absence of duplicated transaction IDs.
    5. Timeliness / Recency (15% weight): Ratio of records with valid parseable dates within logical bounds.
    """
    total = len(records)
    if total == 0:
        return {
            "composite_dqi_score": 0.0,
            "dqi_grade": "Not Available (Empty Dataset)",
            "dimensions": {},
            "total_records": 0,
        }

    # 1. Completeness
    total_cells = total * len(MANDATORY_FIELDS)
    populated_cells = 0
    for r in records:
        for f in MANDATORY_FIELDS:
            val = None
            for k in r:
                if k.strip().lower() == f.lower():
                    val = r[k]
                    break
            if val is not None and str(val).strip() != "":
                populated_cells += 1
    completeness_score = round((populated_cells / total_cells) * 100.0, 2) if total_cells > 0 else 0.0

    # 2. Validity
    valid_count = 0
    for r in records:
        qty_val = None
        price_val = None
        disc_val = 0.0
        status_val = ""
        for k, v in r.items():
            kl = k.strip().lower()
            if kl == "quantity":
                qty_val = v
            elif kl == "unit_price":
                price_val = v
            elif kl == "discount_amount":
                disc_val = v
            elif kl == "status":
                status_val = str(v).strip().lower()

        try:
            q_ok = int(str(qty_val).strip()) > 0 if qty_val is not None else False
        except (ValueError, TypeError):
            q_ok = False

        try:
            p_ok = float(str(price_val).strip()) > 0 if price_val is not None else False
        except (ValueError, TypeError):
            p_ok = False

        try:
            d_ok = float(str(disc_val).strip() or "0") >= 0
        except (ValueError, TypeError):
            d_ok = False

        s_ok = status_val in VALID_STATUSES

        if q_ok and p_ok and d_ok and s_ok:
            valid_count += 1
    validity_score = round((valid_count / total) * 100.0, 2)

    # 3. Consistency
    consistent_count = 0
    for r in records:
        qty = 0
        price = 0.0
        disc = 0.0
        try:
            for k, v in r.items():
                kl = k.strip().lower()
                if kl == "quantity" and v is not None:
                    qty = int(str(v).strip())
                elif kl == "unit_price" and v is not None:
                    price = float(str(v).strip())
                elif kl == "discount_amount" and v is not None:
                    disc = float(str(v).strip() or "0")

            if qty > 0 and price > 0:
                gross = qty * price
                if disc <= gross and disc >= 0:
                    consistent_count += 1
            else:
                pass
        except Exception:
            pass
    consistency_score = round((consistent_count / total) * 100.0, 2)

    # 4. Uniqueness
    tids = []
    for r in records:
        for k, v in r.items():
            if k.strip().lower() == "transaction_id" and v is not None:
                tids.append(str(v).strip())
                break
    unique_ids_count = len(set(tids))
    uniqueness_score = round((unique_ids_count / total) * 100.0, 2)

    # 5. Timeliness / Recency
    dated_count = 0
    for r in records:
        for k, v in r.items():
            if k.strip().lower() in ("order_date", "date") and v:
                parsed = parse_flexible_date(v)
                if parsed and parsed.year >= 2020:
                    dated_count += 1
                break
    timeliness_score = round((dated_count / total) * 100.0, 2)

    # Weighted Composite DQI
    composite_dqi = round(
        (0.25 * completeness_score)
        + (0.25 * validity_score)
        + (0.20 * consistency_score)
        + (0.15 * uniqueness_score)
        + (0.15 * timeliness_score),
        2
    )

    if composite_dqi >= 95.0:
        grade = "Excellent (Production Grade)"
    elif composite_dqi >= 85.0:
        grade = "Good (Acceptable with Minor Governance Warnings)"
    elif composite_dqi >= 70.0:
        grade = "Fair (Remediation Required)"
    else:
        grade = "Poor (Critical Data Governance Risks)"

    return {
        "composite_dqi_score": composite_dqi,
        "dqi_grade": grade,
        "total_records_evaluated": total,
        "dimensions": {
            "completeness": {
                "score": completeness_score,
                "weight": 0.25,
                "description": "Presence of all mandatory transaction fields",
                "status": "PASS" if completeness_score >= 90.0 else "WARN",
            },
            "validity": {
                "score": validity_score,
                "weight": 0.25,
                "description": "Conformity to business domains (positive prices, positive quantities, valid statuses)",
                "status": "PASS" if validity_score >= 90.0 else "WARN",
            },
            "consistency": {
                "score": consistency_score,
                "weight": 0.20,
                "description": "Mathematical coherence across gross revenue, discounts, and net calculations",
                "status": "PASS" if consistency_score >= 90.0 else "WARN",
            },
            "uniqueness": {
                "score": uniqueness_score,
                "weight": 0.15,
                "description": "Absence of duplicate transaction identifiers",
                "status": "PASS" if uniqueness_score >= 99.0 else "WARN",
            },
            "timeliness": {
                "score": timeliness_score,
                "weight": 0.15,
                "description": "Chronological coherence and valid order dates",
                "status": "PASS" if timeliness_score >= 95.0 else "WARN",
            },
        },
    }


def profile_csv_dataset(raw_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Automated CSV Ingestion Profiling:
    Computes statistical and structural profiles for each column:
    data type, null count, distinct values, and range distributions.
    """
    if not raw_rows:
        return {"total_rows": 0, "columns": {}, "profiling_summary": "Empty dataset"}

    total_rows = len(raw_rows)
    all_keys = list(raw_rows[0].keys())
    columns_profile = {}

    for col in all_keys:
        values = [r.get(col) for r in raw_rows]
        non_null_values = [v for v in values if v is not None and str(v).strip() != ""]
        null_count = total_rows - len(non_null_values)
        null_pct = round((null_count / total_rows) * 100.0, 2)

        inferred_type = "string"
        int_count = 0
        float_count = 0
        date_count = 0
        numeric_vals = []

        for v in non_null_values:
            s_val = str(v).strip()
            try:
                int_val = int(s_val)
                int_count += 1
                numeric_vals.append(float(int_val))
                continue
            except ValueError:
                pass

            try:
                flt_val = float(s_val)
                float_count += 1
                numeric_vals.append(flt_val)
                continue
            except ValueError:
                pass

            if parse_flexible_date(s_val) is not None:
                date_count += 1
                continue

        nn_len = len(non_null_values)
        if nn_len > 0:
            if int_count / nn_len >= 0.8:
                inferred_type = "integer"
            elif (int_count + float_count) / nn_len >= 0.8:
                inferred_type = "float"
            elif date_count / nn_len >= 0.8:
                inferred_type = "date"
            else:
                inferred_type = "categorical/text"

        unique_vals = list(set(str(v).strip() for v in non_null_values))
        distinct_count = len(unique_vals)

        col_stat = {
            "column_name": col,
            "inferred_type": inferred_type,
            "total_count": total_rows,
            "populated_count": len(non_null_values),
            "null_count": null_count,
            "null_percentage": null_pct,
            "distinct_values_count": distinct_count,
            "sample_values": unique_vals[:3],
        }

        if numeric_vals:
            col_stat["min_value"] = round(min(numeric_vals), 2)
            col_stat["max_value"] = round(max(numeric_vals), 2)

        columns_profile[col] = col_stat

    dqi_results = calculate_data_quality_index(raw_rows)

    return {
        "total_rows": total_rows,
        "total_columns": len(all_keys),
        "columns_profile": columns_profile,
        "dqi": dqi_results,
    }
