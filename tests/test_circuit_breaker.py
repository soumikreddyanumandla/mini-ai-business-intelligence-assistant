"""
Tests for Circuit Breaker and Resilient Retry Mechanism
------------------------------------------------------
Validates:
1. Thread-safe transitions across CLOSED, OPEN, and HALF_OPEN states.
2. Single-probe half-open guarantee under concurrent requests.
3. Selective transient error retry vs permanent error fail-fast.
4. Bounded exponential backoff and jitter.
5. Dynamic reset and manual outage trip.
"""

import time
import threading
import pytest
from backend.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpenException,
    is_transient_error,
    parse_retry_after,
    execute_with_resilience,
)


def test_circuit_breaker_closed_to_open_transition():
    cb = CircuitBreaker("TestCB", failure_threshold=3, recovery_timeout=0.2)
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True

    # 1st failure
    cb.record_failure(Exception("Transient 503 Service Unavailable"))
    assert cb.state == CircuitState.CLOSED

    # 2nd failure
    cb.record_failure(Exception("Transient 503 Service Unavailable"))
    assert cb.state == CircuitState.CLOSED

    # 3rd failure trips the breaker
    cb.record_failure(Exception("Transient 503 Service Unavailable"))
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False


def test_circuit_breaker_half_open_recovery_and_single_probe():
    cb = CircuitBreaker("TestCB", failure_threshold=2, recovery_timeout=0.1)
    cb.record_failure(Exception("Error 1"))
    cb.record_failure(Exception("Error 2"))
    assert cb.state == CircuitState.OPEN

    # Wait for cooldown to expire
    time.sleep(0.12)
    assert cb.state == CircuitState.HALF_OPEN

    # Exactly ONE probe request should be allowed
    assert cb.allow_request() is True
    # Concurrent request while probe is in flight must be rejected!
    assert cb.allow_request() is False

    # Successful probe restores CLOSED state
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True


def test_circuit_breaker_probe_failure_re_trips_to_open():
    cb = CircuitBreaker("TestCB", failure_threshold=2, recovery_timeout=0.1)
    cb.record_failure(Exception("Error 1"))
    cb.record_failure(Exception("Error 2"))
    assert cb.state == CircuitState.OPEN

    time.sleep(0.12)
    assert cb.state == CircuitState.HALF_OPEN

    # Claim probe
    assert cb.allow_request() is True

    # Probe fails
    cb.record_failure(Exception("Probe failed"))
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False


def test_circuit_breaker_thread_concurrency():
    """Validates that concurrent threads tripping and probing the circuit never corrupt state."""
    cb = CircuitBreaker("ConcurrentCB", failure_threshold=5, recovery_timeout=0.05)
    threads = []
    allowed_probes = []
    lock = threading.Lock()

    # Trip breaker
    for _ in range(5):
        cb.record_failure(Exception("Simulated error"))
    assert cb.state == CircuitState.OPEN

    time.sleep(0.06)

    def probe_worker():
        if cb.allow_request():
            with lock:
                allowed_probes.append(1)
            # Simulate work
            time.sleep(0.01)
            cb.record_success()

    for _ in range(20):
        t = threading.Thread(target=probe_worker)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Exactly 1 probe should have been allowed in HALF_OPEN before it closed
    assert len(allowed_probes) == 1
    assert cb.state == CircuitState.CLOSED


def test_transient_error_classification():
    # Transient errors
    assert is_transient_error(Exception("429 Resource Exhausted: Quota exceeded")) is True
    assert is_transient_error(Exception("503 Service Unavailable: Overloaded")) is True
    assert is_transient_error(Exception("504 Gateway Timeout")) is True
    assert is_transient_error(Exception("Connection reset by peer")) is True

    # Permanent errors (must NOT be retried)
    assert is_transient_error(Exception("400 Bad Request: Invalid argument")) is False
    assert is_transient_error(Exception("401 Unauthorized: API key not valid")) is False
    assert is_transient_error(Exception("403 Forbidden: Permission denied")) is False
    assert is_transient_error(Exception("Model not found: gemini-unknown")) is False


def test_parse_retry_after():
    assert parse_retry_after(Exception("Please retry after 3.5 seconds")) == 3.5
    assert parse_retry_after(Exception("Retry-After: 5")) == 5.0
    # Capped at 10.0s max
    assert parse_retry_after(Exception("Retry-After: 60")) == 10.0
    # Default fallback
    assert parse_retry_after(Exception("Generic error"), default_delay=1.5) == 1.5


def test_execute_with_resilience_transient_retry_success():
    cb = CircuitBreaker("RetryCB", failure_threshold=3, recovery_timeout=1.0)
    call_count = 0

    def flaky_operation():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise Exception("503 Service Unavailable")
        return "success"

    result = execute_with_resilience(cb, flaky_operation, max_retries=2, base_delay=0.01, jitter=0.01)
    assert result == "success"
    assert call_count == 2
    assert cb.state == CircuitState.CLOSED


def test_execute_with_resilience_permanent_error_no_retry():
    cb = CircuitBreaker("PermanentCB", failure_threshold=3, recovery_timeout=1.0)
    call_count = 0

    def bad_request_operation():
        nonlocal call_count
        call_count += 1
        raise Exception("400 Bad Request: Invalid prompt argument")

    with pytest.raises(Exception) as excinfo:
        execute_with_resilience(cb, bad_request_operation, max_retries=2, base_delay=0.01)

    assert "400 Bad Request" in str(excinfo.value)
    # Permanent error should NOT retry
    assert call_count == 1


def test_execute_with_resilience_circuit_open_fast_fail():
    cb = CircuitBreaker("FastFailCB", failure_threshold=1, recovery_timeout=10.0)
    cb.trip("Simulated outage")

    with pytest.raises(CircuitBreakerOpenException):
        execute_with_resilience(cb, lambda: "should not run")
