"""
Unit & Integration Tests for Role-Based Access Control (RBAC) & Auth
---------------------------------------------------------------------
Validates user login, password hashing, and endpoint authorization guards
(Admin, Analyst, Viewer).
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.auth import authenticate_user, UserCredentials, USERS_DATABASE

client = TestClient(app)


def test_authenticate_user_valid_credentials():
    """Verifies that all three demo accounts authenticate successfully."""
    for uname, pwd, exp_role in [
        ("admin", "Admin@123", "Admin"),
        ("analyst", "Analyst@123", "Analyst"),
        ("viewer", "Viewer@123", "Viewer"),
    ]:
        res = authenticate_user(UserCredentials(username=uname, password=pwd))
        assert res is not None
        assert res["role"] == exp_role
        assert res["access_token"].startswith("token_")


def test_authenticate_user_invalid_password():
    """Verifies that incorrect password returns None."""
    res = authenticate_user(UserCredentials(username="admin", password="WrongPassword!"))
    assert res is None


def test_api_login_endpoint_success():
    """Tests POST /api/auth/login endpoint with valid credentials."""
    response = client.post(
        "/api/auth/login",
        json={"username": "analyst", "password": "Analyst@123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "Analyst"
    assert "access_token" in data
    assert "export:pdf" in data["permissions"]


def test_api_login_endpoint_failure():
    """Tests POST /api/auth/login endpoint with invalid credentials."""
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "BadPassword"},
    )
    assert response.status_code == 401
    assert "Invalid username" in response.json()["detail"]


def test_viewer_role_forbidden_from_asking():
    """Verifies that Viewer role cannot post queries to /api/ask (403 Forbidden)."""
    response = client.post(
        "/api/ask",
        json={"question": "Total revenue?"},
        headers={"X-User-Role": "Viewer"},
    )
    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]


def test_analyst_role_forbidden_from_dataset_reset():
    """Verifies that Analyst role cannot reset dataset (403 Forbidden)."""
    response = client.post(
        "/api/dataset/reset",
        headers={"X-User-Role": "Analyst"},
    )
    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]


def test_analyst_role_forbidden_from_csv_upload():
    """Verifies that Analyst role cannot upload CSV (403 Forbidden)."""
    csv_bytes = b"Transaction_Id,Order_date,Product,Category,Region,Sales_channel,Quantity,Unit_price,Discount_amount,Status\n"
    response = client.post(
        "/api/upload",
        files={"file": ("test.csv", csv_bytes, "text/csv")},
        headers={"X-User-Role": "Analyst"},
    )
    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]


def test_admin_role_allowed_for_all_endpoints():
    """Verifies that Admin role can access protected endpoints."""
    # Admin can ask
    ask_res = client.post(
        "/api/ask",
        json={"question": "Total revenue?"},
        headers={"X-User-Role": "Admin"},
    )
    assert ask_res.status_code == 200

    # Admin can export PDF
    pdf_res = client.get(
        "/api/export/pdf",
        headers={"X-User-Role": "Admin"},
    )
    assert pdf_res.status_code == 200


def test_default_role_backward_compatibility():
    """Verifies that requests without headers default to Admin for local dev/testing."""
    response = client.post(
        "/api/ask",
        json={"question": "Total revenue?"},
    )
    assert response.status_code == 200


def test_analyst_forbidden_from_viewing_updating_deleting_llm_key():
    """Verifies Analyst role cannot view, update, or delete centralized Gemini API key (403 Forbidden)."""
    # 1. Analyst cannot view configuration
    get_res = client.get("/api/config/llm", headers={"X-User-Role": "Analyst"})
    assert get_res.status_code == 403
    assert "Access denied" in get_res.json()["detail"]

    # 2. Analyst cannot update key
    post_res = client.post(
        "/api/config/llm",
        json={"provider": "gemini", "api_key": "some_key"},
        headers={"X-User-Role": "Analyst"},
    )
    assert post_res.status_code == 403
    assert "Access denied" in post_res.json()["detail"]

    # 3. Analyst cannot delete key
    del_res = client.delete("/api/config/llm", headers={"X-User-Role": "Analyst"})
    assert del_res.status_code == 403
    assert "Access denied" in del_res.json()["detail"]


def test_viewer_forbidden_from_viewing_updating_deleting_llm_key():
    """Verifies Viewer role cannot view, update, or delete centralized Gemini API key (403 Forbidden)."""
    # 1. Viewer cannot view configuration
    get_res = client.get("/api/config/llm", headers={"X-User-Role": "Viewer"})
    assert get_res.status_code == 403
    assert "Access denied" in get_res.json()["detail"]

    # 2. Viewer cannot update key
    post_res = client.post(
        "/api/config/llm",
        json={"provider": "gemini", "api_key": "some_key"},
        headers={"X-User-Role": "Viewer"},
    )
    assert post_res.status_code == 403
    assert "Access denied" in post_res.json()["detail"]

    # 3. Viewer cannot delete key
    del_res = client.delete("/api/config/llm", headers={"X-User-Role": "Viewer"})
    assert del_res.status_code == 403
    assert "Access denied" in del_res.json()["detail"]


def test_admin_llm_config_operations_and_masked_key():
    """Verifies Admin role can inspect configuration and sees only masked key preview."""
    res = client.get("/api/config/llm", headers={"X-User-Role": "Admin"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "provider" in data
    assert "status" in data
    assert "fallback_active" in data
    # Raw key is never exposed
    assert "api_key" not in data
    if data["is_key_configured"] and data["masked_key"]:
        # Ensure it is masked (e.g., AQ.Ab...J7KA) and does not reveal full string
        assert "..." in data["masked_key"]
        assert len(data["masked_key"]) <= 15


def test_public_llm_status_endpoint_all_roles():
    """Verifies that Admin, Analyst, and Viewer can all query public LLM status without leaking secrets."""
    for role in ["Admin", "Analyst", "Viewer"]:
        res = client.get("/api/llm/status", headers={"X-User-Role": role})
        assert res.status_code == 200
        data = res.json()
        assert "provider" in data
        assert "status" in data
        assert "status_description" in data
        assert "fallback_active" in data
        assert "is_key_configured" in data
        # Absolute security guarantee: raw key and masked key are never present in public status
        assert "api_key" not in data
        assert "masked_key" not in data


def test_analyst_can_ask_queries_without_entering_key():
    """Verifies Analyst can execute natural-language queries using centralized configuration."""
    response = client.post(
        "/api/ask",
        json={"question": "What is the total revenue?"},
        headers={"X-User-Role": "Analyst"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "1,439,200.00" in data["answer"]
    assert data["metrics"]["total_net_revenue"] == 1439200.0

