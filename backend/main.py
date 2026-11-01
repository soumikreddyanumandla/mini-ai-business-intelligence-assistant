"""
FastAPI Backend Application Module
----------------------------------
Serves RESTful API endpoints for the Mini AI Business Intelligence Assistant:
- Health checking and connectivity verification
- Natural language query answering (/api/ask)
- Dashboard KPIs and analytical breakdowns
- Data quality and audit reporting
- CSV dataset upload and dynamic re-synchronization.
"""

import io
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db, init_db, check_db_health, SessionLocal
from backend.models import SalesTransaction
from backend.data_loader import load_and_sync_csv_to_db
from backend.analytics import (
    get_total_revenue,
    get_highest_revenue_product,
    get_monthly_revenue_trend,
    get_highest_revenue_region,
    get_category_revenue_breakdown,
    get_sales_channel_comparison,
    get_dashboard_summary_metrics,
)
from backend.ai_service import ai_service
from backend.schemas import (
    QueryRequest,
    QueryResponse,
    DashboardMetrics,
    DataQualityReport,
    ExcludedTransactionItem,
    SuggestionItem,
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backend.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown events."""
    logger.info("Initializing database and syncing sales dataset on startup...")
    init_db(drop_existing=False)
    
    # Check if database has transactions; if empty, load CSV
    db = SessionLocal()
    try:
        count = db.query(SalesTransaction).count()
        if count == 0:
            logger.info("Database is empty. Ingesting initial sales.csv dataset...")
            load_and_sync_csv_to_db(db=db)
    except Exception as e:
        logger.error(f"Startup initialization error: {e}")
    finally:
        db.close()
        
    yield
    logger.info("Shutting down Mini AI BI Assistant backend.")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Intelligent Business Intelligence Assistant with grounded SQL analytics and GenAI.",
    lifespan=lifespan,
)

# Enable CORS for Streamlit and local browser clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------

@app.get("/api/health", tags=["System"])
def health_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Verifies service health, database connectivity, and configured LLM status."""
    db_ok = check_db_health()
    llm_active = ai_service.is_llm_available()
    return {
        "status": "healthy" if db_ok else "degraded",
        "database_connected": db_ok,
        "llm_provider": settings.LLM_PROVIDER,
        "llm_online": llm_active,
        "version": settings.APP_VERSION,
    }


@app.post("/api/ask", response_model=QueryResponse, tags=["AI Assistant"])
def ask_question(payload: QueryRequest, db: Session = Depends(get_db)) -> QueryResponse:
    """
    Core AI conversational endpoint:
    Accepts natural language business questions, recognizes intent, executes approved
    SQL analytics, generates grounded explanations, and returns interactive chart metadata.
    """
    logger.info(f"Received user question: '{payload.question}'")
    return ai_service.process_query(payload.question, db)


@app.get("/api/dashboard", response_model=DashboardMetrics, tags=["Dashboard"])
def get_dashboard_kpis(db: Session = Depends(get_db)) -> DashboardMetrics:
    """Retrieves high-level summary KPIs for executive dashboard cards."""
    metrics = get_dashboard_summary_metrics(db)
    return DashboardMetrics(**metrics)


@app.get("/api/analytics/products", tags=["Analytics"])
def get_product_analytics(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Returns product-wise net revenue, gross revenue, units sold, and rankings."""
    return get_highest_revenue_product(db, limit=100)


@app.get("/api/analytics/regions", tags=["Analytics"])
def get_region_analytics(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Returns region-wise revenue, quantity sold, order count, and market share."""
    return get_highest_revenue_region(db, limit=100)


@app.get("/api/analytics/monthly", tags=["Analytics"])
def get_monthly_analytics(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Returns chronological monthly revenue trends and growth rates."""
    return get_monthly_revenue_trend(db)


@app.get("/api/analytics/categories", tags=["Analytics"])
def get_category_analytics(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Returns category breakdown and revenue contribution."""
    return get_category_revenue_breakdown(db)


@app.get("/api/analytics/channels", tags=["Analytics"])
def get_channel_analytics(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Returns sales channel performance (Online vs Retail)."""
    return get_sales_channel_comparison(db)


@app.get("/api/data-quality", response_model=DataQualityReport, tags=["Data Quality"])
def get_data_quality_report(db: Session = Depends(get_db)) -> DataQualityReport:
    """
    Detailed audit report on dataset cleanliness:
    Lists total records, valid records, excluded transactions, and exact reasons for exclusion.
    """
    total_records = db.query(SalesTransaction).count()
    eligible_count = db.query(SalesTransaction).filter(SalesTransaction.is_eligible == True).count()
    excluded_rows = db.query(SalesTransaction).filter(SalesTransaction.is_eligible == False).all()

    cleanliness_rate = (
        round((eligible_count / total_records) * 100, 2) if total_records > 0 else 0.0
    )

    excluded_items = []
    for r in excluded_rows:
        reasons = [r.exclusion_reason] if r.exclusion_reason else ["Excluded by business rule"]
        excluded_items.append(
            ExcludedTransactionItem(
                transaction_id=r.transaction_id,
                order_date=r.order_date.isoformat() if r.order_date else None,
                product=r.product,
                quantity=r.quantity,
                unit_price=r.unit_price,
                discount_amount=r.discount_amount,
                status=r.status,
                exclusion_reasons=reasons,
            )
        )

    validation_rules = [
        "Include transactions with Status == 'Completed' only.",
        "Exclude 'Returned' transactions from realized revenue.",
        "Reject zero or negative quantities (flag as suspicious/invalid).",
        "Reject missing, null, or empty unit prices.",
        "Ensure discount amounts are valid (>= 0 and <= gross revenue).",
        "Do not silently replace missing values with zeros or discard audit records.",
    ]

    audit_notes = [
        f"Total transactions imported: {total_records}",
        f"Realized revenue eligible transactions: {eligible_count}",
        f"Excluded for business/data-quality reasons: {len(excluded_rows)}",
    ]

    return DataQualityReport(
        total_records=total_records,
        eligible_records=eligible_count,
        excluded_records=len(excluded_rows),
        cleanliness_percentage=cleanliness_rate,
        excluded_transactions=excluded_items,
        validation_rules=validation_rules,
        audit_notes=audit_notes,
    )


@app.get("/api/suggestions", response_model=List[SuggestionItem], tags=["AI Assistant"])
def get_suggested_questions() -> List[SuggestionItem]:
    """Returns curated suggested business questions across categories."""
    return [
        SuggestionItem(
            category="Mandatory Questions",
            question="What is the total revenue?",
            description="Computes gross, net revenue, discounts, and realized sales.",
        ),
        SuggestionItem(
            category="Mandatory Questions",
            question="Which product generated the highest revenue?",
            description="Ranks products by total net revenue and units sold.",
        ),
        SuggestionItem(
            category="Mandatory Questions",
            question="What is the monthly revenue trend?",
            description="Chronological month-by-month sales trajectory and peak month.",
        ),
        SuggestionItem(
            category="Mandatory Questions",
            question="Which region generated the highest revenue?",
            description="Regional sales distribution and market share ranking.",
        ),
        SuggestionItem(
            category="Mandatory Questions",
            question="Compare January and February.",
            description="Head-to-head comparison with absolute and percentage variance.",
        ),
        SuggestionItem(
            category="Product Performance",
            question="Which product sold the highest quantity?",
            description="Product sales volume and unit distribution.",
        ),
        SuggestionItem(
            category="Channel Analysis",
            question="Compare Online and Retail sales channels.",
            description="Revenue and order volume breakdown by channel.",
        ),
        SuggestionItem(
            category="Category Insights",
            question="What is the revenue breakdown by category?",
            description="Category-wise revenue contribution percentage.",
        ),
        SuggestionItem(
            category="Pricing & Discounts",
            question="How much discount did we give?",
            description="Total discounts and effective discount rate on gross sales.",
        ),
        SuggestionItem(
            category="Edge Cases & Clarification",
            question="Compare revenue.",
            description="Demonstrates AI handling of ambiguous questions needing clarification.",
        ),
        SuggestionItem(
            category="Edge Cases & Clarification",
            question="What is our net profit margin?",
            description="Demonstrates graceful handling of unsupported business metrics.",
        ),
    ]


@app.post("/api/upload", tags=["Data Management"])
async def upload_sales_dataset(file: UploadFile = File(...), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Allows users to upload a new or refreshed sales CSV dataset.
    Validates CSV headers, applies data cleaning rules, updates SQLite, and logs audit metrics.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV files (.csv) are accepted.",
        )

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds the 10MB limit.",
        )

    # Save to disk temporarily and sync
    temp_path = settings.BASE_DIR / "data" / "uploaded_sales.csv"
    with open(temp_path, "wb") as f:
        f.write(content)

    try:
        summary = load_and_sync_csv_to_db(csv_path=str(temp_path), db=db, replace_existing=True)
        return {
            "success": True,
            "filename": file.filename,
            "summary": summary,
            "message": "Dataset successfully uploaded, cleaned, and synced to SQLite database.",
        }
    except Exception as e:
        logger.error(f"Error processing uploaded CSV: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
