"""
Automated Tests for AI Service and Intent Router
------------------------------------------------
Validates:
- 4-category question taxonomy routing
- Handling of ambiguous queries and clarification prompts
- Graceful handling of related but unsupported business queries
- Polite redirection for unrelated out-of-domain queries
- Fallback mechanism when external LLM APIs fail or return malformed JSON.
"""

from unittest.mock import MagicMock, patch
import pytest
from backend.ai_service import ai_service
from backend.intent_router import fallback_classify_intent
from backend.schemas import QuestionCategory


def test_supported_total_revenue_phrasings():
    """Test 1: Multiple natural language phrasings map to 'total_revenue'."""
    phrasings = [
        "What is the total revenue?",
        "How much money did we earn?",
        "Calculate our total net sales.",
        "Give me the overall sales revenue.",
        "How much money did we make?",
    ]
    for q in phrasings:
        intent_res = fallback_classify_intent(q)
        assert intent_res.intent == "total_revenue"
        assert intent_res.category == QuestionCategory.SUPPORTED


def test_supported_top_product_phrasings():
    """Test 2: Multiple natural language phrasings map to 'top_revenue_product'."""
    phrasings = [
        "Which product generated the highest revenue?",
        "Which product made the most money?",
        "What is our best-selling product by sales revenue?",
        "Rank products by revenue.",
    ]
    for q in phrasings:
        intent_res = fallback_classify_intent(q)
        assert intent_res.intent == "top_revenue_product"
        assert intent_res.category == QuestionCategory.SUPPORTED


def test_supported_monthly_trend_phrasings():
    """Test 3: Multiple natural language phrasings map to 'monthly_revenue_trend'."""
    phrasings = [
        "What is the monthly revenue trend?",
        "Show revenue month by month.",
        "Which month performed best?",
        "Monthly sales trend.",
    ]
    for q in phrasings:
        intent_res = fallback_classify_intent(q)
        assert intent_res.intent == "monthly_revenue_trend"
        assert intent_res.category == QuestionCategory.SUPPORTED


def test_supported_region_phrasings():
    """Test 4: Multiple natural language phrasings map to 'top_revenue_region'."""
    phrasings = [
        "Which region generated the highest revenue?",
        "Compare sales across regions.",
        "Which region performs best in sales?",
    ]
    for q in phrasings:
        intent_res = fallback_classify_intent(q)
        assert intent_res.intent == "top_revenue_region"
        assert intent_res.category == QuestionCategory.SUPPORTED


def test_supported_month_comparison_extraction():
    """Test 5: Parameter extraction for two-month comparison."""
    q = "Compare January and February."
    intent_res = fallback_classify_intent(q)
    assert intent_res.intent == "monthly_comparison"
    assert intent_res.category == QuestionCategory.SUPPORTED
    assert intent_res.parameters.get("month_1") == "2026-01"
    assert intent_res.parameters.get("month_2") == "2026-02"


def test_unsupported_business_questions():
    """Test 6: Category 2 questions (Profit, Churn, Inventory, CAC)."""
    questions = [
        "What is our net profit margin?",
        "What is our customer churn rate?",
        "Show inventory stock levels in the warehouse.",
        "What was our marketing ad spend ROAS?",
    ]
    for q in questions:
        intent_res = fallback_classify_intent(q)
        assert intent_res.category == QuestionCategory.RELATED_UNSUPPORTED
        assert intent_res.unsupported_reason is not None
        assert len(intent_res.suggested_alternatives) > 0


def test_ambiguous_comparison_question():
    """Test 7: Category 3 ambiguous question without parameters triggers clarification."""
    q = "Compare revenue"
    intent_res = fallback_classify_intent(q)
    assert intent_res.category == QuestionCategory.AMBIGUOUS
    assert intent_res.needs_clarification is True
    assert "Which two months" in intent_res.clarification_prompt


def test_unrelated_trivia_question():
    """Test 8: Category 4 unrelated questions trigger polite redirection."""
    q = "Who is the Prime Minister of India?"
    intent_res = fallback_classify_intent(q)
    assert intent_res.category == QuestionCategory.UNRELATED
    assert "Business Intelligence Assistant" in intent_res.clarification_prompt


def test_empty_query_handling():
    """Test 9: Empty question handling."""
    intent_res = fallback_classify_intent("   ")
    assert intent_res.category == QuestionCategory.AMBIGUOUS
    assert intent_res.needs_clarification is True


def test_end_to_end_query_processing(db_session):
    """Test 10: Full pipeline execution via ai_service.process_query."""
    res = ai_service.process_query("Which product generated the highest revenue?", db_session)
    assert res.success is True
    assert res.intent == "top_revenue_product"
    assert "Monitor" in res.answer
    assert res.metrics["top_product_net_revenue"] == 473000.0
    assert len(res.supporting_data) > 0


def test_llm_api_failure_fallback(db_session):
    """Test 11: When external LLM throws an exception, system falls back gracefully."""
    with patch.object(ai_service, "is_llm_available", return_value=True):
        with patch.object(ai_service, "gemini_client", create=True) as mock_gemini:
            mock_model = MagicMock()
            mock_model.generate_content.side_effect = RuntimeError("API Network Timeout")
            mock_gemini.GenerativeModel.return_value = mock_model

            res = ai_service.process_query("What is the total revenue?", db_session)
            assert res.success is True
            assert res.ai_mode == "fallback_rule"
            assert "1,439,200.00" in res.answer


def test_invalid_llm_json_fallback(db_session):
    """Test 12: When LLM outputs malformed non-JSON, fallback handles it safely."""
    with patch.object(ai_service, "is_llm_available", return_value=True):
        with patch.object(ai_service, "gemini_client", create=True) as mock_gemini:
            mock_model = MagicMock()
            mock_res = MagicMock()
            mock_res.text = "This is not valid json at all!"
            mock_model.generate_content.return_value = mock_res
            mock_gemini.GenerativeModel.return_value = mock_model

            res = ai_service.process_query("What is the monthly revenue trend?", db_session)
            assert res.success is True
            assert res.intent == "monthly_revenue_trend"
            assert res.ai_mode == "fallback_rule"
