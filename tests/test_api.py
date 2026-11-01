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
