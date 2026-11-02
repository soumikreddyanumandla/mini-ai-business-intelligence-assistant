"""
Test Suite for Phase 2 – Package B: Advanced Analytics
------------------------------------------------------
Validates:
1. IQR and Z-score anomaly detection (statistical outliers vs. confirmed DQ errors).
2. Pareto 80/20 revenue concentration with explicit denominator.
3. What-if revenue simulation with price, volume, and discount adjustments without cost invention.
4. Sales target and quota pacing distinguishing configured quota from empirical sales data.
5. REST API endpoints and RBAC protection (Analyst / Admin allowed; Viewer 403).
6. Tool registry execution and natural language query routing.
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import SalesTransaction
from backend.analytics import (
    detect_anomalies,
    get_pareto_revenue_concentration,
    simulate_what_if_revenue,
    get_sales_target_pacing,
    get_total_revenue,
)
from backend.tool_registry import registry
from backend.ai_service import ai_service
from backend.security import rate_limiter

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_limiter():
    rate_limiter.reset()
    yield
    rate_limiter.reset()


# ----------------------------------------------------------------------
# 1. Anomaly Detection Tests
# ----------------------------------------------------------------------

def test_detect_anomalies_distinguishes_statistical_from_dq_errors():
    """Anomaly detection must strictly separate statistical outliers from confirmed data quality errors."""
    db = SessionLocal()
    try:
        result = detect_anomalies(db, z_threshold=2.0)
        assert result["eligible_transactions_analyzed"] > 0
        assert "mean_transaction_revenue" in result
        assert "std_dev_revenue" in result
        assert "iqr" in result
        assert result["iqr_upper_bound"] > result["iqr_lower_bound"]

        # Statistical outliers checks
        assert isinstance(result["statistical_outliers"], list)
        for item in result["statistical_outliers"]:
            assert item["classification"] == "Statistical Outlier (Eligible Transaction)"
            assert "z_score" in item
            assert "outlier_methods" in item
            assert item["net_revenue"] > 0

        # Confirmed data quality errors checks
        assert isinstance(result["data_quality_errors"], list)
        assert result["confirmed_data_quality_errors_count"] == len(result["data_quality_errors"])
        for dq in result["data_quality_errors"]:
            assert dq["classification"] == "Confirmed Data Quality Error (Excluded Transaction)"
            assert "exclusion_reason" in dq

        # In baseline company dataset, 3 records are excluded (returned, zero-qty, missing price)
        assert result["confirmed_data_quality_errors_count"] == 3
    finally:
        db.close()


# ----------------------------------------------------------------------
# 2. Pareto 80/20 Revenue Concentration Tests
# ----------------------------------------------------------------------

def test_pareto_revenue_concentration_has_explicit_denominator():
    """Pareto calculation must state the exact net revenue denominator and vital few cohort."""
    db = SessionLocal()
    try:
        tot_rev = get_total_revenue(db)
        expected_denominator = tot_rev["total_net_revenue"]

        result = get_pareto_revenue_concentration(db, top_pct_cutoff=80.0)
        assert result["total_products"] > 0
        assert result["vital_few_count"] > 0
        assert result["denominator_total_eligible_net_revenue"] == expected_denominator
        assert "Total Realized Net Revenue" in result["denominator_description"]

        # Vital few products must generate approx 80% or more of net revenue
        assert result["vital_revenue_share_percentage"] >= 75.0
        assert 0 < result["vital_few_product_percentage"] <= 100.0

        # Verify ranking structure
        ranking = result["ranking"]
        assert len(ranking) == result["total_products"]
        for idx, item in enumerate(ranking, start=1):
            assert item["rank"] == idx
            assert "product" in item
            assert "net_revenue" in item
            assert "cumulative_share_percentage" in item
            if item["rank"] <= result["vital_few_count"]:
                assert item["in_vital_80_cohort"] is True
    finally:
        db.close()


# ----------------------------------------------------------------------
# 3. What-If Revenue Simulation Tests
# ----------------------------------------------------------------------

def test_what_if_simulation_zero_change_matches_baseline():
    """A 0% change scenario should produce identical simulated and baseline revenue."""
    db = SessionLocal()
    try:
        tot_rev = get_total_revenue(db)
        result = simulate_what_if_revenue(db, price_change_pct=0.0, volume_change_pct=0.0, discount_adjustment_pct=0.0)
        assert result["baseline_net_revenue"] == tot_rev["total_net_revenue"]
        assert result["simulated_net_revenue"] == tot_rev["total_net_revenue"]
        assert result["net_revenue_delta"] == 0.0
        assert result["net_revenue_delta_percentage"] == 0.0
        # Must include cost disclaimer
        assert "Technical Notice" in result["cost_model_disclaimer"]
    finally:
        db.close()


def test_what_if_simulation_price_and_volume_adjustments():
    """Tests +10% price increase and -5% volume change."""
    db = SessionLocal()
    try:
        result = simulate_what_if_revenue(
            db,
            price_change_pct=10.0,
            volume_change_pct=-5.0,
            discount_adjustment_pct=0.0,
        )
        # Price +10% and Volume -5% -> Net multiplier approx 1.10 * 0.95 = 1.045 (+4.5% gross)
        assert result["simulated_net_revenue"] > result["baseline_net_revenue"]
        assert result["net_revenue_delta"] > 0
        assert result["net_revenue_delta_percentage"] > 0
        assert len(result["product_breakdown"]) > 0
    finally:
        db.close()


def test_what_if_simulation_filtered_by_category():
    """Tests simulation filtered by a specific category (e.g. 'Electronics')."""
    db = SessionLocal()
    try:
        result = simulate_what_if_revenue(
            db,
            price_change_pct=15.0,
            volume_change_pct=0.0,
            discount_adjustment_pct=0.0,
            category="Electronics",
        )
        assert result["baseline_net_revenue"] > 0
        assert result["simulated_net_revenue"] > result["baseline_net_revenue"]
        assert result["scenario_parameters"]["category_filter"] == "Electronics"
    finally:
        db.close()


# ----------------------------------------------------------------------
# 4. Sales Target and Quota Pacing Tests
# ----------------------------------------------------------------------

def test_sales_target_pacing_distinguishes_target_from_empirical():
    """Quota pacing must clearly differentiate configured quota from actual database sales."""
    db = SessionLocal()
    try:
        target_amount = 600000.0
        result = get_sales_target_pacing(db, monthly_target=target_amount)

        # Configured target verification
        conf = result["configured_target"]
        assert conf["amount"] == target_amount
        assert "Configured Business Target" in conf["source"]

        # Empirical actuals verification
        emp = result["empirical_actuals"]
        assert emp["actual_revenue"] > 0
        assert "Empirical SQLite Database" in emp["source"]

        # Pacing metrics verification
        pacing = result["pacing_metrics"]
        assert pacing["attainment_percentage"] == round((emp["actual_revenue"] / target_amount) * 100.0, 2)
        assert pacing["run_rate_projected_revenue"] > 0
        assert pacing["status"] in ("Ahead of Pace", "On Track", "Behind Pace")
    finally:
        db.close()


# ----------------------------------------------------------------------
# 5. REST API Endpoints and RBAC Protection Tests
# ----------------------------------------------------------------------

def test_advanced_analytics_endpoints_rbac():
    """Endpoints must require Analyst or Admin role (Viewer role rejected with 403)."""
    endpoints = [
        ("GET", "/api/analytics/anomalies", None),
        ("GET", "/api/analytics/pareto", None),
        ("POST", "/api/analytics/what-if", {"price_change_pct": 5.0}),
        ("GET", "/api/analytics/quota-pacing", None),
    ]

    for method, path, body in endpoints:
        # Viewer role -> 403 Forbidden
        if method == "GET":
            res_viewer = client.get(path, headers={"X-User-Role": "Viewer"})
        else:
            res_viewer = client.post(path, json=body or {}, headers={"X-User-Role": "Viewer"})
        assert res_viewer.status_code == 403, f"{path} did not reject Viewer"

        # Analyst role -> 200 OK
        if method == "GET":
            res_analyst = client.get(path, headers={"X-User-Role": "Analyst"})
        else:
            res_analyst = client.post(path, json=body or {}, headers={"X-User-Role": "Analyst"})
        assert res_analyst.status_code == 200, f"{path} did not allow Analyst"
        assert "title" in res_analyst.json()


# ----------------------------------------------------------------------
# 6. Tool Registry and AI Execution Tests
# ----------------------------------------------------------------------

def test_package_b_tools_registered_and_executable():
    """All 4 new tools must be registered and executable via ToolRegistry."""
    db = SessionLocal()
    try:
        # 1. anomaly_detection
        res_anom = registry.execute("anomaly_detection", db=db)
        assert "statistical_outliers" in res_anom

        # 2. revenue_concentration
        res_pareto = registry.execute("revenue_concentration", db=db)
        assert "vital_few_count" in res_pareto

        # 3. what_if_simulation
        res_sim = registry.execute("what_if_simulation", db=db, params={"price_change_pct": 10.0})
        assert "simulated_net_revenue" in res_sim

        # 4. quota_pacing
        res_pacing = registry.execute("quota_pacing", db=db, params={"monthly_target": 400000.0})
        assert "pacing_metrics" in res_pacing
    finally:
        db.close()


def test_ai_fallback_routes_package_b_questions():
    """Simulates conversational questions for Package B tools through ai_service."""
    db = SessionLocal()
    try:
        queries = [
            ("Show sales anomalies and outliers.", "anomaly_detection"),
            ("What is our Pareto 80/20 revenue concentration?", "revenue_concentration"),
            ("What if prices increase by 10%?", "what_if_simulation"),
            ("What is our sales quota pacing for target 500000?", "quota_pacing"),
        ]
        for q, expected_intent in queries:
            response = ai_service.process_query(q, db=db, session_id="test_pkg_b")
            assert response.success is True
            assert response.intent == expected_intent, f"Query '{q}' routed to '{response.intent}' instead of '{expected_intent}'"
            assert response.answer is not None
            assert len(response.answer) > 10
    finally:
        db.close()
