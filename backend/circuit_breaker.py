"""
Circuit Breaker and Resilient Retry Module
------------------------------------------
Implements the canonical Circuit Breaker pattern and bounded exponential
backoff retry logic for external LLM integrations (Google Gemini & OpenAI).

Key Guarantees:
1. Thread-Safe State Transitions: All state mutations are protected by reentrant locks.
2. Single-Probe Half-Open: Only a single thread is permitted to probe recovery;
   concurrent requests during Half-Open immediately utilize deterministic fallback.
3. Selective Transient Retries: Retries ONLY transient network errors, HTTP 429,
   and 503/504 errors; permanent errors (400, 401, 403) fail immediately.
4. Bounded Exponential Backoff with Jitter: Prevents thundering herds and respects Retry-After.
"""

import time
import random
import logging
import threading
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"          # Normal operation: requests pass to LLM
    OPEN = "OPEN"              # Outage detected: fail fast, route to fallback immediately
    HALF_OPEN = "HALF_OPEN"    # Cooldown elapsed: single probe request tests recovery


class CircuitBreakerOpenException(Exception):
    """Raised when an operation is attempted while the circuit breaker is OPEN."""
    pass


class CircuitBreaker:
    """
    Thread-safe Circuit Breaker guarding external LLM service calls.
    """

    def __init__(
        self,
        name: str = "GeminiCircuitBreaker",
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        success_threshold: int = 1,
        on_trip: Optional[Callable[[], None]] = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.on_trip = on_trip

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._last_state_change: float = time.time()
        self._last_failure_time: Optional[float] = None
        self._last_failure_reason: Optional[str] = None
        self._probe_in_progress: bool = False
        self._lock = threading.RLock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._evaluate_state()
            return self._state

    def _evaluate_state(self) -> None:
        """Internal helper to transition from OPEN to HALF_OPEN when cooldown expires."""
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_state_change
            if elapsed >= self.recovery_timeout:
                logger.info(
                    f"[{self.name}] Cooldown period ({self.recovery_timeout}s) expired. "
                    f"Transitioning to HALF_OPEN for recovery probing."
                )
                self._state = CircuitState.HALF_OPEN
                self._last_state_change = time.time()
                self._probe_in_progress = False
                self._success_count = 0

    def allow_request(self) -> bool:
        """
        Determines whether an external request may proceed.
        In HALF_OPEN, ensures strictly ONE request acts as the recovery probe.
        """
        with self._lock:
            self._evaluate_state()

            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                return False

            if self._state == CircuitState.HALF_OPEN:
                if not self._probe_in_progress:
                    # Claim the probe slot atomically
                    self._probe_in_progress = True
                    logger.info(f"[{self.name}] Permitting single probe request in HALF_OPEN state.")
                    return True
                # A probe is already in flight; concurrent requests use fallback
                return False

            return False

    def record_success(self) -> None:
        """Records a successful LLM invocation."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    logger.info(
                        f"[{self.name}] Probe request succeeded! Circuit CLOSED. "
                        f"Normal LLM routing restored."
                    )
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._probe_in_progress = False
                    self._last_state_change = time.time()
                    self._last_failure_reason = None
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0
                self._probe_in_progress = False

    def record_failure(self, error: Exception) -> None:
        """Records a failed LLM invocation and evaluates circuit tripping."""
        err_msg = str(error)
        with self._lock:
            self._last_failure_time = time.time()
            self._last_failure_reason = err_msg

            if self._state == CircuitState.HALF_OPEN:
                logger.warning(
                    f"[{self.name}] Probe request failed in HALF_OPEN ({err_msg[:80]}). "
                    f"Tripping circuit back to OPEN for {self.recovery_timeout}s."
                )
                self._state = CircuitState.OPEN
                self._last_state_change = time.time()
                self._probe_in_progress = False
                self._success_count = 0
                if self.on_trip:
                    try:
                        self.on_trip()
                    except Exception:
                        pass

            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                logger.warning(
                    f"[{self.name}] LLM failure recorded ({self._failure_count}/{self.failure_threshold}): {err_msg[:80]}"
                )
                if self._failure_count >= self.failure_threshold:
                    logger.error(
                        f"[{self.name}] Consecutive failures reached threshold ({self.failure_threshold}). "
                        f"Tripping circuit to OPEN for {self.recovery_timeout}s. Deterministic fallback active."
                    )
                    self._state = CircuitState.OPEN
                    self._last_state_change = time.time()
                    if self.on_trip:
                        try:
                            self.on_trip()
                        except Exception:
                            pass

    def reset(self) -> None:
        """Explicitly resets the circuit breaker to CLOSED (e.g. after manual Admin re-verification)."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._probe_in_progress = False
            self._last_state_change = time.time()
            self._last_failure_reason = None
            logger.info(f"[{self.name}] Circuit breaker manually reset to CLOSED.")

    def trip(self, reason: str = "Manual outage trip") -> None:
        """Explicitly trips the circuit breaker to OPEN (e.g. during outage simulation)."""
        with self._lock:
            self._state = CircuitState.OPEN
            self._last_state_change = time.time()
            self._last_failure_time = time.time()
            self._last_failure_reason = reason
            self._probe_in_progress = False
            if self.on_trip:
                try:
                    self.on_trip()
                except Exception:
                    pass
            logger.warning(f"[{self.name}] Circuit breaker tripped to OPEN: {reason}")

    def get_status(self) -> Dict[str, Any]:
        """Returns structured diagnostic status dictionary for observability."""
        with self._lock:
            self._evaluate_state()
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout_seconds": self.recovery_timeout,
                "seconds_since_state_change": round(time.time() - self._last_state_change, 2),
                "last_failure_time": self._last_failure_time,
                "last_failure_reason": self._last_failure_reason,
                "probe_in_progress": self._probe_in_progress,
            }


