"""
Security, Guardrails, and Rate Limiting Module
---------------------------------------------
Implements enterprise application defense mechanisms:
1. Prompt Injection & Jailbreak Guard: Detects adversarial attempts to override system
   instructions, extract system prompts, or break prompt boundaries before LLM invocation.
2. In-Memory API Rate Limiter: Thread-safe sliding-window rate limiting per client IP/session.
   Note: In-memory rate limiting is recorded per process and is not shared across multi-process cluster workers.
3. CSV Formula Injection Sanitizer: Escapes formula trigger characters ('=', '@', '+', '-', '\t', '\r')
   for spreadsheet exports without mutating raw underlying database records.
4. Security Audit Logging: Persists auditable security events (logins, prompt rejections,
   rate-limit violations, administrative configuration updates).
"""

import re
import time
import threading
import logging
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import SecurityAuditLog

logger = logging.getLogger(__name__)


# ======================================================================
# 1. Prompt Injection & Jailbreak Guard
# ======================================================================

PROMPT_INJECTION_PATTERNS = [
    # Instruction override patterns
    r"(?i)\bignore\s+(all\s+)?(previous|prior|above|system)\s+(instructions|directions|prompts|rules)",
    r"(?i)\bdisregard\s+(all\s+)?(previous|prior|above|system)\s+(instructions|directions|prompts|rules)",
    r"(?i)\bforget\s+(all\s+)?(previous|prior|about|your)\s+(instructions|rules|identity)",
    r"(?i)\byou\s+are\s+now\s+(in\s+)?(developer|unconstrained|dan|unrestricted|god|override|a\s+different\s+ai|free|an\s+unrestricted)",
    
    # System prompt extraction patterns
    r"(?i)\b(reveal|display|output|show|print|leak|repeat)\s+(your\s+)?(system\s+prompt|initial\s+prompt|internal\s+prompt|hidden\s+instructions|secret\s+instructions|confidential\s+instructions)",
    r"(?i)\bwhat\s+(are\s+your|is\s+your)\s+(exact\s+)?(system\s+instructions|system\s+prompt|initial\s+instructions|internal\s+prompt)",
    
    # Role-play & jailbreak framing
    r"(?i)\b(dan\s+mode|jailbreak|developer\s+mode|unrestricted\s+mode|god\s+mode)\b",
    r"(?i)\b(developer|admin|root|system)\s+(override|mode|access|privileges)\b",
    r"(?i)\bpretend\s+you\s+(have\s+no\s+rules|are\s+evil|are\s+unrestricted|are\s+unfiltered)",
    r"(?i)\bdo\s+anything\s+now\b",
    
    # Delimiter injection & conversational prefix forging
    r"(?i)^\s*(system|assistant|admin|root)\s*:\s*",
    r"(?i)\n\s*(system|assistant|admin|root)\s*:\s*",
    r"(?i)```\s*(system|admin|root)\b",
]

COMPILED_INJECTION_PATTERNS = [re.compile(p) for p in PROMPT_INJECTION_PATTERNS]


def inspect_prompt_safety(text: str) -> Tuple[bool, Optional[str]]:
    """
    Evaluates natural language input for adversarial prompt injection patterns.
    
    Returns:
        (is_safe, violation_reason)
    """
    if not text:
        return True, None

    cleaned = text.strip()

    # Check for adversarial pattern matches
    for pattern in COMPILED_INJECTION_PATTERNS:
        match = pattern.search(cleaned)
        if match:
            matched_phrase = match.group(0)[:60]
            reason = f"Security Violation: Adversarial prompt pattern detected ('{matched_phrase}')."
            logger.warning(f"[PromptInjectionGuard] Blocked input: {reason}")
            return False, reason

    return True, None


# ======================================================================
# 2. In-Memory Thread-Safe Rate Limiter
# ======================================================================

class InMemoryRateLimiter:
    """
    Thread-safe sliding-window rate limiter.
    
    Note:
        In-memory rate limiting is recorded per process. In a multi-worker
        environment (e.g. Gunicorn with multiple Uvicorn workers), limits
        are tracked independently within each operating worker process.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._clients: Dict[str, deque] = defaultdict(deque)

    def is_allowed(
        self,
        client_id: str,
        max_requests: int = 60,
        window_seconds: float = 60.0,
    ) -> Tuple[bool, float, int]:
        """
        Evaluates whether a request from client_id is permitted under the rate limit.
        
        Returns:
            (is_allowed, retry_after_seconds, remaining_requests)
        """
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            timestamps = self._clients[client_id]

            # Evict expired timestamps older than sliding window
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            current_usage = len(timestamps)
            if current_usage >= max_requests:
                oldest = timestamps[0]
                retry_after = max(1.0, round(window_seconds - (now - oldest), 1))
                return False, retry_after, 0

            # Record this request
            timestamps.append(now)
            remaining = max(0, max_requests - current_usage - 1)
            return True, 0.0, remaining

    def reset(self) -> None:
        """Clears all client rate tracking."""
        with self._lock:
            self._clients.clear()


# Global rate limiter instance
rate_limiter = InMemoryRateLimiter()


# ======================================================================
# 3. CSV Formula Injection Defense
# ======================================================================

FORMULA_TRIGGERS = ("=", "@", "+", "-", "\t", "\r")


def sanitize_csv_cell_for_export(val: Any) -> Any:
    """
    Sanitizes values during spreadsheet export to prevent CSV Formula Injection
    (e.g., '=cmd|/c calc'!A0).
    
    Technical Guarantee:
        Protects spreadsheet exports by prefixing triggers with a single quote (').
        Does NOT alter or corrupt raw database records.
    """
    if val is None:
        return ""
    s_val = str(val)
    if s_val.startswith(FORMULA_TRIGGERS):
        # Prefix with single quote to force spreadsheet programs to treat as text
        return f"'{s_val}"
    return s_val


# ======================================================================
# 4. Security Audit Logging
# ======================================================================

def log_security_event(
    event_type: str,
    user_role: Optional[str] = None,
    client_ip: Optional[str] = None,
    endpoint: Optional[str] = None,
    severity: str = "INFO",
    details: Optional[str] = None,
    db: Optional[Session] = None,
) -> None:
    """
    Persists a security or governance audit event to the database.
    Fails safely without raising exceptions to calling application code.
    """
    own_session = False
    session = db
    if session is None:
        session = SessionLocal()
        own_session = True

    try:
        log_entry = SecurityAuditLog(
            event_type=event_type,
            user_role=user_role or "Anonymous",
            client_ip=client_ip or "127.0.0.1",
            endpoint=endpoint or "internal",
            severity=severity,
            details=details,
        )
        session.add(log_entry)
        session.commit()
    except Exception as e:
        logger.error(f"[SecurityAudit] Failed to persist security audit event: {e}")
        try:
            session.rollback()
        except Exception:
            pass
    finally:
        if own_session and session:
            session.close()
