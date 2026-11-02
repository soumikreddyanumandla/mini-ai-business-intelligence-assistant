"""
Pydantic Schemas Module
-----------------------
Defines structured request and response models for the FastAPI endpoints,
LLM structured output validation, and frontend contract serialization.
"""

from enum import IntEnum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class QuestionCategory(IntEnum):
    """
    Business Intelligence Question Taxonomy:
    1 - Supported: Mapped directly to an approved database analytical tool.
    2 - Related Unsupported: Business query lacking dataset fields (e.g., profit/cost).
    3 - Ambiguous: Query lacks necessary parameters (e.g., month comparison without months).
    4 - Unrelated: Query outside the sales analytics domain (general chit-chat, trivia).
    """
    SUPPORTED = 1
    RELATED_UNSUPPORTED = 2
    AMBIGUOUS = 3
    UNRELATED = 4


class QueryRequest(BaseModel):
    """User incoming natural language question request."""
    question: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="The natural language question asked by the business user.",
        examples=["Which product generated the highest revenue?"]
    )
    session_id: Optional[str] = Field(
        default="default",
        description="Conversation session ID for multi-turn conversational tracking."
    )
    conversation_history: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        description="Recent conversation turns for contextual grounding."
    )

    @field_validator("question")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Question cannot be empty or solely whitespace.")
        return stripped


class IntentInterpretation(BaseModel):
    """Structured output schema returned by the LLM / Intent Router."""
    intent: str = Field(..., description="Canonical tool or intent identifier.")
    category: QuestionCategory = Field(
        QuestionCategory.SUPPORTED,
        description="Classification according to the 4-category taxonomy."
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted key-value parameters (e.g., month_1, month_2, product, region)."
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    needs_clarification: bool = Field(default=False)
    clarification_prompt: Optional[str] = Field(
        default=None,
        description="Clarification request to the user if ambiguous."
    )
    unsupported_reason: Optional[str] = Field(
        default=None,
        description="Explanation when the requested metric is not in the dataset."
    )
    suggested_alternatives: List[str] = Field(
        default_factory=list,
        description="Helpful alternative supported questions."
    )


class QueryResponse(BaseModel):
    """Unified API response returned to client / Streamlit interface."""
    success: bool
    question: str
    intent: str
    category: int
    category_name: str
    answer: str
    explanation: str
    metrics: Dict[str, Any] = Field(default_factory=dict)
    supporting_data: List[Dict[str, Any]] = Field(default_factory=list)
    chart_type: Optional[str] = Field(
        default="metric",
        description="Recommended chart type: bar, line, donut, metric, table, etc."
    )
    chart_data: Optional[Dict[str, Any]] = None
    ai_mode: str = Field(
        default="fallback_rule",
        description="AI engine used: 'gemini', 'openai', or 'fallback_rule'."
    )
    data_quality_notes: List[str] = Field(default_factory=list)
    execution_time_ms: float = 0.0
    session_id: Optional[str] = "default"
    resolved_context: Optional[str] = None
    provenance: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Data provenance metadata describing executed analytical operation, entity, and eligible row count."
    )


class DashboardMetrics(BaseModel):
    """High-level summary metrics for executive dashboard."""
    total_gross_revenue: float
    total_net_revenue: float
    total_discounts: float
    total_quantity: int
    total_transactions: int
    eligible_transactions: int
    excluded_transactions: int
    unique_products: int
    unique_regions: int
    unique_categories: int
    average_order_value: float
    currency: str = "INR"


class ExcludedTransactionItem(BaseModel):
    """Details of an excluded or suspicious record for audit transparency."""
    transaction_id: str
    order_date: Optional[str]
    product: str
    quantity: int
    unit_price: Optional[float]
    discount_amount: float
    status: str
    exclusion_reasons: List[str]


class DataQualityReport(BaseModel):
    """Detailed audit report of data cleanliness and eligibility."""
    total_records: int
    eligible_records: int
    excluded_records: int
    cleanliness_percentage: float
    excluded_transactions: List[ExcludedTransactionItem]
    validation_rules: List[str]
    audit_notes: List[str]
    dqi_score: Optional[float] = None
    dqi_grade: Optional[str] = None
    dimensions: Optional[Dict[str, Any]] = None
    profiling: Optional[Dict[str, Any]] = None


class SuggestionItem(BaseModel):
    """Pre-built suggestion for business users."""
    category: str
    question: str
    description: str


class LLMConfigRequest(BaseModel):
    """Payload to configure or update the LLM provider key dynamically (Admin only)."""
    provider: str = Field(default="gemini", description="LLM provider: 'gemini' or 'openai'")
    api_key: str = Field(..., description="API key string")
    model: Optional[str] = Field(default="gemini-flash-lite-latest", description="Model name")


class LLMStatusResponse(BaseModel):
    """Safe public LLM status summary visible to all authenticated roles (never exposes key)."""
    provider: str
    model: str
    is_key_configured: bool
    status: str = Field(..., description="'verified', 'not_configured', or 'temporarily_unavailable'")
    status_description: str
    fallback_active: bool
    last_verified_at: Optional[str] = None


class AdminLLMConfigResponse(BaseModel):
    """Privileged LLM configuration response for Admin role with masked key preview."""
    success: bool = True
    provider: str
    model: str
    is_key_configured: bool
    masked_key: Optional[str] = None
    status: str
    status_description: str
    fallback_active: bool
    message: Optional[str] = None


class LLMOutageSimRequest(BaseModel):
    """Optional payload to toggle simulated LLM outage."""
    enabled: bool = True
    reason: Optional[str] = "Simulated Gemini API Timeout (504 Gateway Timeout)"

