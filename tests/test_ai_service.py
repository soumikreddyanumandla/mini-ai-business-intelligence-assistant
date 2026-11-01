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


def test_multi_turn_conversational_followup_dialog(db_session):
    """Test 13: Multi-turn conversational context & reference resolution."""
    session_id = "test_eval_session_01"
    
    # Turn 1: Initial query establishing regional entity
    t1 = ai_service.process_query(
        "Which region generated the highest revenue?",
        db_session,
        session_id=session_id,
    )
    assert t1.success is True
    assert t1.intent == "top_revenue_region"
    assert "South" in t1.answer
    assert t1.metrics["top_region"] == "South"

    # Turn 2: Follow-up using pronoun 'its' -> should resolve to South
    t2 = ai_service.process_query(
        "Show its monthly trend.",
        db_session,
        session_id=session_id,
    )
    assert t2.success is True
    assert t2.intent == "monthly_revenue_trend"
    assert t2.metrics.get("filtered_region") == "South"
    assert "South" in t2.metrics["title"]

    # Turn 3: Follow-up using 'Compare it with North' -> should resolve South vs North
    t3 = ai_service.process_query(
        "Compare it with North.",
        db_session,
        session_id=session_id,
    )
    assert t3.success is True
    assert t3.intent == "compare_regions"
    assert "South" in t3.answer
    assert "North" in t3.answer
    assert t3.metrics["region_1"]["region"] == "South"
    assert t3.metrics["region_2"]["region"] == "North"


def test_compare_regions_direct(db_session):
    """Test 14: Direct region-to-region comparison."""
    from backend.analytics import compare_regions
    res = compare_regions(db_session, "South", "North")
    assert res["region_1"]["region"] == "South"
    assert res["region_2"]["region"] == "North"
    assert res["region_1"]["net_revenue"] == 411200.0
    assert res["region_2"]["net_revenue"] == 384450.0
    assert res["revenue_difference"] == 26750.0


def test_lowest_performing_product_direct(db_session):
    """Test 15: Lowest revenue product analysis."""
    from backend.analytics import get_lowest_performing_product
    res = get_lowest_performing_product(db_session)
    assert res["lowest_product"] == "Laptop Stand"
    assert res["lowest_product_net_revenue"] == 96000.0
    assert res["quantity_sold"] == 80


def test_sanitize_secret_removes_api_keys():
    """Test 16: sanitize_secret redacts API keys and secrets from text."""
    from backend.ai_service import sanitize_secret
    sensitive_text = "API connection error with key AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q in call"
    scrubbed = sanitize_secret(sensitive_text)
    assert "AIzaSy" not in scrubbed
    assert "[REDACTED_API_KEY]" in scrubbed


def test_llm_status_four_states_distinction():
    """Test 17: Validates clear distinction among the 4 states:
    - API key configured
    - Gemini successfully verified
    - Gemini temporarily unavailable
    - Deterministic fallback active
    """
    # 1. Verified state
    with patch.object(ai_service, "gemini_status", "verified"):
        with patch.object(ai_service, "gemini_client", MagicMock()):
            with patch.object(ai_service, "is_llm_available", return_value=True):
                status_res = ai_service.get_llm_status()
                assert status_res["status"] == "verified"
                assert status_res["fallback_active"] is False

    # 2. Temporarily unavailable state (e.g. 429 quota or connection timeout)
    with patch.object(ai_service, "gemini_status", "temporarily_unavailable"):
        with patch.object(ai_service, "is_llm_available", return_value=False):
            status_res = ai_service.get_llm_status()
            assert status_res["status"] == "temporarily_unavailable"
            assert status_res["fallback_active"] is True

    # 3. Not configured state
    with patch.object(ai_service, "gemini_status", "not_configured"):
        with patch.object(ai_service, "is_llm_available", return_value=False):
            status_res = ai_service.get_llm_status()
            assert status_res["status"] == "not_configured"
            assert status_res["fallback_active"] is True


def test_end_to_end_gemini_success_and_fallback_toggle(db_session):
    """Test 18: End-to-end verification of Gemini success, fallback transition, and recovery."""
    # Step 1: Normal processing when Gemini is available
    res_normal = ai_service.process_query("What is the total revenue?", db_session)
    assert res_normal.success is True
    assert res_normal.metrics["total_net_revenue"] == 1439200.0
    # Confirms grounded answer without fabrication
    assert "1,439,200.00" in res_normal.answer

    # Step 2: Simulate timeout/outage
    ai_service.simulate_outage(enabled=True, reason="Simulated Timeout Probe")
    try:
        assert ai_service.is_llm_available() is False
        status_outage = ai_service.get_llm_status()
        assert status_outage["status"] == "temporarily_unavailable"
        assert status_outage["fallback_active"] is True

        # Supported question processed via deterministic fallback
        res_fallback = ai_service.process_query("What is the total revenue?", db_session)
        assert res_fallback.success is True
        assert res_fallback.ai_mode == "fallback_rule"
        assert res_fallback.metrics["total_net_revenue"] == 1439200.0
        assert "1,439,200.00" in res_fallback.answer
        # Verify no fabricated data
        assert res_fallback.category == 1

        # Test another supported question under fallback: top product
        res_top_prod = ai_service.process_query("Which product generated the highest revenue?", db_session)
        assert res_top_prod.success is True
        assert res_top_prod.ai_mode == "fallback_rule"
        assert "Monitor" in res_top_prod.answer
        assert res_top_prod.metrics["top_product_net_revenue"] == 473000.0

    finally:
        # Step 3: Restore Gemini availability
        ai_service.simulate_outage(enabled=False)
        assert ai_service._simulation_active is False
        status_restored = ai_service.get_llm_status()
        assert status_restored["status"] == "verified"
        assert status_restored["fallback_active"] is False

    # Step 4: Verify application returns automatically to operational state
    res_restored = ai_service.process_query("What is the total revenue?", db_session)
    assert res_restored.success is True
    assert res_restored.metrics["total_net_revenue"] == 1439200.0


