"""
Application Telemetry and Metrics Collector Module
--------------------------------------------------
Collects in-memory telemetry on API requests, execution latency, error rates,
LLM provider calls, circuit breaker events, and analytical cache utilization.

Architecture & Scope:
- Thread-safe state tracking using reentrant locks (RLock).
- Zero external infrastructure dependencies (no external stats daemon or Prometheus server required).
- Note on Multi-Worker Environments:
  These in-memory metrics are per process. If deployed with multiple worker processes
  (e.g., Gunicorn with multiple Uvicorn workers), each process records metrics for its
  own handled traffic.
"""

import time
import threading
import logging
from typing import Any, Dict, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Thread-safe in-memory metrics collector for application performance monitoring.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._start_time: float = time.time()
        
        # HTTP Traffic Metrics
        self._total_requests: int = 0
        self._requests_by_status: Dict[int, int] = defaultdict(int)
        self._requests_by_endpoint: Dict[str, int] = defaultdict(int)
        self._latency_sum_seconds: float = 0.0
        self._max_latency_seconds: float = 0.0
        self._recent_latencies: List[float] = []  # Rolling sample of last 100 requests
        self._slow_requests_count: int = 0  # Requests taking > 1.0s
        
        # LLM & AI Metrics
        self._llm_requests_total: int = 0
        self._llm_success_total: int = 0
        self._llm_failures_total: int = 0
        self._deterministic_fallbacks_total: int = 0
        self._circuit_trips_total: int = 0

    def record_request(self, endpoint: str, status_code: int, duration_seconds: float) -> None:
        """Records an HTTP request completion and latency."""
        with self._lock:
            self._total_requests += 1
            self._requests_by_status[status_code] += 1
            self._requests_by_endpoint[endpoint] += 1
            self._latency_sum_seconds += duration_seconds
            
            if duration_seconds > self._max_latency_seconds:
                self._max_latency_seconds = duration_seconds
            
            if duration_seconds > 1.0:
                self._slow_requests_count += 1
            
            self._recent_latencies.append(duration_seconds)
            if len(self._recent_latencies) > 100:
                self._recent_latencies.pop(0)

    def record_llm_call(self, provider: str, success: bool, is_fallback: bool = False) -> None:
        """Records an AI service call outcome."""
        with self._lock:
            self._llm_requests_total += 1
            if success:
                self._llm_success_total += 1
            else:
                self._llm_failures_total += 1
            if is_fallback:
                self._deterministic_fallbacks_total += 1

    def record_circuit_trip(self) -> None:
        """Records a circuit breaker trip event."""
        with self._lock:
            self._circuit_trips_total += 1

    def get_summary(self) -> Dict[str, Any]:
        """Returns structured diagnostic telemetry for /api/metrics endpoint."""
        with self._lock:
            uptime = round(time.time() - self._start_time, 2)
            avg_latency_ms = (
                round((self._latency_sum_seconds / self._total_requests) * 1000, 2)
                if self._total_requests > 0
                else 0.0
            )
            
            # Approximate p95 from rolling window
            p95_latency_ms = 0.0
            if self._recent_latencies:
                sorted_lats = sorted(self._recent_latencies)
                idx = int(0.95 * len(sorted_lats))
                p95_latency_ms = round(sorted_lats[min(idx, len(sorted_lats) - 1)] * 1000, 2)

            from backend.cache import analytics_cache
            cache_stats = analytics_cache.stats()

            return {
                "process_uptime_seconds": uptime,
                "notes": "In-memory telemetry is recorded per process.",
                "http_metrics": {
                    "total_requests": self._total_requests,
                    "status_codes": dict(self._requests_by_status),
                    "endpoints": dict(self._requests_by_endpoint),
                    "average_latency_ms": avg_latency_ms,
                    "p95_latency_ms": p95_latency_ms,
                    "max_latency_ms": round(self._max_latency_seconds * 1000, 2),
                    "slow_requests_count (>1s)": self._slow_requests_count,
                },
                "ai_service_metrics": {
                    "total_llm_queries": self._llm_requests_total,
                    "successful_llm_queries": self._llm_success_total,
                    "failed_llm_queries": self._llm_failures_total,
                    "fallback_queries": self._deterministic_fallbacks_total,
                    "circuit_breaker_trips": self._circuit_trips_total,
                },
                "cache_metrics": cache_stats,
            }


# Global singleton instance
metrics_collector = MetricsCollector()
