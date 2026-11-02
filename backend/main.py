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
import time
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Response, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import get_db, init_db, check_db_health, SessionLocal
from backend.models import SalesTransaction, SecurityAuditLog
from backend.security import rate_limiter, log_security_event
from backend.data_loader import load_and_sync_csv_to_db
from backend.metrics import metrics_collector
from backend.ai_service import sanitize_secret
from backend.analytics import (
    get_total_revenue,
    get_highest_revenue_product,
    get_monthly_revenue_trend,
    get_highest_revenue_region,
    get_category_revenue_breakdown,
    get_sales_channel_comparison,
    get_dashboard_summary_metrics,
    detect_anomalies,
    get_pareto_revenue_concentration,
    simulate_what_if_revenue,
    get_sales_target_pacing,
)
from backend.ai_service import ai_service
from backend.report_exporter import (
    generate_executive_pdf_report,
    generate_transactions_csv_export,
    generate_analytics_summary_csv,
)
from backend.forecasting import generate_sales_forecast
from backend.auth import (
    authenticate_user,
    UserCredentials,
    AuthTokenResponse,
    require_admin,
    require_analyst_or_admin,
    require_any_authenticated,
)
from backend.schemas import (
    QueryRequest,
    QueryResponse,
    DashboardMetrics,
    DataQualityReport,
    ExcludedTransactionItem,
    SuggestionItem,
    LLMConfigRequest,
    LLMStatusResponse,
    AdminLLMConfigResponse,
    LLMOutageSimRequest,
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
# Middleware & Global Exception Handling
# ----------------------------------------------------------------------

@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):
    """
    Measures request execution duration, records HTTP telemetry, and adds
    an X-Process-Time-Ms diagnostic header.
    """
    start_time = time.time()
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        metrics_collector.record_request(request.url.path, response.status_code, duration)
        response.headers["X-Process-Time-Ms"] = str(round(duration * 1000, 2))
        return response
    except Exception as exc:
        duration = time.time() - start_time
        metrics_collector.record_request(request.url.path, 500, duration)
        raise exc


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global defensive exception handler:
    - Logs detailed stack traces and sanitized error context internally for developer troubleshooting.
    - Strictly prevents API keys, database internals, and raw Python tracebacks from leaking to end users.
    """
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    # Sanitize any credentials from error text before logging
    clean_err = sanitize_secret(str(exc))
    logger.error(
        f"[Internal Server Error] Unhandled exception on {request.method} {request.url.path}: {clean_err}",
        exc_info=True,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred while processing your request. Please try again later.",
            "status_code": 500,
        },
    )


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------

@app.get("/api/health", tags=["System"])
def health_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Verifies service health, database connectivity, and configured LLM status."""
    db_ok = check_db_health()
    status_info = ai_service.get_llm_status()
    return {
        "status": "healthy" if db_ok else "degraded",
        "database_connected": db_ok,
        "llm_provider": status_info["provider"],
        "llm_online": not status_info["fallback_active"],
        "llm_status": status_info["status"],
        "llm_status_detail": status_info["status_description"],
        "fallback_active": status_info["fallback_active"],
        "version": settings.APP_VERSION,
    }


