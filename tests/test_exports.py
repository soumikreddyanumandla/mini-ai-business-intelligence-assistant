"""
Unit & Integration Tests for PDF and CSV Report Exporters
---------------------------------------------------------
Validates ReportLab executive PDF generation, transactions CSV exports,
and aggregated analytical CSV downloads.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.main import app
from backend.database import SessionLocal
from backend.report_exporter import (
    generate_executive_pdf_report,
    generate_transactions_csv_export,
    generate_analytics_summary_csv,
)

client = TestClient(app)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_generate_executive_pdf_binary(db_session: Session):
    """Verifies that generate_executive_pdf_report returns valid non-empty PDF bytes starting with %PDF."""
    pdf_bytes = generate_executive_pdf_report(db_session)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF")


def test_generate_transactions_csv(db_session: Session):
    """Verifies that generate_transactions_csv_export contains header and all 51 transaction records."""
    csv_str = generate_transactions_csv_export(db_session)
    lines = [line for line in csv_str.strip().split("\n") if line.strip()]
    assert len(lines) == 52  # 1 header + 51 rows
    assert "Transaction_Id,Order_Date,Product" in lines[0]


def test_generate_filtered_transactions_csv(db_session: Session):
    """Verifies that filtering by is_eligible=True yields 48 records + 1 header."""
    csv_str = generate_transactions_csv_export(db_session, filter_eligible=True)
    lines = [line for line in csv_str.strip().split("\n") if line.strip()]
    assert len(lines) == 49  # 1 header + 48 eligible rows


def test_generate_analytics_summary_csv_types(db_session: Session):
    """Verifies that each summary export type produces expected header and content."""
    for stype in ["products", "regions", "monthly", "channels"]:
        csv_str = generate_analytics_summary_csv(db_session, summary_type=stype)
        lines = [line for line in csv_str.strip().split("\n") if line.strip()]
        assert len(lines) >= 2  # At least header + 1 row


def test_api_export_pdf_endpoint():
    """Tests GET /api/export/pdf endpoint via HTTP client."""
    response = client.get("/api/export/pdf", headers={"X-User-Role": "Analyst"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_api_export_csv_endpoint():
    """Tests GET /api/export/csv endpoint via HTTP client."""
    response = client.get("/api/export/csv", headers={"X-User-Role": "Admin"})
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    lines = response.text.strip().split("\n")
    assert len(lines) == 52
