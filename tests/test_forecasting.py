"""
Unit & Integration Tests for Sales Forecasting Module
------------------------------------------------------
Validates time-series model fitting, out-of-sample evaluation metrics,
confidence intervals, and epistemic disclosures.
"""

import pytest
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.forecasting import generate_sales_forecast


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_sales_forecast_structure(db_session: Session):
    """Verifies that the forecast payload contains all required sections."""
    res = generate_sales_forecast(db_session, forecast_horizon=3)
    assert res["status"] == "success"
    assert res["historical_observations_count"] == 6
    assert res["recommended_model"] in ["Linear Regression", "Holt's Linear Trend"]
    assert "evaluation_metrics" in res
    assert "forecast_projections" in res
    assert "scientific_disclosures" in res


def test_forecast_horizon_length(db_session: Session):
    """Tests that the number of projected points matches the requested horizon."""
    for h in [1, 3, 5]:
        res = generate_sales_forecast(db_session, forecast_horizon=h)
        assert len(res["forecast_projections"]) == h


def test_out_of_sample_metrics_validity(db_session: Session):
    """Verifies that out-of-sample evaluation metrics are non-negative and finite."""
    res = generate_sales_forecast(db_session, forecast_horizon=3)
    metrics = res["evaluation_metrics"]
    
    for model_name in ["linear_regression", "holts_exponential_smoothing"]:
        m = metrics[model_name]
        assert m["mae"] >= 0.0
        assert m["rmse"] >= 0.0
        assert m["mape"] >= 0.0
        # RMSE is mathematically >= MAE (Cauchy-Schwarz inequality)
        assert m["rmse"] >= m["mae"] or abs(m["rmse"] - m["mae"]) < 1e-5


def test_confidence_interval_bounds(db_session: Session):
    """Verifies statistical consistency: CI_95_lower <= CI_80_lower <= Projected <= CI_80_upper <= CI_95_upper."""
    res = generate_sales_forecast(db_session, forecast_horizon=3)
    for p in res["forecast_projections"]:
        proj = p["projected_revenue"]
        ci80_l = p["ci_80_lower"]
        ci80_u = p["ci_80_upper"]
        ci95_l = p["ci_95_lower"]
        ci95_u = p["ci_95_upper"]
        
        assert ci95_l <= ci80_l <= proj <= ci80_u <= ci95_u


def test_scientific_disclosures_present(db_session: Session):
    """Ensures honesty regarding sample size and seasonality limitations."""
    res = generate_sales_forecast(db_session, forecast_horizon=3)
    disclosures = res["scientific_disclosures"]
    assert "sample_size_limitation" in disclosures
    assert "seasonality_limitation" in disclosures
    assert "stationarity_assumption" in disclosures
    assert "interview_defense_note" in disclosures
