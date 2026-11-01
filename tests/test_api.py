"""
Automated Tests for FastAPI Endpoints and API Security
------------------------------------------------------
Validates:
- Health checking and dashboard KPI serialization
- /api/ask endpoint behavior across valid, empty, and edge queries
- SQL injection resistance
- Pydantic request validation and HTTP status codes.
"""

import pytest


def test_health_check_endpoint(client):
    """Test 1: GET /api/health returns HTTP 200 with database connectivity."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database_connected"] is True


def test_dashboard_endpoint(client):
    """Test 2: GET /api/dashboard returns correct numerical KPIs."""
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    data = response.json()
    assert data["total_net_revenue"] == 1439200.0
    assert data["total_gross_revenue"] == 1443700.0
    assert data["eligible_transactions"] == 48
    assert data["excluded_transactions"] == 3


def test_analytics_endpoints(client):
    """Test 3: Analytical sub-endpoints return structured arrays."""
    endpoints = [
        "/api/analytics/products",
        "/api/analytics/regions",
        "/api/analytics/monthly",
        "/api/analytics/categories",
        "/api/analytics/channels",
    ]
    for ep in endpoints:
        res = client.get(ep)
        assert res.status_code == 200
        assert isinstance(res.json(), dict)


def test_data_quality_endpoint(client):
    """Test 4: GET /api/data-quality reports audit counts and excluded records."""
    response = client.get("/api/data-quality")
    assert response.status_code == 200
    data = response.json()
    assert data["total_records"] == 51
    assert data["eligible_records"] == 48
    assert data["excluded_records"] == 3
    assert data["cleanliness_percentage"] == 94.12
    assert len(data["excluded_transactions"]) == 3


def test_ask_valid_query(client):
    """Test 5: POST /api/ask returns structured answer and supporting figures."""
    payload = {"question": "What is the total revenue?"}
    response = client.post("/api/ask", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["intent"] == "total_revenue"
    assert data["metrics"]["total_net_revenue"] == 1439200.0


def test_ask_empty_query_validation(client):
    """Test 6: POST /api/ask with empty question fails validation (HTTP 422)."""
    payload = {"question": ""}
    response = client.post("/api/ask", json=payload)
    assert response.status_code == 422


def test_ask_whitespace_only_validation(client):
    """Test 7: POST /api/ask with whitespace-only question fails validation."""
    payload = {"question": "    "}
    response = client.post("/api/ask", json=payload)
    assert response.status_code == 422


def test_sql_injection_defense(client, db_session):
    """Test 8: Ensure malicious SQL payloads cannot execute or corrupt tables."""
    injection_payload = "What is total revenue'; DROP TABLE sales_transactions; --"
    response = client.post("/api/ask", json={"question": injection_payload})
    assert response.status_code == 200
    
    # Verify sales_transactions table is intact
    from backend.models import SalesTransaction
    count = db_session.query(SalesTransaction).count()
    assert count == 51


def test_suggestions_endpoint(client):
    """Test 9: GET /api/suggestions returns pre-configured query chips."""
    response = client.get("/api/suggestions")
    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 5
    assert any(item["question"] == "What is the total revenue?" for item in items)


def test_config_llm_validation(client):
    """Test 10: POST /api/config/llm with invalid key returns HTTP 400."""
    response = client.post("/api/config/llm", json={
        "provider": "gemini",
        "api_key": "invalid_test_key_123",
        "model": "gemini-1.5-flash"
    })
    assert response.status_code == 400
    assert "Failed to connect" in response.json()["detail"]


def test_upload_csv_missing_columns_fails(client):
    """Test 11: Uploading a CSV missing required columns returns HTTP 422."""
    bad_csv = "Transaction_Id,Order_date,Product\nTXN9999,01-01-2026,Mouse"
    files = {"file": ("test_missing.csv", bad_csv.encode("utf-8"), "text/csv")}
    response = client.post("/api/upload", files=files)
    assert response.status_code == 422
    assert "Missing required column" in response.json()["detail"]


def test_upload_csv_duplicate_detection(client):
    """Test 12: Uploading CSV with duplicates correctly tags duplicate transaction IDs."""
    csv_content = (
        "Transaction_Id,Order_date,Product,Category,Region,Sales_channel,Quantity,Unit_price,Discount_amount,Status\n"
        "TXN001,01-01-2026,Monitor,Electronics,North,Online,2,5000,0,Completed\n"
        "TXN001,01-01-2026,Monitor,Electronics,North,Online,2,5000,0,Completed\n"
    )
    files = {"file": ("test_dups.csv", csv_content.encode("utf-8"), "text/csv")}
    response = client.post("/api/upload", files=files)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["summary"]["duplicate_count"] == 1
    assert data["summary"]["eligible_count"] == 1
    assert data["summary"]["excluded_count"] == 1


def test_dataset_reset_endpoint(client):
    """Test 13: POST /api/dataset/reset restores the original company dataset."""
    response = client.post("/api/dataset/reset")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["summary"]["total_imported"] == 51
    assert data["summary"]["eligible_count"] == 48
    assert data["summary"]["excluded_count"] == 3


def test_verify_llm_endpoint(client):
    """Test 14: POST /api/config/llm/verify re-probes connectivity and returns AdminLLMConfigResponse."""
    response = client.post("/api/config/llm/verify", headers={"X-User-Role": "Admin"})
    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "status" in data
    assert "fallback_active" in data


def test_simulate_outage_endpoint_flow(client, monkeypatch):
    """Test 15: Simulates outage via API, verifies fallback activation, and restores connectivity."""
    from backend.config import settings
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")

    # 1. Activate simulated outage
    sim_res = client.post(
        "/api/config/llm/simulate-outage?enabled=true&reason=Simulated+Test+Timeout",
        headers={"X-User-Role": "Admin"},
    )
    assert sim_res.status_code == 200
    assert sim_res.json()["status"] == "temporarily_unavailable"
    assert sim_res.json()["fallback_active"] is True

    # 2. Check public status reflects fallback_active == True
    status_res = client.get("/api/llm/status", headers={"X-User-Role": "Analyst"})
    assert status_res.status_code == 200
    assert status_res.json()["fallback_active"] is True
    assert status_res.json()["status"] == "temporarily_unavailable"

    # 3. Question processed via fallback rule during outage
    ask_res = client.post(
        "/api/ask",
        json={"question": "What is the total revenue?"},
        headers={"X-User-Role": "Analyst"},
    )
    assert ask_res.status_code == 200
    assert ask_res.json()["ai_mode"] == "fallback_rule"
    assert "1,439,200.00" in ask_res.json()["answer"]

    # 4. Deactivate simulated outage
    restore_res = client.post(
        "/api/config/llm/simulate-outage?enabled=false",
        headers={"X-User-Role": "Admin"},
    )
    assert restore_res.status_code == 200
    assert restore_res.json()["status"] == "verified"
    assert restore_res.json()["fallback_active"] is False

