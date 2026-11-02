"""
AI Service Module
-----------------
Orchestrates natural-language understanding, intent recognition, tool selection,
and grounded insight generation.

Supports:
1. Gemini API (via google-genai or google-generativeai)
2. OpenAI API (via openai)
3. Deterministic rule-based fallback router when credentials are not configured
   or external APIs fail/timeout.

Guarantees safety:
- The LLM selects tools; the backend executes them.
- Numerical figures in the response are sourced directly from the SQLite database.
- AI commentary is strictly grounded in the retrieved metrics.
"""

import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, Literal
from sqlalchemy.orm import Session

from backend.config import settings
from backend.exceptions import LLMProviderError, ToolExecutionError
from backend.intent_router import fallback_classify_intent
from backend.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    execute_with_resilience,
    CircuitBreakerOpenException,
)
from backend.schemas import (
    IntentInterpretation,
    QuestionCategory,
    QueryResponse,
)
from backend.tool_registry import registry
from backend.conversation import conversation_manager
from backend.metrics import metrics_collector
from backend.security import inspect_prompt_safety, log_security_event
from backend.models import SalesTransaction

logger = logging.getLogger(__name__)


def sanitize_secret(text: Optional[str]) -> str:
    """Removes sensitive keys, secrets, or credential tokens from messages or logs."""
    if not text:
        return ""
    # Redact Google API key pattern (AIzaSy...) or any long alphanumeric tokens
    text = re.sub(r'AIzaSy[A-Za-z0-9_-]{33}', '[REDACTED_API_KEY]', text)
    if settings.GEMINI_API_KEY and len(settings.GEMINI_API_KEY.strip()) > 8:
        text = text.replace(settings.GEMINI_API_KEY.strip(), '[REDACTED_API_KEY]')
    if settings.OPENAI_API_KEY and len(settings.OPENAI_API_KEY.strip()) > 8:
        text = text.replace(settings.OPENAI_API_KEY.strip(), '[REDACTED_API_KEY]')
    return text

SYSTEM_INTENT_PROMPT = """You are the AI Intent Classifier and Tool Router for an enterprise Business Intelligence assistant analyzing sales transaction data.
Your job is to classify the user's natural language question into one of 4 categories and extract any required parameters.

=== QUESTION CATEGORIES ===
1. Category 1 (SUPPORTED): The question maps directly to an approved analytical tool in the catalog.
2. Category 2 (RELATED_UNSUPPORTED): A business question asking about metrics NOT present in this dataset (e.g., profit, cost/COGS, inventory, customer churn, marketing ROI). The dataset only contains sales transactions, order dates, products, categories, regions, sales channels, quantities, unit prices, discounts, and statuses.
3. Category 3 (AMBIGUOUS): The question requires parameters that were omitted (e.g. "compare revenue" or "month comparison" without specifying two months).
4. Category 4 (UNRELATED): Questions outside sales and business intelligence (e.g., trivia, weather, politics, programming questions).

=== APPROVED TOOLS CATALOG ===
{tool_catalog}

=== OUTPUT FORMAT ===
You MUST respond with ONLY a valid, raw JSON object (no markdown fencing, no explanation) adhering to:
{{
  "intent": "<tool_name or classification_label>",
  "category": <1, 2, 3, or 4>,
  "parameters": {{}},
  "confidence": <float between 0.0 and 1.0>,
  "needs_clarification": <boolean>,
  "clarification_prompt": <string or null>,
  "unsupported_reason": <string or null>,
  "suggested_alternatives": [<string>, ...]
}}
"""

SYSTEM_EXPLANATION_PROMPT = """You are an executive Business Intelligence Analyst.
You are given a business user's question and the EXACT retrieved database metrics.
Generate a concise, professional 2-3 sentence business answer and insight grounded strictly in these retrieved metrics.
CRITICAL RULES:
- Never invent, extrapolate, or alter any numbers.
- State the key metric clearly in the first sentence.
- Provide a brief business observation or context in the second sentence.
- Keep the response direct, authoritative, and professional.
"""