# ----------------------------------------------------------------------
# Resilient Retry Utilities
# ----------------------------------------------------------------------

def is_transient_error(error: Exception) -> bool:
    """
    Distinguishes transient errors (which should be retried) from permanent errors
    (which should fail immediately without wasteful retries).
    """
    msg = str(error).lower()

    # Permanent failures that MUST NOT be retried:
    permanent_indicators = [
        "400", "bad request", "invalid argument", "invalid_api_key",
        "api key not valid", "unauthorized", "401", "403", "forbidden",
        "permission_denied", "not_found", "model not found",
    ]
    for ind in permanent_indicators:
        if ind in msg:
            return False

    # Transient failures that MAY be retried:
    transient_indicators = [
        "429", "quota", "rate limit", "resource_exhausted",
        "503", "unavailable", "service unavailable", "overloaded",
        "504", "gateway timeout", "timeout", "timed out",
        "connection reset", "connection refused", "remote disconnected",
    ]
    for ind in transient_indicators:
        if ind in msg:
            return True

    return False


def parse_retry_after(error: Exception, default_delay: float = 1.0) -> float:
    """Extracts Retry-After duration if present in exception details."""
    msg = str(error)
    import re
    # Match patterns like "retry after 5s" or "Retry-After: 4.2"
    m = re.search(r"retry[- ]after[:\s]+(\d+(?:\.\d+)?)", msg, re.IGNORECASE)
    if m:
        try:
            return min(float(m.group(1)), 10.0)  # Bound to max 10s
        except ValueError:
            pass
    return default_delay


def execute_with_resilience(
    circuit_breaker: CircuitBreaker,
    operation: Callable[[], T],
    max_retries: int = 2,
    base_delay: float = 0.5,
    max_delay: float = 4.0,
    jitter: float = 0.25,
) -> T:
    """
    Executes a callable guarded by the Circuit Breaker with bounded exponential backoff
    and jitter for transient errors.
    """
    if not circuit_breaker.allow_request():
        raise CircuitBreakerOpenException(
            f"Circuit breaker '{circuit_breaker.name}' is {circuit_breaker.state.value}. "
            f"Immediate fallback engaged."
        )

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            result = operation()
            circuit_breaker.record_success()
            return result
        except Exception as exc:
            last_exc = exc
            if not is_transient_error(exc) or attempt == max_retries:
                # Permanent error or exhausted retries
                circuit_breaker.record_failure(exc)
                raise exc

            # Calculate backoff with jitter
            retry_after = parse_retry_after(exc, default_delay=base_delay * (2 ** attempt))
            delay = min(retry_after, max_delay) + random.uniform(0, jitter)
            logger.warning(
                f"[{circuit_breaker.name}] Transient error on attempt {attempt + 1}/{max_retries + 1}: {str(exc)[:80]}. "
                f"Backing off for {delay:.2f}s before retry..."
            )
            time.sleep(delay)

    circuit_breaker.record_failure(last_exc)
    raise last_exc
