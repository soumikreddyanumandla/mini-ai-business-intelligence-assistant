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
