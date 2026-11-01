"""
Conversational Session Memory and Context Resolution Module
-----------------------------------------------------------
Maintains multi-turn conversation state, tracks entities (products, regions, months),
and resolves pronouns/follow-ups (e.g., "Show its monthly trend", "Compare it with North").
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

KNOWN_REGIONS = ["north", "south", "east", "west"]
KNOWN_PRODUCTS = [
    "monitor", "desk", "office chair", "usb-c hub",
    "wireless mouse", "keyboard", "laptop stand"
]


@dataclass
class ConversationSession:
    session_id: str
    last_region: Optional[str] = None
    last_product: Optional[str] = None
    last_months: List[str] = field(default_factory=list)
    last_category: Optional[str] = None
    last_intent: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def add_turn(
        self,
        question: str,
        answer: str,
        intent: str,
        metrics: Dict[str, Any],
    ) -> None:
        """Appends a turn to history and updates entity references."""
        self.updated_at = time.time()
        self.last_intent = intent
        
        # Extract and update active entities from results
        if "top_region" in metrics:
            self.last_region = metrics["top_region"]
        elif "region" in metrics:
            self.last_region = metrics["region"]

        if "top_product" in metrics:
            self.last_product = metrics["top_product"]
        elif "product" in metrics:
            self.last_product = metrics["product"]

        if "month_1" in metrics and "month_2" in metrics:
            self.last_months = [metrics["month_1"], metrics["month_2"]]
        elif "best_performing_month" in metrics:
            self.last_months = [metrics["best_performing_month"]]

        self.history.append({
            "question": question,
            "answer": answer,
            "intent": intent,
            "timestamp": self.updated_at,
        })
        # Keep maximum 20 turns to prevent unbounded growth
        if len(self.history) > 20:
            self.history = self.history[-20:]


class ConversationManager:
    """Manages active conversation sessions and resolves context references."""

    def __init__(self, ttl_seconds: int = 3600):
        self._sessions: Dict[str, ConversationSession] = {}
        self.ttl_seconds = ttl_seconds

    def get_or_create_session(self, session_id: Optional[str] = None) -> ConversationSession:
        sid = (session_id or "default").strip()
        self._cleanup_expired_sessions()
        if sid not in self._sessions:
            self._sessions[sid] = ConversationSession(session_id=sid)
        return self._sessions[sid]

    def _cleanup_expired_sessions(self) -> None:
        """Removes sessions older than TTL."""
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if now - s.updated_at > self.ttl_seconds]
        for sid in expired:
            del self._sessions[sid]

    def resolve_context(
        self,
        question: str,
        session_id: Optional[str] = "default",
    ) -> Tuple[str, Dict[str, Any], Optional[str]]:
        """
        Inspects the question and recent session state.
        If pronouns or follow-up expressions are detected, resolves antecedents.
        
        Returns:
            (resolved_question, injected_parameters, resolved_intent_hint)
        """
        session = self.get_or_create_session(session_id)
        clean = question.strip()
        lowered = clean.lower()
        injected_params: Dict[str, Any] = {}
        intent_hint: Optional[str] = None
        resolved_question = clean

        # Check for explicit region mentions in the query
        found_regions = [r.title() for r in KNOWN_REGIONS if r in lowered]
        found_products = [p.title() for p in KNOWN_PRODUCTS if p in lowered]

        if found_regions and not session.last_region:
            session.last_region = found_regions[0]
        if found_products and not session.last_product:
            session.last_product = found_products[0]

        # Case 1: "Compare it with <Region>" or "Compare with <Region>"
        compare_region_match = re.search(
            r"\bcompare (?:it|this|that|sales)?\s*(?:with|to|and)\s*([a-zA-Z]+)\b",
            lowered,
            re.IGNORECASE,
        )
        if compare_region_match:
            target_token = compare_region_match.group(1).strip().lower()
            if target_token in KNOWN_REGIONS and session.last_region:
                r1 = session.last_region
                r2 = target_token.title()
                injected_params = {"region_1": r1, "region_2": r2}
                intent_hint = "compare_regions"
                resolved_question = f"Compare {r1} and {r2}."
                logger.info(f"Resolved contextual region comparison: {r1} vs {r2}")
                return resolved_question, injected_params, intent_hint

        # Case 2: "Show its monthly trend" or "Show its trend" or "monthly trend for it"
        trend_pronoun_match = re.search(
            r"\b(?:show|what is|get)?\s*(?:its|it's|that|this)\s*(?:monthly\s+)?trend\b",
            lowered,
            re.IGNORECASE,
        )
        if trend_pronoun_match or ("its trend" in lowered) or ("its monthly trend" in lowered):
            if session.last_region:
                injected_params = {"region": session.last_region}
                intent_hint = "monthly_revenue_trend"
                resolved_question = f"What is the monthly revenue trend for {session.last_region} region?"
                logger.info(f"Resolved contextual trend for region: {session.last_region}")
                return resolved_question, injected_params, intent_hint
            elif session.last_product:
                injected_params = {"product": session.last_product}
                intent_hint = "monthly_revenue_trend"
                resolved_question = f"What is the monthly revenue trend for {session.last_product}?"
                logger.info(f"Resolved contextual trend for product: {session.last_product}")
                return resolved_question, injected_params, intent_hint

        # Case 3: "What about <Product>?" or "How about <Product>?"
        how_about_prod = re.search(r"\b(?:what|how)\s+about\s+([a-zA-Z\s-]+)\??$", lowered)
        if how_about_prod:
            target = how_about_prod.group(1).strip()
            for p in KNOWN_PRODUCTS:
                if p in target:
                    resolved_question = f"What was the revenue and sales for {p.title()}?"
                    injected_params = {"product": p.title()}
                    intent_hint = "product_comparison" if session.last_product else "top_revenue_product"
                    return resolved_question, injected_params, intent_hint

        return resolved_question, injected_params, intent_hint


# Global conversation manager instance
conversation_manager = ConversationManager()