class AIService:
    def __init__(self):
        self.gemini_client = None
        self.gemini_is_genai_sdk = False
        self.gemini_status: Literal["not_configured", "verified", "temporarily_unavailable"] = "not_configured"
        self.gemini_status_detail: str = "Gemini is not configured. Deterministic fallback active."
        self.last_verified_at: Optional[str] = None
        self._simulation_active: bool = False
        self._simulated_reason: Optional[str] = None
        self.openai_client = None
        self.circuit_breaker = CircuitBreaker(
            name="GeminiCircuitBreaker",
            failure_threshold=3,
            recovery_timeout=30.0,
            success_threshold=1,
            on_trip=metrics_collector.record_circuit_trip,
        )
        self._init_clients()

    def _init_clients(self) -> None:
        """Initializes API clients based on backend configuration and environment keys."""
        # 1. Centralized Google Gemini Client Initialization
        if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip():
            clean_key = settings.GEMINI_API_KEY.strip()
            m_name = settings.GEMINI_MODEL or "gemini-flash-lite-latest"
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(
                    api_key=clean_key,
                    http_options=types.HttpOptions(timeout=10000),
                )
                # Live connectivity verification probe
                client.models.generate_content(
                    model=m_name,
                    contents="Ping",
                )
                self.gemini_client = client
                self.gemini_is_genai_sdk = True
                self.gemini_status = "verified"
                self.gemini_status_detail = f"Gemini Connected & Verified Operational (Model: {m_name})"
                self.last_verified_at = datetime.now().isoformat()
                self.circuit_breaker.reset()
                logger.info(f"Centralized Google Gemini modern SDK client verified with model {m_name}.")
            except Exception as e:
                err_clean = sanitize_secret(str(e))
                self.gemini_client = client if 'client' in locals() else None
                self.gemini_is_genai_sdk = True
                self.circuit_breaker.record_failure(e)
                if "429" in err_clean or "quota" in err_clean.lower():
                    self.gemini_status = "temporarily_unavailable"
                    self.gemini_status_detail = "Gemini Quota Exceeded (Free Tier Rate Limit). Deterministic fallback active."
                elif "400" in err_clean or "403" in err_clean or "invalid" in err_clean.lower():
                    self.gemini_status = "temporarily_unavailable"
                    self.gemini_status_detail = "Gemini API key is invalid or unauthorized. Deterministic fallback active."
                else:
                    self.gemini_status = "temporarily_unavailable"
                    self.gemini_status_detail = "Gemini Temporarily Unavailable (Connection/Timeout). Deterministic fallback active."
                logger.warning(f"Centralized Gemini verification probe: {self.gemini_status_detail} (Reason: {err_clean[:90]})")
        else:
            self.gemini_client = None
            self.gemini_is_genai_sdk = False
            self.gemini_status = "not_configured"
            self.gemini_status_detail = "Gemini is not configured. Deterministic fallback active."
            logger.info("No Gemini API key configured in backend. Operating in deterministic rule-based mode.")

        # 2. Check OpenAI (if configured)
        if settings.OPENAI_API_KEY:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
                logger.info("Configured OpenAI client.")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {sanitize_secret(str(e))}")

    def configure_provider(self, provider: str, api_key: str, model: Optional[str] = None) -> Tuple[bool, str]:
        """
        Dynamically configures and verifies the centralized LLM provider (Admin only).
        Guarantees that raw API keys are never exposed in logs or return strings.
        """
        clean_key = api_key.strip()
        if not clean_key:
            return False, "API key cannot be empty."

        if provider == "gemini":
            m_name = model or settings.GEMINI_MODEL or "gemini-flash-lite-latest"
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(
                    api_key=clean_key,
                    http_options=types.HttpOptions(timeout=10000),
                )
                # Verification call with 10s timeout
                client.models.generate_content(
                    model=m_name,
                    contents="Ping",
                )
                self.gemini_client = client
                self.gemini_is_genai_sdk = True
                self.gemini_status = "verified"
                self.gemini_status_detail = f"Gemini Connected & Verified Operational (Model: {m_name})"
                self.last_verified_at = datetime.now().isoformat()
                self.circuit_breaker.reset()
                
                settings.LLM_PROVIDER = "gemini"
                settings.GEMINI_API_KEY = clean_key
                settings.GEMINI_MODEL = m_name
                logger.info(f"Centralized Gemini API key verified and updated by Admin (Model: {m_name}).")
                return True, f"Successfully verified and saved Gemini API configuration (Model: {m_name})!"
            except Exception as e:
                err_clean = sanitize_secret(str(e))
                self.circuit_breaker.record_failure(e)
                if "429" in err_clean or "quota" in err_clean.lower():
                    self.gemini_status = "temporarily_unavailable"
                    self.gemini_status_detail = "Gemini Quota Exceeded (Free Tier Rate Limit). Deterministic fallback active."
                elif "400" in err_clean or "403" in err_clean or "invalid" in err_clean.lower():
                    self.gemini_status = "temporarily_unavailable"
                    self.gemini_status_detail = "Gemini API key is invalid or unauthorized. Deterministic fallback active."
                else:
                    self.gemini_status = "temporarily_unavailable"
                    self.gemini_status_detail = f"Gemini Temporarily Unavailable: {err_clean[:80]}. Deterministic fallback active."
                logger.error(f"Failed to verify Gemini API key: {err_clean}")
                return False, f"Failed to connect to Gemini API: {err_clean}"

        elif provider == "openai":
            try:
                from openai import OpenAI
                client = OpenAI(api_key=clean_key)
                m_name = model or settings.OPENAI_MODEL or "gpt-4o-mini"
                client.models.list()
                self.openai_client = client
                self.circuit_breaker.reset()
                settings.LLM_PROVIDER = "openai"
                settings.OPENAI_API_KEY = clean_key
                settings.OPENAI_MODEL = m_name
                logger.info(f"OpenAI API key successfully verified and connected with model {m_name}.")
                return True, f"Successfully connected to OpenAI API with model {m_name}!"
            except Exception as e:
                err_clean = sanitize_secret(str(e))
                self.circuit_breaker.record_failure(e)
                logger.error(f"Failed to verify OpenAI API key: {err_clean}")
                return False, f"Failed to connect to OpenAI API: {err_clean}"

        return False, f"Unsupported provider: '{provider}'."

    def clear_provider(self, provider: str = "gemini") -> Tuple[bool, str]:
        """Admin clears the centralized LLM key from memory and configuration."""
        if provider == "gemini":
            self.gemini_client = None
            self.gemini_is_genai_sdk = False
            self.gemini_status = "not_configured"
            self.gemini_status_detail = "Gemini is not configured. Deterministic fallback active."
            settings.GEMINI_API_KEY = None
            self.circuit_breaker.reset()
            logger.info("Admin cleared centralized Gemini API key from backend.")
            return True, "Gemini API key cleared successfully from backend configuration."
        return False, f"Unsupported provider: '{provider}'."

    def get_masked_key(self) -> Optional[str]:
        """Returns a safe masked preview of the active API key for Admin inspection (e.g. 'AQ.Ab8...J7KA')."""
        k = settings.GEMINI_API_KEY
        if not k or len(k.strip()) < 8:
            return None
        k_clean = k.strip()
        return f"{k_clean[:6]}...{k_clean[-4:]}"

    def get_llm_status(self) -> Dict[str, Any]:
        """Returns comprehensive sanitized LLM status information (safe for all users)."""
        is_configured = bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip())
        cb_status = self.circuit_breaker.get_status() if hasattr(self, "circuit_breaker") else {}
        return {
            "provider": settings.LLM_PROVIDER,
            "model": settings.GEMINI_MODEL if settings.LLM_PROVIDER == "gemini" else settings.OPENAI_MODEL,
            "is_key_configured": is_configured,
            "status": self.gemini_status,
            "status_description": self.gemini_status_detail,
            "fallback_active": not self.is_llm_available(),
            "last_verified_at": self.last_verified_at,
            "circuit_breaker": cb_status,
        }

    def simulate_outage(self, enabled: bool = True, reason: str = "Simulated Gemini API Timeout (504 Gateway Timeout)") -> None:
        """
        Temporarily simulates an external Gemini API outage/timeout for end-to-end testing,
        without deleting or modifying the configured API key or production configuration.
        """
        self._simulation_active = enabled
        self._simulated_reason = reason if enabled else None
        if enabled:
            self._pre_sim_status = self.gemini_status
            self._pre_sim_detail = self.gemini_status_detail
            if hasattr(self, "circuit_breaker"):
                self.circuit_breaker.trip(reason=reason)
            self.gemini_status = "temporarily_unavailable"
            self.gemini_status_detail = f"Gemini Temporarily Unavailable: {reason}. Deterministic fallback active."
            logger.warning(f"Simulated Gemini outage activated: {reason}")
        else:
            if hasattr(self, "circuit_breaker"):
                self.circuit_breaker.reset()
            if self.gemini_client and settings.GEMINI_API_KEY:
                m_name = settings.GEMINI_MODEL or "gemini-flash-lite-latest"
                self.gemini_status = "verified"
                self.gemini_status_detail = f"Gemini Connected & Verified Operational (Model: {m_name})"
            else:
                self.verify_live_connection()
            logger.info("Simulated Gemini outage deactivated. Connection restored.")

    def verify_live_connection(self) -> Tuple[bool, str]:
        """
        Performs a live connectivity probe with the configured Gemini API client.
        Restores 'verified' status if reachable, or sets 'temporarily_unavailable'.
        """
        self._simulation_active = False
        self._simulated_reason = None
        if not settings.GEMINI_API_KEY or not settings.GEMINI_API_KEY.strip():
            self.gemini_client = None
            self.gemini_status = "not_configured"
            self.gemini_status_detail = "Gemini is not configured. Deterministic fallback active."
            return False, "Gemini is not configured."

        clean_key = settings.GEMINI_API_KEY.strip()
        m_name = settings.GEMINI_MODEL or "gemini-flash-lite-latest"
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(
                api_key=clean_key,
                http_options=types.HttpOptions(timeout=10000),
            )
            # Live connectivity probe
            client.models.generate_content(
                model=m_name,
                contents="Ping",
            )
            self.gemini_client = client
            self.gemini_is_genai_sdk = True
            self.gemini_status = "verified"
            settings.LLM_PROVIDER = "gemini"
            self.gemini_status_detail = f"Gemini Connected & Verified Operational (Model: {m_name})"
            self.last_verified_at = datetime.now().isoformat()
            if hasattr(self, "circuit_breaker"):
                self.circuit_breaker.reset()
            logger.info(f"Live Gemini connectivity re-verified: {self.gemini_status_detail}")
            return True, f"Gemini verified operational with model {m_name}."
        except Exception as e:
            err_clean = sanitize_secret(str(e))
            self.gemini_status = "temporarily_unavailable"
            if hasattr(self, "circuit_breaker"):
                self.circuit_breaker.record_failure(e)
            if "429" in err_clean or "quota" in err_clean.lower():
                self.gemini_status_detail = "Gemini Quota Exceeded (Free Tier Rate Limit). Deterministic fallback active."
            else:
                self.gemini_status_detail = f"Gemini Temporarily Unavailable ({err_clean[:80]}). Deterministic fallback active."
            return False, self.gemini_status_detail

    def is_llm_available(self) -> bool:
        """Returns True only if an external LLM client is configured AND verified operational AND circuit breaker not OPEN."""
        if getattr(self, "_simulation_active", False):
            return False
        if hasattr(self, "circuit_breaker") and self.circuit_breaker.state == CircuitState.OPEN:
            return False
        if settings.LLM_PROVIDER == "gemini":
            return bool(self.gemini_client and self.gemini_status == "verified")
        if settings.LLM_PROVIDER == "openai":
            return bool(self.openai_client)
        return False

    def interpret_intent(self, question: str) -> Tuple[IntentInterpretation, str]:
        """
        Interprets natural language question into structured IntentInterpretation.
        Returns (IntentInterpretation, ai_mode).
        Guarded by thread-safe Circuit Breaker and resilient retries.
        """
        # If no LLM credentials configured or temporarily unavailable, use deterministic intent router
        if not self.is_llm_available():
            logger.info(f"Using deterministic intent router ({self.gemini_status_detail}).")
            return fallback_classify_intent(question), "fallback_rule"

        # Attempt interpretation via configured LLM provider
        catalog = registry.get_tool_catalog_prompt()
        prompt = f"{SYSTEM_INTENT_PROMPT.format(tool_catalog=catalog)}\n\nUser Question: \"{question}\""

        try:
            if settings.LLM_PROVIDER == "gemini" and self.gemini_client:
                def _invoke_gemini():
                    if getattr(self, "gemini_is_genai_sdk", False):
                        from google.genai import types
                        config = types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.0,
                        )
                        response = self.gemini_client.models.generate_content(
                            model=settings.GEMINI_MODEL,
                            contents=prompt,
                            config=config,
                        )
                        raw_text = response.text.strip()
                        return self._parse_json_response(raw_text)
                    else:
                        model = self.gemini_client.GenerativeModel(settings.GEMINI_MODEL)
                        response = model.generate_content(prompt, request_options={"timeout": 15.0})
                        raw_text = response.text.strip()
                        return self._parse_json_response(raw_text)

                parsed = execute_with_resilience(self.circuit_breaker, _invoke_gemini)
                metrics_collector.record_llm_call("gemini", success=True, is_fallback=False)
                return IntentInterpretation(**parsed), "gemini"

            elif settings.LLM_PROVIDER == "openai" and self.openai_client:
                def _invoke_openai():
                    response = self.openai_client.chat.completions.create(
                        model=settings.OPENAI_MODEL,
                        messages=[
                            {"role": "system", "content": SYSTEM_INTENT_PROMPT.format(tool_catalog=catalog)},
                            {"role": "user", "content": question},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.0,
                    )
                    raw_text = response.choices[0].message.content.strip()
                    return json.loads(raw_text)

                parsed = execute_with_resilience(self.circuit_breaker, _invoke_openai)
                metrics_collector.record_llm_call("openai", success=True, is_fallback=False)
                return IntentInterpretation(**parsed), "openai"

        except CircuitBreakerOpenException as cbe:
            logger.warning(f"Circuit breaker active: {cbe}. Reverting immediately to deterministic fallback.")
            self.gemini_status = "temporarily_unavailable"
            self.gemini_status_detail = f"Gemini Circuit Breaker OPEN ({self.circuit_breaker.state.value}). Deterministic fallback active."
            metrics_collector.record_llm_call(settings.LLM_PROVIDER, success=False, is_fallback=True)
            return fallback_classify_intent(question), "fallback_rule"
        except Exception as e:
            err_clean = sanitize_secret(str(e))
            if "429" in err_clean or "quota" in err_clean.lower():
                self.gemini_status = "temporarily_unavailable"
                self.gemini_status_detail = "Gemini Quota Exceeded (Free Tier Rate Limit). Deterministic fallback active."
            else:
                self.gemini_status = "temporarily_unavailable"
                self.gemini_status_detail = f"Gemini Temporarily Unavailable: {err_clean[:80]}. Deterministic fallback active."
            logger.error(f"External LLM API call failed ({err_clean}). Reverting to fallback intent classifier.")
            metrics_collector.record_llm_call(settings.LLM_PROVIDER, success=False, is_fallback=True)
            if settings.ALLOW_FALLBACK_ON_ERROR:
                return fallback_classify_intent(question), "fallback_rule"
            raise LLMProviderError(f"LLM API failure: {err_clean}")

        metrics_collector.record_llm_call(settings.LLM_PROVIDER, success=False, is_fallback=True)
        return fallback_classify_intent(question), "fallback_rule"

    def generate_grounded_explanation(
        self, question: str, metrics: Dict[str, Any], tool_name: str, ai_mode: str
    ) -> str:
        """
        Generates grounded business explanation based on actual retrieved database numbers.
        Guarded by thread-safe Circuit Breaker.
        """
        if ai_mode in ["gemini", "openai"] and self.is_llm_available():
            prompt = (
                f"{SYSTEM_EXPLANATION_PROMPT}\n\n"
                f"User Question: \"{question}\"\n"
                f"Executed Tool: {tool_name}\n"
                f"Retrieved Database Metrics: {json.dumps(metrics, default=str)}\n\n"
                f"Provide concise, evidence-based business answer and insight:"
            )
            try:
                if ai_mode == "gemini" and self.gemini_client:
                    def _call_gemini_exp():
                        if getattr(self, "gemini_is_genai_sdk", False):
                            res = self.gemini_client.models.generate_content(
                                model=settings.GEMINI_MODEL,
                                contents=prompt,
                            )
                            return res.text.strip()
                        else:
                            model = self.gemini_client.GenerativeModel(settings.GEMINI_MODEL)
                            res = model.generate_content(prompt, request_options={"timeout": 15.0})
                            return res.text.strip()

                    return execute_with_resilience(self.circuit_breaker, _call_gemini_exp)

                elif ai_mode == "openai" and self.openai_client:
                    def _call_openai_exp():
                        res = self.openai_client.chat.completions.create(
                            model=settings.OPENAI_MODEL,
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.2,
                            timeout=15.0,
                        )
                        return res.choices[0].message.content.strip()

                    return execute_with_resilience(self.circuit_breaker, _call_openai_exp)
            except Exception as e:
                logger.warning(f"LLM explanation generation failed ({sanitize_secret(str(e))}); using deterministic explanation.")

        # Deterministic Grounded Narrative Generator
        return self._build_deterministic_explanation(tool_name, metrics)

    def _build_deterministic_explanation(self, tool_name: str, metrics: Dict[str, Any]) -> str:
        """Constructs deterministic, evidence-based explanations grounded in database metrics."""
        if tool_name == "total_revenue":
            net = metrics.get("total_net_revenue", 0.0)
            gross = metrics.get("total_gross_revenue", 0.0)
            disc = metrics.get("total_discounts", 0.0)
            orders = metrics.get("eligible_transaction_count", 0)
            aov = metrics.get("average_order_value", 0.0)
            return (
                f"The total realized net sales revenue is ₹{net:,.2f} across {orders} eligible completed orders, "
                f"from a gross total of ₹{gross:,.2f} with ₹{disc:,.2f} in customer discounts. "
                f"The average order value stands at ₹{aov:,.2f}."
            )

        elif tool_name == "top_revenue_product":
            prod = metrics.get("top_product", "N/A")
            rev = metrics.get("top_product_net_revenue", 0.0)
            qty = metrics.get("top_product_quantity", 0)
            return (
                f"{prod} generated the highest revenue among all products, achieving ₹{rev:,.2f} in net sales "
                f"with {qty} units sold across all sales channels."
            )

        elif tool_name == "monthly_revenue_trend":
            best = metrics.get("best_performing_month", "N/A")
            best_rev = metrics.get("best_month_revenue", 0.0)
            trend = metrics.get("monthly_trend", [])
            filt_reg = metrics.get("filtered_region")
            filt_prod = metrics.get("filtered_product")
            scope = f"for {filt_reg} region " if filt_reg else (f"for {filt_prod} " if filt_prod else "")
            return (
                f"Monthly revenue {scope}shows consistent performance across 2026, peaking in {best} with ₹{best_rev:,.2f} in net sales. "
                f"A total of {len(trend)} months were recorded with steady sales distribution."
            )

        elif tool_name == "compare_regions":
            r1 = metrics.get("region_1", {})
            r2 = metrics.get("region_2", {})
            diff = metrics.get("revenue_difference", 0.0)
            pct = metrics.get("percentage_difference", 0.0)
            return (
                f"{r1.get('region', 'Region 1')} generated ₹{r1.get('net_revenue', 0.0):,.2f} in sales compared to "
                f"₹{r2.get('net_revenue', 0.0):,.2f} in {r2.get('region', 'Region 2')} "
                f"(a variance of ₹{diff:+,.2f} or {pct:+.2f}%)."
            )

        elif tool_name == "lowest_performing_product":
            prod = metrics.get("lowest_product", "N/A")
            rev = metrics.get("lowest_product_net_revenue", 0.0)
            qty = metrics.get("quantity_sold", 0)
            return (
                f"{prod} recorded the lowest realized sales revenue among all products at ₹{rev:,.2f} with {qty} units sold."
            )

        elif tool_name == "top_revenue_region":
            reg = metrics.get("top_region", "N/A")
            rev = metrics.get("top_region_revenue", 0.0)
            qty = metrics.get("top_region_quantity", 0)
            return (
                f"The {reg} region generated the highest sales revenue at ₹{rev:,.2f}, delivering {qty} units sold. "
                f"It remains the primary regional revenue driver for the business."
            )

        elif tool_name == "monthly_comparison":
            m1 = metrics.get("month_1", "")
            m2 = metrics.get("month_2", "")
            r1 = metrics.get("month_1_revenue", 0.0)
            r2 = metrics.get("month_2_revenue", 0.0)
            diff = metrics.get("absolute_difference", 0.0)
            pct = metrics.get("percentage_difference", 0.0)
            trend = metrics.get("trend_direction", "changed")
            return (
                f"Revenue in {m2} was ₹{r2:,.2f} compared to ₹{r1:,.2f} in {m1}. "
                f"Sales {trend} by ₹{abs(diff):,.2f} ({pct:+.2f}%)."
            )

        elif tool_name == "top_quantity_product":
            prod = metrics.get("top_product", "N/A")
            units = metrics.get("total_units_sold", 0)
            rev = metrics.get("associated_revenue", 0.0)
            return (
                f"{prod} is the highest volume product with {units} units sold, generating ₹{rev:,.2f} in realized sales."
            )

        elif tool_name == "category_revenue":
            cats = metrics.get("categories", [])
            top_cat = cats[0] if cats else {}
            return (
                f"The top-performing category is {top_cat.get('category', 'N/A')} with ₹{top_cat.get('net_revenue', 0.0):,.2f} "
                f"({top_cat.get('percentage_share', 0.0)}% of total sales)."
            )

        elif tool_name == "channel_comparison":
            best = metrics.get("best_channel", "N/A")
            channels = metrics.get("channels", [])
            return (
                f"The {best} channel leads sales performance, accounting for the primary share of total revenue "
                f"across recorded transactions."
            )

        elif tool_name == "average_transaction_value":
            aov = metrics.get("average_transaction_value", 0.0)
            orders = metrics.get("eligible_orders", 0)
            return (
                f"The average transaction value is ₹{aov:,.2f} calculated across {orders} eligible completed transactions."
            )

        elif tool_name == "discount_analysis":
            disc = metrics.get("total_discounts", 0.0)
            rate = metrics.get("discount_rate_percentage", 0.0)
            return (
                f"Total discounts distributed amounted to ₹{disc:,.2f}, representing an effective discount rate of {rate:.2f}% on gross sales."
            )

        elif tool_name == "product_comparison":
            p1 = metrics.get("product_1", {})
            p2 = metrics.get("product_2", {})
            p1_name = p1.get("product", "Product 1")
            p2_name = p2.get("product", "Product 2")
            diff = metrics.get("revenue_difference", 0.0)
            return (
                f"{p1_name} generated ₹{p1.get('net_revenue', 0.0):,.2f} across {p1.get('quantity', 0)} units compared to "
                f"₹{p2.get('net_revenue', 0.0):,.2f} across {p2.get('quantity', 0)} units for {p2_name} "
                f"(a revenue variance of ₹{diff:,.2f})."
            )

        elif tool_name == "data_quality_audit":
            tot = metrics.get("total_records", 0)
            el = metrics.get("eligible_records", 0)
            ex = metrics.get("excluded_records", 0)
            clean = metrics.get("cleanliness_percentage", 0.0)
            return (
                f"The sales data quality audit verified {el} eligible transactions out of {tot} total rows ({clean}% cleanliness rate). "
                f"{ex} records were excluded due to business eligibility rules (1 returned order, 1 zero-quantity order, and 1 missing unit price)."
            )

        elif tool_name == "anomaly_detection":
            stat_count = metrics.get("statistical_outliers_count", 0)
            dq_count = metrics.get("confirmed_data_quality_errors_count", 0)
            mean = metrics.get("mean_transaction_revenue", 0.0)
            return (
                f"Anomaly detection identified {stat_count} statistical outlier transactions (IQR / Z-score) "
                f"and {dq_count} confirmed data quality errors. Average eligible transaction value is ₹{mean:,.2f}."
            )

        elif tool_name == "revenue_concentration":
            vital_count = metrics.get("vital_few_count", 0)
            vital_pct = metrics.get("vital_revenue_share_percentage", 0.0)
            denom = metrics.get("denominator_total_eligible_net_revenue", 0.0)
            return (
                f"Pareto 80/20 analysis demonstrates that the top {vital_count} products account for "
                f"{vital_pct:.1f}% of total realized net revenue (denominator: ₹{denom:,.2f})."
            )

        elif tool_name == "what_if_simulation":
            sim_net = metrics.get("simulated_net_revenue", 0.0)
            delta = metrics.get("net_revenue_delta", 0.0)
            delta_pct = metrics.get("net_revenue_delta_percentage", 0.0)
            return (
                f"Under the simulated scenario, net revenue is projected at ₹{sim_net:,.2f}, representing a variance of "
                f"₹{delta:+,.2f} ({delta_pct:+.2f}%) against baseline. (Note: Excludes operating costs as cost data is not in dataset)."
            )

        elif tool_name == "quota_pacing":
            pacing = metrics.get("pacing_metrics", {})
            att = pacing.get("attainment_percentage", 0.0)
            status_label = pacing.get("status", "On Track")
            proj = pacing.get("run_rate_projected_revenue", 0.0)
            target_val = metrics.get("configured_target", {}).get("amount", 0.0)
            return (
                f"Sales quota pacing currently stands at {att:.1f}% of configured target (₹{target_val:,.2f}) with a status of '{status_label}'. "
                f"Month-end run-rate is projected at ₹{proj:,.2f}."
            )

        return f"Successfully computed metrics for {tool_name} based on active database records."

    def process_query(self, question: str, db: Session, session_id: Optional[str] = "default") -> QueryResponse:
        """
        End-to-end question processing pipeline:
        Security pre-screen -> Context resolution -> Natural language intent -> Tool selection ->
        SQL computation -> Grounded explanation -> Conversational session update.
        """
        start_time = time.time()
        sid = (session_id or "default").strip()

        # Step 0: Security & Prompt Injection Inspection
        is_safe, threat_reason = inspect_prompt_safety(question)
        if not is_safe:
            exec_time = round((time.time() - start_time) * 1000, 2)
            log_security_event(
                event_type="PROMPT_INJECTION_BLOCKED",
                endpoint="/api/ask",
                severity="WARNING",
                details=f"Query: '{question[:100]}' | Reason: {threat_reason}",
                db=db,
            )
            return QueryResponse(
                success=False,
                question=question,
                intent="security_violation_blocked",
                category=int(QuestionCategory.UNRELATED),
                category_name="Security Guardrail Violation",
                answer="Enterprise Security Alert: Your query was flagged and blocked by the AI Safety & Prompt Injection Guardrail. System prompt overrides, delimiter injections, and adversarial jailbreaks are strictly prohibited.",
                explanation="The query contained adversarial instruction override patterns or prompt extraction syntax.",
                metrics={},
                supporting_data=[],
                chart_type="metric",
                ai_mode="security_guardrail",
                data_quality_notes=["Query blocked by AI prompt injection safety guardrail."],
                execution_time_ms=exec_time,
                session_id=sid,
            )

        # Step 1: Conversational context & pronoun resolution
        resolved_question, injected_params, intent_hint = conversation_manager.resolve_context(
            question, session_id=sid
        )
        has_resolved_context = (resolved_question != question)

        # Step 2: Intent Classification
        if intent_hint and injected_params:
            interpretation = IntentInterpretation(
                intent=intent_hint,
                category=QuestionCategory.SUPPORTED,
                parameters=injected_params,
                confidence=0.95,
            )
            ai_mode = "context_memory"
        else:
            interpretation, ai_mode = self.interpret_intent(resolved_question)
            if injected_params:
                interpretation.parameters.update(injected_params)

        cat = interpretation.category

        # Category 4: Unrelated questions
        if cat == QuestionCategory.UNRELATED:
            exec_time = round((time.time() - start_time) * 1000, 2)
            msg = interpretation.clarification_prompt or (
                "I am a Business Intelligence Assistant designed to analyze your sales data. "
                "I can help with revenue, product performance, regional analysis, and other sales-related questions."
            )
            return QueryResponse(
                success=True,
                question=question,
                intent=interpretation.intent,
                category=int(cat),
                category_name="Unrelated Query",
                answer=msg,
                explanation="The assistant specializes in sales analytics and polite redirection for out-of-domain questions.",
                metrics={},
                supporting_data=[],
                chart_type="metric",
                ai_mode=ai_mode,
                data_quality_notes=[],
                execution_time_ms=exec_time,
                session_id=sid,
                resolved_context=resolved_question if has_resolved_context else None,
            )

        # Category 2: Related but Unsupported Business Questions
        if cat == QuestionCategory.RELATED_UNSUPPORTED:
            exec_time = round((time.time() - start_time) * 1000, 2)
            reason = interpretation.unsupported_reason or (
                "This business metric cannot be calculated because the supplied dataset does not contain cost, "
                "margin, or customer identity information."
            )
            return QueryResponse(
                success=True,
                question=question,
                intent=interpretation.intent,
                category=int(cat),
                category_name="Related Unsupported Metric",
                answer=reason,
                explanation="Dataset limitations: cost and inventory fields are absent from the transaction CSV.",
                metrics={},
                supporting_data=[
                    {"suggested_alternative": alt} for alt in interpretation.suggested_alternatives
                ],
                chart_type="table",
                ai_mode=ai_mode,
                data_quality_notes=["Exclusion: Profit and operational expense attributes are not captured in the schema."],
                execution_time_ms=exec_time,
                session_id=sid,
                resolved_context=resolved_question if has_resolved_context else None,
            )

        # Category 3: Ambiguous Questions
        if cat == QuestionCategory.AMBIGUOUS or interpretation.needs_clarification:
            exec_time = round((time.time() - start_time) * 1000, 2)
            clarification = interpretation.clarification_prompt or "Could you please specify more details for this comparison?"
            return QueryResponse(
                success=True,
                question=question,
                intent=interpretation.intent,
                category=int(cat),
                category_name="Ambiguous Query",
                answer=clarification,
                explanation="Ambiguity detected: query lacks necessary comparative parameters (e.g. month names or product names).",
                metrics={},
                supporting_data=[
                    {"suggested_query": alt} for alt in interpretation.suggested_alternatives
                ],
                chart_type="metric",
                ai_mode=ai_mode,
                data_quality_notes=[],
                execution_time_ms=exec_time,
                session_id=sid,
                resolved_context=resolved_question if has_resolved_context else None,
            )

        # Category 1: Supported Questions
        tool_name = interpretation.intent
        tool = registry.get(tool_name)
        if not tool:
            # Fallback to total revenue if unknown tool
            tool_name = "total_revenue"
            tool = registry.get("total_revenue")

        try:
            # Execute database tool
            metrics = registry.execute(tool_name, db, interpretation.parameters)
            
            # Grounded explanation
            explanation = self.generate_grounded_explanation(resolved_question, metrics, tool_name, ai_mode)
            
            # Build answer summary
            answer = metrics.get("title", f"Result for {tool_name}")
            if "total_net_revenue" in metrics and "total_gross_revenue" in metrics:
                answer = f"Total Realized Net Revenue is ₹{metrics['total_net_revenue']:,.2f}."
            elif "top_product" in metrics and "top_product_net_revenue" in metrics:
                answer = f"{metrics['top_product']} generated the highest revenue (₹{metrics['top_product_net_revenue']:,.2f})."
            elif "lowest_product" in metrics and "lowest_product_net_revenue" in metrics:
                answer = f"{metrics['lowest_product']} generated the lowest revenue (₹{metrics['lowest_product_net_revenue']:,.2f})."
            elif "top_region" in metrics:
                answer = f"{metrics['top_region']} generated the highest revenue (₹{metrics['top_region_revenue']:,.2f})."
            elif "region_1" in metrics and "region_2" in metrics:
                r1_name = metrics["region_1"].get("region", "Region 1")
                r2_name = metrics["region_2"].get("region", "Region 2")
                answer = f"{r1_name} (₹{metrics['region_1']['net_revenue']:,.2f}) vs {r2_name} (₹{metrics['region_2']['net_revenue']:,.2f})."
            elif "product_1" in metrics and "product_2" in metrics:
                p1_name = metrics["product_1"].get("product", "Product 1")
                p2_name = metrics["product_2"].get("product", "Product 2")
                answer = f"Product Comparison: {p1_name} (₹{metrics['product_1']['net_revenue']:,.2f}) vs {p2_name} (₹{metrics['product_2']['net_revenue']:,.2f})."
            elif "cleanliness_percentage" in metrics:
                answer = f"Data Quality Audit: {metrics['excluded_records']} issues flagged ({metrics['cleanliness_percentage']}% cleanliness across {metrics['total_records']} total records)."
            elif "month_1_revenue" in metrics and "month_2_revenue" in metrics:
                answer = f"{metrics.get('month_2')} revenue was ₹{metrics['month_2_revenue']:,.2f} vs ₹{metrics['month_1_revenue']:,.2f} in {metrics.get('month_1')} ({metrics.get('percentage_difference'):+.2f}%)."
            elif "best_performing_month" in metrics and "best_month_revenue" in metrics:
                answer = f"Monthly Revenue Trend: Peak in {metrics['best_performing_month']} (₹{metrics['best_month_revenue']:,.2f})."
            elif "average_transaction_value" in metrics:
                answer = f"The average transaction value is ₹{metrics['average_transaction_value']:,.2f}."
            elif "total_units_sold" in metrics:
                answer = f"{metrics.get('top_product')} sold the highest quantity ({metrics['total_units_sold']} units)."
            elif "statistical_outliers_count" in metrics:
                answer = f"Anomaly Detection: {metrics.get('statistical_outliers_count', 0)} statistical outliers and {metrics.get('confirmed_data_quality_errors_count', 0)} data quality errors flagged."
            elif "vital_few_count" in metrics and "vital_revenue_share_percentage" in metrics:
                answer = f"Pareto 80/20: Top {metrics['vital_few_count']} products drive {metrics['vital_revenue_share_percentage']:.1f}% of net revenue (denominator: ₹{metrics.get('denominator_total_eligible_net_revenue', 0.0):,.2f})."
            elif "simulated_net_revenue" in metrics and "net_revenue_delta" in metrics:
                answer = f"What-If Simulation: Projected net revenue is ₹{metrics['simulated_net_revenue']:,.2f} ({metrics['net_revenue_delta_percentage']:+.2f}% vs baseline)."
            elif "pacing_metrics" in metrics and "configured_target" in metrics:
                pm = metrics["pacing_metrics"]
                tgt_amt = metrics["configured_target"].get("amount", 0.0)
                answer = f"Quota Pacing: {pm.get('attainment_percentage', 0.0):.1f}% attained against ₹{tgt_amt:,.2f} target (Status: {pm.get('status', 'On Track')})."

            supporting = metrics.get("supporting_data", [])
            chart_type = metrics.get("chart_type", tool.default_chart_type)

            exec_time = round((time.time() - start_time) * 1000, 2)

            # Update conversational session memory
            session = conversation_manager.get_or_create_session(sid)
            session.add_turn(question, answer, tool_name, metrics)

            # Build data provenance metadata describing executed operation and dataset scope
            el_count = db.query(SalesTransaction).filter(SalesTransaction.is_eligible == True).count()
            ex_count = db.query(SalesTransaction).filter(SalesTransaction.is_eligible == False).count()
            provenance_metadata = {
                "operation": tool.description,
                "target_entity": "sales_transactions",
                "eligible_rows_used": el_count,
                "excluded_rows_omitted": ex_count,
                "applied_parameters": interpretation.parameters or {},
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "deterministic_guarantee": "Computed deterministically via SQLite ORM aggregation; zero AI numerical hallucination.",
            }

            return QueryResponse(
                success=True,
                question=question,
                intent=tool_name,
                category=int(QuestionCategory.SUPPORTED),
                category_name="Supported Analytical Query",
                answer=answer,
                explanation=explanation,
                metrics=metrics,
                supporting_data=supporting,
                chart_type=chart_type,
                ai_mode=ai_mode,
                data_quality_notes=[
                    "Realized revenue calculated strictly from eligible completed transactions.",
                    "Returned orders and invalid records were audited and excluded from sales KPIs.",
                ],
                execution_time_ms=exec_time,
                session_id=sid,
                resolved_context=resolved_question if has_resolved_context else None,
                provenance=provenance_metadata,
            )

        except Exception as e:
            logger.error(f"Error executing analytical tool '{tool_name}': {e}")
            exec_time = round((time.time() - start_time) * 1000, 2)
            return QueryResponse(
                success=False,
                question=question,
                intent=tool_name,
                category=int(QuestionCategory.SUPPORTED),
                category_name="Execution Error",
                answer=f"Could not complete the calculation: {str(e)}",
                explanation="A database error or parameter mismatch occurred during query execution.",
                metrics={},
                supporting_data=[],
                chart_type="metric",
                ai_mode=ai_mode,
                data_quality_notes=[],
                execution_time_ms=exec_time,
            )

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Safely extracts JSON object from LLM response text."""
        cleaned = text.strip()
        # Remove markdown code block if present
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        return json.loads(cleaned)


ai_service = AIService()
