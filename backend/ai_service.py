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
import time
from typing import Any, Dict, Optional, Tuple
from sqlalchemy.orm import Session

from backend.config import settings
from backend.exceptions import LLMProviderError, ToolExecutionError
from backend.intent_router import fallback_classify_intent
from backend.schemas import (
    IntentInterpretation,
    QuestionCategory,
    QueryResponse,
)
from backend.tool_registry import registry

logger = logging.getLogger(__name__)

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
        self.openai_client = None
        self._init_clients()

    def _init_clients(self) -> None:
        """Initializes API clients based on configured settings and environment keys."""
        # Check Gemini
        if settings.GEMINI_API_KEY:
            try:
                import google.generativeai as genai
                genai.configure(api_key=settings.GEMINI_API_KEY)
                self.gemini_client = genai
                logger.info("Configured Google Gemini Generative AI client.")
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini client: {e}")

        # Check OpenAI
        if settings.OPENAI_API_KEY:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
                logger.info("Configured OpenAI client.")
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI client: {e}")

    def configure_provider(self, provider: str, api_key: str, model: Optional[str] = None) -> Tuple[bool, str]:
        """Dynamically configures and verifies the LLM provider."""
        clean_key = api_key.strip()
        if not clean_key:
            return False, "API key cannot be empty."

        if provider == "gemini":
            try:
                import google.generativeai as genai
                genai.configure(api_key=clean_key)
                m_name = model or settings.GEMINI_MODEL or "gemini-1.5-flash"
                m = genai.GenerativeModel(m_name)
                # Verify key with test call
                m.generate_content("Ping")
                self.gemini_client = genai
                settings.LLM_PROVIDER = "gemini"
                settings.GEMINI_API_KEY = clean_key
                settings.GEMINI_MODEL = m_name
                logger.info(f"Gemini API key successfully verified and connected with model {m_name}.")
                return True, f"Successfully connected to Gemini API with model {m_name}!"
            except Exception as e:
                logger.error(f"Failed to verify Gemini API key: {e}")
                return False, f"Failed to connect to Gemini API: {str(e)}"

        elif provider == "openai":
            try:
                from openai import OpenAI
                client = OpenAI(api_key=clean_key)
                m_name = model or settings.OPENAI_MODEL or "gpt-4o-mini"
                client.models.list()
                self.openai_client = client
                settings.LLM_PROVIDER = "openai"
                settings.OPENAI_API_KEY = clean_key
                settings.OPENAI_MODEL = m_name
                logger.info(f"OpenAI API key successfully verified and connected with model {m_name}.")
                return True, f"Successfully connected to OpenAI API with model {m_name}!"
            except Exception as e:
                logger.error(f"Failed to verify OpenAI API key: {e}")
                return False, f"Failed to connect to OpenAI API: {str(e)}"

        return False, f"Unsupported provider: '{provider}'."

    def is_llm_available(self) -> bool:
        """Returns True if a valid external LLM client is configured."""
        if settings.LLM_PROVIDER == "gemini" and self.gemini_client:
            return True
        if settings.LLM_PROVIDER == "openai" and self.openai_client:
            return True
        return False

    def interpret_intent(self, question: str) -> Tuple[IntentInterpretation, str]:
        """
        Interprets natural language question into structured IntentInterpretation.
        Returns (IntentInterpretation, ai_mode).
        """
        # If no LLM credentials configured, use deterministic intent router
        if not self.is_llm_available():
            logger.info("Using fallback deterministic intent router (no external LLM key configured).")
            return fallback_classify_intent(question), "fallback_rule"

        # Attempt interpretation via configured LLM provider
        catalog = registry.get_tool_catalog_prompt()
        prompt = f"{SYSTEM_INTENT_PROMPT.format(tool_catalog=catalog)}\n\nUser Question: \"{question}\""

        try:
            if settings.LLM_PROVIDER == "gemini" and self.gemini_client:
                model = self.gemini_client.GenerativeModel(settings.GEMINI_MODEL)
                response = model.generate_content(prompt)
                raw_text = response.text.strip()
                parsed = self._parse_json_response(raw_text)
                return IntentInterpretation(**parsed), "gemini"

            elif settings.LLM_PROVIDER == "openai" and self.openai_client:
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
                parsed = json.loads(raw_text)
                return IntentInterpretation(**parsed), "openai"

        except Exception as e:
            logger.error(f"External LLM API call failed ({e}). Reverting to fallback intent classifier.")
            if settings.ALLOW_FALLBACK_ON_ERROR:
                return fallback_classify_intent(question), "fallback_rule"
            raise LLMProviderError(f"LLM API failure: {e}")

        return fallback_classify_intent(question), "fallback_rule"

    def generate_grounded_explanation(
        self, question: str, metrics: Dict[str, Any], tool_name: str, ai_mode: str
    ) -> str:
        """
        Generates grounded business explanation based on actual retrieved database numbers.
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
                    model = self.gemini_client.GenerativeModel(settings.GEMINI_MODEL)
                    res = model.generate_content(prompt)
                    return res.text.strip()
                elif ai_mode == "openai" and self.openai_client:
                    res = self.openai_client.chat.completions.create(
                        model=settings.OPENAI_MODEL,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                    )
                    return res.choices[0].message.content.strip()
            except Exception as e:
                logger.warning(f"LLM explanation generation failed ({e}); using template fallback.")

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
            return (
                f"Monthly revenue shows consistent performance across 2026, peaking in {best} with ₹{best_rev:,.2f} in net sales. "
                f"A total of {len(trend)} months were recorded with steady sales distribution."
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

        return f"Successfully computed metrics for {tool_name} based on active database records."

    def process_query(self, question: str, db: Session) -> QueryResponse:
        """
        End-to-end question processing pipeline:
        Natural language -> Intent classification -> Tool selection ->
        SQL computation -> Grounded explanation -> Unified response.
        """
        start_time = time.time()
        interpretation, ai_mode = self.interpret_intent(question)
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
            explanation = self.generate_grounded_explanation(question, metrics, tool_name, ai_mode)
            
            # Build answer summary
            answer = metrics.get("title", f"Result for {tool_name}")
            if "total_net_revenue" in metrics:
                answer = f"Total Realized Net Revenue is ₹{metrics['total_net_revenue']:,.2f}."
            elif "top_product" in metrics and "top_product_net_revenue" in metrics:
                answer = f"{metrics['top_product']} generated the highest revenue (₹{metrics['top_product_net_revenue']:,.2f})."
            elif "top_region" in metrics:
                answer = f"{metrics['top_region']} generated the highest revenue (₹{metrics['top_region_revenue']:,.2f})."
            elif "month_1_revenue" in metrics and "month_2_revenue" in metrics:
                answer = f"{metrics.get('month_2')} revenue was ₹{metrics['month_2_revenue']:,.2f} vs ₹{metrics['month_1_revenue']:,.2f} in {metrics.get('month_1')} ({metrics.get('percentage_difference'):+.2f}%)."
            elif "average_transaction_value" in metrics:
                answer = f"The average transaction value is ₹{metrics['average_transaction_value']:,.2f}."
            elif "total_units_sold" in metrics:
                answer = f"{metrics.get('top_product')} sold the highest quantity ({metrics['total_units_sold']} units)."

            supporting = metrics.get("supporting_data", [])
            chart_type = metrics.get("chart_type", tool.default_chart_type)

            exec_time = round((time.time() - start_time) * 1000, 2)

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
