"""
Test Suite for Phase 3 – Package C: Data Intelligence and Provenance
---------------------------------------------------------------------
Validates:
1. Multi-dimensional Data Quality Index (DQI) across 5 standard dimensions.
2. Automated CSV ingestion profiling (inferred types, null counts, min/max distributions).
3. Data quality reporting API integration (/api/data-quality).
4. Source provenance metadata in AI responses (/api/ask).
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import SalesTransaction, DataQualityLog
from backend.data_cleaning import (
    calculate_data_quality_index,
    profile_csv_dataset,
)
from backend.data_loader import load_and_sync_csv_to_db
from backend.security import rate_limiter

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_limiter():
    rate_limiter.reset()
    yield
    rate_limiter.reset()


# ----------------------------------------------------------------------
# 1. Multi-Dimensional Data Quality Index (DQI) Tests
# ----------------------------------------------------------------------

def test_calculate_dqi_all_five_dimensions():
    """Validates that DQI computes all 5 dimensions and outputs a weighted composite score."""
    sample_records = [
        {
            "Transaction_Id": "TXN_001",
            "Order_date": "2026-01-05",
            "Product": "Monitor",
            "Category": "Electronics",
            "Region": "North",
            "Sales_channel": "Online",
            "Quantity": "2",
            "Unit_price": "15000.00",
            "Discount_amount": "500.00",
            "Status": "Completed",
        },
        {
            "Transaction_Id": "TXN_002",
            "Order_date": "2026-01-06",
            "Product": "Desk",
            "Category": "Furniture",
            "Region": "South",
            "Sales_channel": "Retail",
            "Quantity": "1",
            "Unit_price": "8000.00",
            "Discount_amount": "0.00",
            "Status": "Completed",
        },
    ]

    dqi_res = calculate_data_quality_index(sample_records)
    assert "composite_dqi_score" in dqi_res
    assert dqi_res["composite_dqi_score"] == 100.0
    assert "Excellent" in dqi_res["dqi_grade"]

    dims = dqi_res["dimensions"]
    assert "completeness" in dims
    assert "validity" in dims
    assert "consistency" in dims
    assert "uniqueness" in dims
    assert "timeliness" in dims

    # Verify dimension weights sum to 1.0
    weights_sum = sum(d["weight"] for d in dims.values())
    assert round(weights_sum, 2) == 1.0


def test_calculate_dqi_penalizes_dirty_data():
    """Dirty data with missing prices, negative discounts, or invalid status should reduce DQI."""
    dirty_records = [
        {
            "Transaction_Id": "TXN_BAD_1",
            "Order_date": "invalid-date",
            "Product": "Monitor",
            "Category": "Electronics",
            "Region": "North",
            "Sales_channel": "Online",
            "Quantity": "-5",            # Invalid
            "Unit_price": "",             # Incomplete & invalid
            "Discount_amount": "-100",    # Inconsistent
            "Status": "UnknownStatus",    # Invalid status
        },
    ]
    dqi_res = calculate_data_quality_index(dirty_records)
    assert dqi_res["composite_dqi_score"] < 50.0
    assert "Poor" in dqi_res["dqi_grade"]


# ----------------------------------------------------------------------
# 2. Automated CSV Ingestion Profiling Tests
# ----------------------------------------------------------------------

def test_profile_csv_dataset_columns():
    """CSV profiling must infer column data types, null rates, and distribution ranges."""
    sample_rows = [
        {"Transaction_Id": "T1", "Order_date": "2026-02-01", "Quantity": "5", "Unit_price": "250.00"},
        {"Transaction_Id": "T2", "Order_date": "2026-02-02", "Quantity": "10", "Unit_price": "500.00"},
    ]
    profile = profile_csv_dataset(sample_rows)
    assert profile["total_rows"] == 2
    assert profile["total_columns"] == 4

    col_prof = profile["columns_profile"]
    assert col_prof["Quantity"]["inferred_type"] == "integer"
    assert col_prof["Quantity"]["min_value"] == 5.0
    assert col_prof["Quantity"]["max_value"] == 10.0
    assert col_prof["Unit_price"]["inferred_type"] in ("float", "integer")
    assert col_prof["Order_date"]["inferred_type"] == "date"
    assert "dqi" in profile


def test_load_and_sync_includes_dqi_and_profiling():
    """load_and_sync_csv_to_db must compute and return DQI and profiling metadata."""
    db = SessionLocal()
    try:
        summary = load_and_sync_csv_to_db(db=db, replace_existing=True)
        assert "dqi" in summary
        assert "composite_dqi_score" in summary["dqi"]
        assert summary["dqi"]["composite_dqi_score"] >= 90.0
        assert "profiling" in summary
        assert len(summary["profiling"]) >= 10

        # Verify DataQualityLog contains DQI audit notes
        log_entry = (
            db.query(DataQualityLog)
            .order_by(DataQualityLog.import_timestamp.desc())
            .first()
        )
        assert log_entry is not None
        assert "dqi_score" in log_entry.notes
        assert "dqi_grade" in log_entry.notes
    finally:
        db.close()


# ----------------------------------------------------------------------
# 3. Data Quality API Endpoint Tests
# ----------------------------------------------------------------------

def test_api_data_quality_endpoint_contains_dqi_dimensions():
    """GET /api/data-quality must return DQI score, grade, dimensions, and profiling."""
    res = client.get("/api/data-quality")
    assert res.status_code == 200
    data = res.json()
    assert data["dqi_score"] is not None
    assert data["dqi_score"] > 80.0
    assert data["dqi_grade"] is not None
    assert "dimensions" in data and data["dimensions"] is not None
    assert "completeness" in data["dimensions"]
    assert "profiling" in data and data["profiling"] is not None


# ----------------------------------------------------------------------
# 4. Source Provenance Metadata in AI Responses Tests
# ----------------------------------------------------------------------

def test_ai_response_includes_provenance_metadata():
    """Calling /api/ask must return comprehensive source provenance metadata."""
    headers = {"X-User-Role": "Analyst"}
    payload = {"question": "What is the total revenue?"}
    res = client.post("/api/ask", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True

    # Check provenance dictionary
    prov = data.get("provenance")
    assert prov is not None, "Provenance metadata missing from QueryResponse"
    assert "operation" in prov
    assert prov["target_entity"] == "sales_transactions"
    assert prov["eligible_rows_used"] > 0
    assert prov["excluded_rows_omitted"] >= 0
    assert "timestamp" in prov
    assert "deterministic_guarantee" in prov

    # Security check: Provenance must NEVER expose unrestricted raw SQL strings
    raw_text = str(prov)
    assert "DROP TABLE" not in raw_text
    assert "DELETE FROM" not in raw_text
