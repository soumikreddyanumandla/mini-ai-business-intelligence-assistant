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


class SuggestionItem(BaseModel):
    """Pre-built suggestion for business users."""
    category: str
    question: str
    description: str
