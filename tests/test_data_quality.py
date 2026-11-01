"""
Automated Tests for Data Quality and Business Eligibility
----------------------------------------------------------
Tests the data cleaning policy:
- Exclusion of 'Returned' transactions from realized revenue
- Exclusion of transactions with zero or negative quantities
- Exclusion of transactions with missing/empty unit prices
- Handling of duplicate transaction IDs
- Rejection of invalid dates.
"""

from datetime import date
import pytest
from backend.data_cleaning import clean_and_validate_record, parse_flexible_date
from backend.models import SalesTransaction


def test_returned_status_exclusion():
    """Test 1: Verify Status == 'Returned' is excluded from realized sales."""
    raw = {
        "Transaction_Id": "TXN0033",
        "Order_date": "26-04-2026",
        "Product": "Monitor",
        "Category": "Electronics",
        "Region": "West",
        "Sales_channel": "Retail",
        "Quantity": "2",
        "Unit_price": "9500",
        "Discount_amount": "0",
        "Status": "Returned",
    }
    res = clean_and_validate_record(raw)
    assert res.is_eligible is False
    assert any("Returned" in r for r in res.exclusion_reasons)


def test_zero_quantity_handling():
    """Test 2: Verify zero quantity is flagged as invalid/suspicious."""
    raw = {
        "Transaction_Id": "TXN0034",
        "Order_date": "28-04-2026",
        "Product": "Keyboard",
        "Category": "Accessories",
        "Region": "East",
        "Sales_channel": "Online",
        "Quantity": "0",
        "Unit_price": "900",
        "Discount_amount": "0",
        "Status": "Completed",
    }
    res = clean_and_validate_record(raw)
    assert res.is_eligible is False
    assert any("Quantity must be positive" in r for r in res.exclusion_reasons)


def test_negative_quantity_handling():
    """Test 3: Verify negative quantity is rejected."""
    raw = {
        "Transaction_Id": "TXN_NEG",
        "Order_date": "10-05-2026",
        "Product": "Desk",
        "Category": "Furniture",
        "Region": "North",
        "Sales_channel": "Online",
        "Quantity": "-5",
        "Unit_price": "12500",
        "Discount_amount": "0",
        "Status": "Completed",
    }
    res = clean_and_validate_record(raw)
    assert res.is_eligible is False
    assert any("Quantity must be positive" in r for r in res.exclusion_reasons)


def test_missing_unit_price_handling():
    """Test 4: Verify missing or blank unit price is excluded."""
    raw = {
        "Transaction_Id": "TXN0051",
        "Order_date": "28-06-2026",
        "Product": "Laptop Stand",
        "Category": "Accessories",
        "Region": "East",
        "Sales_channel": "Online",
        "Quantity": "5",
        "Unit_price": "",
        "Discount_amount": "0",
        "Status": "Completed",
    }
    res = clean_and_validate_record(raw)
    assert res.is_eligible is False
    assert any("Missing unit price" in r for r in res.exclusion_reasons)
    assert res.unit_price is None


def test_invalid_date_parsing():
    """Test 5: Verify invalid date strings are rejected."""
    raw = {
        "Transaction_Id": "TXN_DATE",
        "Order_date": "invalid-date-string",
        "Product": "Mouse",
        "Category": "Accessories",
        "Region": "North",
        "Sales_channel": "Retail",
        "Quantity": "10",
        "Unit_price": "500",
        "Discount_amount": "0",
        "Status": "Completed",
    }
    res = clean_and_validate_record(raw)
    assert res.is_eligible is False
    assert any("Invalid or missing order date" in r for r in res.exclusion_reasons)


def test_valid_transaction_calculation():
    """Test 6: Verify valid completed transaction gross and net revenue."""
    raw = {
        "Transaction_Id": "TXN0004",
        "Order_date": "12-01-2026",
        "Product": "Monitor",
        "Category": "Electronics",
        "Region": "East",
        "Sales_channel": "Retail",
        "Quantity": "6",
        "Unit_price": "9500",
        "Discount_amount": "500",
        "Status": "Completed",
    }
    res = clean_and_validate_record(raw)
    assert res.is_eligible is True
    assert res.order_date == date(2026, 1, 12)
    assert res.gross_revenue == 57000.0  # 6 * 9500
    assert res.net_revenue == 56500.0    # 57000 - 500
    assert len(res.exclusion_reasons) == 0


def test_database_audit_record_counts(db_session):
    """Test 7: Verify database retains all 51 rows while marking exactly 3 as ineligible."""
    total = db_session.query(SalesTransaction).count()
    eligible = db_session.query(SalesTransaction).filter(SalesTransaction.is_eligible == True).count()
    excluded = db_session.query(SalesTransaction).filter(SalesTransaction.is_eligible == False).count()
    
    assert total == 51
    assert eligible == 48
    assert excluded == 3

    # Verify the 3 excluded IDs specifically
    excluded_ids = {
        r.transaction_id
        for r in db_session.query(SalesTransaction.transaction_id).filter(SalesTransaction.is_eligible == False).all()
    }
    assert excluded_ids == {"TXN0033", "TXN0034", "TXN0051"}