@app.get("/api/ready", tags=["System"])
def readiness_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Deployment readiness probe:
    Verifies that SQLite database is reachable, operational, and initialized with records.
    Returns HTTP 200 when ready to accept traffic, or HTTP 503 if degraded.
    """
    db_ok = check_db_health()
    if not db_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service Not Ready: SQLite database connection is unreachable.",
        )
    try:
        count = db.query(SalesTransaction).count()
    except Exception as e:
        logger.error(f"Readiness probe database query failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service Not Ready: Database table query failed.",
        )

    return {
        "status": "ready",
        "database": "connected",
        "initialized": count > 0,
        "total_records": count,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/metrics", tags=["System"])
def get_system_metrics(role: str = Depends(require_admin)) -> Dict[str, Any]:
    """
    Telemetry and observability metrics endpoint (Admin only).
    Reports request counts, status code breakdown, latency distributions (avg, p95, max),
    AI service provider invocations, circuit breaker events, and in-memory cache statistics.
    Note: Metrics are collected in-memory per process.
    """
    return metrics_collector.get_summary()


@app.get("/api/llm/status", response_model=LLMStatusResponse, tags=["System"])
def get_public_llm_status(role: str = Depends(require_any_authenticated)) -> LLMStatusResponse:
    """
    Public/All-roles status summary of backend centralized Gemini engine.
    Distinguishes between configured, verified, temporarily unavailable, and deterministic fallback active.
    Never exposes the raw or masked API key.
    """
    status_info = ai_service.get_llm_status()
    return LLMStatusResponse(**status_info)


@app.post("/api/auth/login", response_model=AuthTokenResponse, tags=["Authentication & RBAC"])
def login_user(
    credentials: UserCredentials,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    """
    Authenticates users via username and password.
    Returns access token, role ('Admin', 'Analyst', 'Viewer'), and allowed permissions.
    Logs audit events for successful and failed authentication attempts.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    auth_res = authenticate_user(credentials)
    if not auth_res:
        log_security_event(
            event_type="LOGIN_FAILED",
            user_role="Anonymous",
            client_ip=client_ip,
            endpoint="/api/auth/login",
            severity="WARNING",
            details=f"Failed login attempt for username '{credentials.username}'.",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    user_role = auth_res.get("role", "Unknown")
    log_security_event(
        event_type="LOGIN_SUCCESS",
        user_role=user_role,
        client_ip=client_ip,
        endpoint="/api/auth/login",
        severity="INFO",
        details=f"User '{credentials.username}' authenticated successfully as '{user_role}'.",
        db=db,
    )
    return AuthTokenResponse(**auth_res)


@app.get("/api/config/llm", response_model=AdminLLMConfigResponse, tags=["System"])
def get_admin_llm_config(role: str = Depends(require_admin)) -> AdminLLMConfigResponse:
    """
    Admin-only endpoint to inspect centralized LLM configuration and verification state.
    Includes a masked preview of the configured key (e.g. 'AQ.Ab8...J7KA').
    Analyst and Viewer roles are strictly forbidden (403).
    """
    status_info = ai_service.get_llm_status()
    return AdminLLMConfigResponse(
        success=True,
        provider=status_info["provider"],
        model=status_info["model"],
        is_key_configured=status_info["is_key_configured"],
        masked_key=ai_service.get_masked_key(),
        status=status_info["status"],
        status_description=status_info["status_description"],
        fallback_active=status_info["fallback_active"],
        message=status_info["status_description"],
    )


@app.post("/api/config/llm", response_model=AdminLLMConfigResponse, tags=["System"])
def configure_llm_key(
    payload: LLMConfigRequest,
    role: str = Depends(require_admin),
) -> AdminLLMConfigResponse:
    """
    Dynamically connects and validates the Gemini or OpenAI API key.
    Tests the connection live and persists verified keys to the .env file.
    Protected by Admin RBAC role. Analyst and Viewer roles are strictly forbidden (403).
    """
    success, msg = ai_service.configure_provider(
        provider=payload.provider,
        api_key=payload.api_key,
        model=payload.model,
    )
    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    # Persist to .env file
    env_file = settings.BASE_DIR / ".env"
    try:
        lines = []
        if env_file.exists():
            with open(env_file, "r") as f:
                lines = f.readlines()

        updated = {}
        if payload.provider == "gemini":
            updated["LLM_PROVIDER"] = "gemini"
            updated["GEMINI_API_KEY"] = payload.api_key
            if payload.model:
                updated["GEMINI_MODEL"] = payload.model
        elif payload.provider == "openai":
            updated["LLM_PROVIDER"] = "openai"
            updated["OPENAI_API_KEY"] = payload.api_key
            if payload.model:
                updated["OPENAI_MODEL"] = payload.model

        new_lines = []
        written_keys = set()
        for line in lines:
            line_str = line.strip()
            if "=" in line_str and not line_str.startswith("#"):
                k, _ = line_str.split("=", 1)
                k = k.strip()
                if k in updated:
                    new_lines.append(f"{k}={updated[k]}\n")
                    written_keys.add(k)
                    continue
            new_lines.append(line)

        for k, v in updated.items():
            if k not in written_keys:
                new_lines.append(f"{k}={v}\n")

        with open(env_file, "w") as f:
            f.writelines(new_lines)
    except Exception as e:
        logger.warning(f"Could not persist API key to .env: {e}")

    log_security_event(
        event_type="LLM_CONFIG_UPDATED",
        user_role=role,
        endpoint="/api/config/llm",
        severity="INFO",
        details=f"Provider '{payload.provider}' configured (model: {payload.model}).",
    )

    status_info = ai_service.get_llm_status()
    return AdminLLMConfigResponse(
        success=True,
        provider=status_info["provider"],
        model=status_info["model"],
        is_key_configured=status_info["is_key_configured"],
        masked_key=ai_service.get_masked_key(),
        status=status_info["status"],
        status_description=status_info["status_description"],
        fallback_active=status_info["fallback_active"],
        message=msg,
    )


@app.delete("/api/config/llm", response_model=AdminLLMConfigResponse, tags=["System"])
def clear_llm_key(role: str = Depends(require_admin)) -> AdminLLMConfigResponse:
    """
    Clears the centralized Gemini API key from memory and backend configuration.
    Protected by Admin RBAC role. Analyst and Viewer roles are strictly forbidden (403).
    """
    success, msg = ai_service.clear_provider("gemini")

    # Persist blank key to .env file
    env_file = settings.BASE_DIR / ".env"
    try:
        if env_file.exists():
            with open(env_file, "r") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                line_str = line.strip()
                if line_str.startswith("GEMINI_API_KEY="):
                    new_lines.append("GEMINI_API_KEY=\n")
                else:
                    new_lines.append(line)
            with open(env_file, "w") as f:
                f.writelines(new_lines)
    except Exception as e:
        logger.warning(f"Could not update .env on key deletion: {e}")

    log_security_event(
        event_type="LLM_KEY_CLEARED",
        user_role=role,
        endpoint="/api/config/llm",
        severity="WARNING",
        details="Centralized Gemini key was removed/cleared.",
    )

    status_info = ai_service.get_llm_status()
    return AdminLLMConfigResponse(
        success=success,
        provider=status_info["provider"],
        model=status_info["model"],
        is_key_configured=status_info["is_key_configured"],
        masked_key=None,
        status=status_info["status"],
        status_description=status_info["status_description"],
        fallback_active=status_info["fallback_active"],
        message=msg,
    )


@app.post("/api/config/llm/verify", response_model=AdminLLMConfigResponse, tags=["System"])
def verify_llm_connection(role: str = Depends(require_admin)) -> AdminLLMConfigResponse:
    """
    Performs a live connectivity probe against the centralized Gemini client.
    Restores verified status if reachable, or marks temporarily unavailable.
    Protected by Admin RBAC role. Analyst and Viewer are strictly forbidden (403).
    """
    success, msg = ai_service.verify_live_connection()
    status_info = ai_service.get_llm_status()
    return AdminLLMConfigResponse(
        success=success,
        provider=status_info["provider"],
        model=status_info["model"],
        is_key_configured=status_info["is_key_configured"],
        masked_key=ai_service.get_masked_key(),
        status=status_info["status"],
        status_description=status_info["status_description"],
        fallback_active=status_info["fallback_active"],
        message=msg,
    )


@app.post("/api/config/llm/simulate-outage", response_model=AdminLLMConfigResponse, tags=["System"])
def simulate_llm_outage(
    payload: Optional[LLMOutageSimRequest] = None,
    enabled: Optional[bool] = None,
    reason: Optional[str] = None,
    role: str = Depends(require_admin),
) -> AdminLLMConfigResponse:
    """
    Simulates a temporary external Gemini API outage/timeout for end-to-end testing,
    without deleting or modifying the configured API key or production configuration.
    Accepts either JSON payload or query parameters.
    Protected by Admin RBAC role. Analyst and Viewer are strictly forbidden (403).
    """
    is_enabled = True
    outage_reason = "Simulated Gemini API Timeout (504 Gateway Timeout)"

    if payload is not None:
        is_enabled = payload.enabled
        if payload.reason:
            outage_reason = payload.reason
    elif enabled is not None:
        is_enabled = enabled
        if reason:
            outage_reason = reason

    ai_service.simulate_outage(enabled=is_enabled, reason=outage_reason)
    log_security_event(
        event_type="OUTAGE_SIMULATION_TOGGLED",
        user_role=role,
        endpoint="/api/config/llm/simulate-outage",
        severity="INFO",
        details=f"Simulation active={is_enabled}, reason='{outage_reason}'",
    )
    status_info = ai_service.get_llm_status()
    return AdminLLMConfigResponse(
        success=True,
        provider=status_info["provider"],
        model=status_info["model"],
        is_key_configured=status_info["is_key_configured"],
        masked_key=ai_service.get_masked_key(),
        status=status_info["status"],
        status_description=status_info["status_description"],
        fallback_active=status_info["fallback_active"],
        message=status_info["status_description"],
    )


@app.post("/api/ask", response_model=QueryResponse, tags=["AI Assistant"])
def ask_question(
    payload: QueryRequest,
    request: Request,
    db: Session = Depends(get_db),
    role: str = Depends(require_analyst_or_admin),
) -> QueryResponse:
    """
    Core AI conversational endpoint:
    Accepts natural language business questions, recognizes intent, executes approved
    SQL analytics, generates grounded explanations, and returns interactive chart metadata.
    Protected by Analyst or Admin RBAC role.
    Rate limited to 60 requests/minute per client IP (thread-safe sliding window).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "127.0.0.1")
    allowed, retry_after, remaining = rate_limiter.is_allowed(client_ip, max_requests=60, window_seconds=60.0)
    if not allowed:
        log_security_event(
            event_type="RATE_LIMIT_EXCEEDED",
            user_role=role,
            client_ip=client_ip,
            endpoint="/api/ask",
            severity="WARNING",
            details=f"Rate limit exceeded on /api/ask (60 req/min). Cooldown: {retry_after}s.",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: 60 requests per minute limit reached. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(int(retry_after))},
        )

    logger.info(f"Received user question: '{payload.question}' (session: {payload.session_id}, role: {role})")
    return ai_service.process_query(payload.question, db, session_id=payload.session_id)


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


@app.get("/api/analytics/anomalies", tags=["Advanced Analytics"])
def get_anomaly_analytics(
    z_threshold: float = 2.5,
    db: Session = Depends(get_db),
    role: str = Depends(require_analyst_or_admin),
) -> Dict[str, Any]:
    """
    Detects statistical outliers (IQR and Z-score) and lists confirmed data quality errors.
    Protected by Analyst or Admin RBAC role.
    """
    return detect_anomalies(db, z_threshold=z_threshold)


@app.get("/api/analytics/pareto", tags=["Advanced Analytics"])
def get_pareto_analytics(
    cutoff: float = 80.0,
    db: Session = Depends(get_db),
    role: str = Depends(require_analyst_or_admin),
) -> Dict[str, Any]:
    """
    Calculates Pareto 80/20 revenue concentration with explicit denominator.
    Protected by Analyst or Admin RBAC role.
    """
    return get_pareto_revenue_concentration(db, top_pct_cutoff=cutoff)


@app.post("/api/analytics/what-if", tags=["Advanced Analytics"])
def run_what_if_simulation(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    role: str = Depends(require_analyst_or_admin),
) -> Dict[str, Any]:
    """
    Simulates revenue impact of price, volume, and discount adjustments without inventing costs.
    Protected by Analyst or Admin RBAC role.
    """
    return simulate_what_if_revenue(
        db,
        price_change_pct=float(payload.get("price_change_pct", 0.0)),
        volume_change_pct=float(payload.get("volume_change_pct", 0.0)),
        discount_adjustment_pct=float(payload.get("discount_adjustment_pct", 0.0)),
        category=payload.get("category"),
        channel=payload.get("channel"),
    )


@app.get("/api/analytics/quota-pacing", tags=["Advanced Analytics"])
def get_quota_pacing_analytics(
    target: float = 500000.0,
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
    role: str = Depends(require_analyst_or_admin),
) -> Dict[str, Any]:
    """
    Evaluates quota pacing comparing configured target against empirical sales data.
    Protected by Analyst or Admin RBAC role.
    """
    return get_sales_target_pacing(
        db,
        monthly_target=target,
        target_year=year,
        target_month=month,
    )


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

    all_txs = db.query(SalesTransaction).all()
    records_dicts = [
        {
            "Transaction_Id": t.transaction_id,
            "Order_date": t.order_date.isoformat() if t.order_date else "",
            "Product": t.product,
            "Category": t.category,
            "Region": t.region,
            "Sales_channel": t.sales_channel,
            "Quantity": t.quantity,
            "Unit_price": t.unit_price,
            "Discount_amount": t.discount_amount,
            "Status": t.status,
        }
        for t in all_txs
    ]
    from backend.data_cleaning import calculate_data_quality_index, profile_csv_dataset
    dqi_res = calculate_data_quality_index(records_dicts)
    profile_res = profile_csv_dataset(records_dicts)

    return DataQualityReport(
        total_records=total_records,
        eligible_records=eligible_count,
        excluded_records=len(excluded_rows),
        cleanliness_percentage=cleanliness_rate,
        excluded_transactions=excluded_items,
        validation_rules=validation_rules,
        audit_notes=audit_notes,
        dqi_score=dqi_res.get("composite_dqi_score", cleanliness_rate),
        dqi_grade=dqi_res.get("dqi_grade", "Good"),
        dimensions=dqi_res.get("dimensions", {}),
        profiling=profile_res.get("columns_profile", {}),
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
def upload_sales_dataset(
    file: UploadFile = File(...),
    request: Request = None,
    db: Session = Depends(get_db),
    role: str = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Allows users to upload a new or refreshed sales CSV dataset.
    Validates CSV headers, applies data cleaning rules, updates SQLite, and logs audit metrics.
    Runs on worker threadpool to avoid blocking FastAPI's main event loop.
    Protected by Admin RBAC role.
    Rate limited to 10 upload attempts per minute per client IP.
    """
    client_ip = request.client.host if (request and request.client) else "127.0.0.1"
    allowed, retry_after, _ = rate_limiter.is_allowed(f"upload_{client_ip}", max_requests=10, window_seconds=60.0)
    if not allowed:
        log_security_event(
            event_type="RATE_LIMIT_EXCEEDED",
            user_role=role,
            client_ip=client_ip,
            endpoint="/api/upload",
            severity="WARNING",
            details="Upload rate limit exceeded (10 uploads/min).",
            db=db,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Upload rate limit exceeded. Try again in {retry_after} seconds.",
            headers={"Retry-After": str(int(retry_after))},
        )

    if not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV files (.csv) are accepted.",
        )

    content = file.file.read()
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
        # Analytics cache invalidation occurs strictly AFTER successful dataset upload
        from backend.cache import analytics_cache
        analytics_cache.invalidate_all()
        log_security_event(
            event_type="DATASET_UPLOAD_SUCCESS",
            user_role=role,
            client_ip=client_ip,
            endpoint="/api/upload",
            severity="INFO",
            details=f"Uploaded '{file.filename}' successfully ({summary.get('total_rows_imported', 0)} rows).",
            db=db,
        )
        return {
            "success": True,
            "filename": file.filename,
            "summary": summary,
            "message": "Dataset successfully validated, cleaned, and synced to SQLite database.",
        }
    except ValueError as e:
        logger.warning(f"CSV schema validation failure: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error processing uploaded CSV: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.post("/api/dataset/reset", tags=["Data Management"])
def reset_to_company_dataset(
    request: Request = None,
    db: Session = Depends(get_db),
    role: str = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Restores the database to the authoritative company-provided sales dataset (data/sales.csv).
    Guarantees baseline consistency for testing and demonstrations.
    Protected by Admin RBAC role.
    """
    client_ip = request.client.host if (request and request.client) else "127.0.0.1"
    from backend.data_loader import reset_default_dataset
    summary = reset_default_dataset(db=db)
    # Analytics cache invalidation occurs strictly AFTER successful dataset reset
    from backend.cache import analytics_cache
    analytics_cache.invalidate_all()
    log_security_event(
        event_type="DATASET_RESET",
        user_role=role,
        client_ip=client_ip,
        endpoint="/api/dataset/reset",
        severity="WARNING",
        details="Database reset to authoritative default sales.csv dataset.",
        db=db,
    )
    return {
        "success": True,
        "message": "Database successfully reset to original company-provided dataset.",
        "summary": summary,
    }


@app.get("/api/security/audit-logs", tags=["Security & Governance"])
def get_security_audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    role: str = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Retrieves recent security and governance audit logs.
    Strictly protected by Admin RBAC role (Analyst and Viewer forbidden with 403).
    """
    safe_limit = min(max(1, limit), 1000)
    total_count = db.query(SecurityAuditLog).count()
    logs = (
        db.query(SecurityAuditLog)
        .order_by(SecurityAuditLog.timestamp.desc())
        .limit(safe_limit)
        .all()
    )
    return {
        "success": True,
        "total_logs": total_count,
        "returned_count": len(logs),
        "logs": [l.to_dict() for l in logs],
    }


# ----------------------------------------------------------------------
# Reports, Forecasting & Data Export Endpoints (Phase 3)
# ----------------------------------------------------------------------

@app.get("/api/export/pdf", tags=["Reporting & Exports"])
def export_pdf_report(
    db: Session = Depends(get_db),
    role: str = Depends(require_analyst_or_admin),
) -> Response:
    """
    Generates and downloads an executive-grade Business Intelligence PDF report.
    Grounded strictly in SQLite database metrics and audit logs.
    Protected by Analyst or Admin role.
    """
    pdf_bytes = generate_executive_pdf_report(db)
    filename = f"sales_executive_bi_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/export/csv", tags=["Reporting & Exports"])
def export_transactions_csv(
    filter_eligible: Optional[bool] = None,
    db: Session = Depends(get_db),
    role: str = Depends(require_analyst_or_admin),
) -> Response:
    """
    Downloads sales transactions as a structured CSV file with audit eligibility status.
    Protected by Analyst or Admin role.
    """
    csv_content = generate_transactions_csv_export(db, filter_eligible=filter_eligible)
    filename = f"sales_transactions_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/export/summary", tags=["Reporting & Exports"])
def export_summary_csv(
    summary_type: str = "products",
    db: Session = Depends(get_db),
    role: str = Depends(require_analyst_or_admin),
) -> Response:
    """
    Downloads aggregated business intelligence summaries in CSV format.
    Options: 'products', 'regions', 'monthly', 'channels'.
    Protected by Analyst or Admin role.
    """
    csv_content = generate_analytics_summary_csv(db, summary_type=summary_type)
    filename = f"sales_summary_{summary_type}_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/forecast", tags=["Machine Learning & Forecasting"])
def get_sales_forecast_endpoint(
    horizon: int = 3,
    db: Session = Depends(get_db),
    role: str = Depends(require_any_authenticated),
) -> Dict[str, Any]:
    """
    Time-series sales forecasting using Linear Trend Regression and Holt's Exponential Smoothing.
    Evaluates out-of-sample MAE, RMSE, and MAPE, and projects revenue with confidence bounds.
    Includes explicit scientific disclosures regarding limited historical sample size.
    """
    return generate_sales_forecast(db, forecast_horizon=horizon)
