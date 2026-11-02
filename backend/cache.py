"""
In-Memory Analytics Cache Module
--------------------------------
Provides a lightweight, thread-safe in-memory cache with TTL expiration
and atomic invalidation for analytical query results.

Architecture & Scope:
- Zero external infrastructure dependencies (no Redis, Memcached, or external daemons).
- Thread-safe via reentrant locks (RLock).
- Strictly scoped to non-sensitive analytical query results (KPIs, aggregates, trends).
- Note: In-memory cache is per-process. When running multi-process workers, each process
  maintains its own isolated cache.
- Explicit atomic invalidation triggered immediately AFTER dataset upload and reset operations.
"""

import time
import copy
import functools
import threading
import logging
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class AnalyticsCache:
    """
    Thread-safe in-memory TTL cache with fine-grained eviction and statistics.
    """

    def __init__(self, default_ttl: float = 60.0):
        self._default_ttl = default_ttl
        self._cache: Dict[str, Tuple[Any, float]] = {}  # key -> (value, expire_at)
        self._lock = threading.RLock()
        self._hits: int = 0
        self._misses: int = 0
        self._invalidations: int = 0

    def get(self, key: str) -> Optional[Any]:
        """Retrieves a cached value if present and not expired."""
        with self._lock:
            if key in self._cache:
                value, expire_at = self._cache[key]
                if time.time() < expire_at:
                    self._hits += 1
                    return copy.deepcopy(value)
                # Expired: evict lazily
                del self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Stores a value with TTL (seconds)."""
        duration = ttl if ttl is not None else self._default_ttl
        expire_at = time.time() + duration
        val_copy = copy.deepcopy(value)
        with self._lock:
            self._cache[key] = (val_copy, expire_at)

    def invalidate_all(self) -> int:
        """Clears all cached entries (called AFTER dataset upload or reset)."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._invalidations += 1
            logger.info(f"[AnalyticsCache] Invalidated all {count} cached entries.")
            return count

    def invalidate_prefix(self, prefix: str) -> int:
        """Clears all entries matching a specific prefix."""
        with self._lock:
            to_del = [k for k in self._cache if k.startswith(prefix)]
            for k in to_del:
                del self._cache[k]
            if to_del:
                logger.info(f"[AnalyticsCache] Invalidated {len(to_del)} entries matching '{prefix}'.")
            return len(to_del)

    def stats(self) -> Dict[str, Any]:
        """Returns diagnostic telemetry for cache health monitoring."""
        with self._lock:
            now = time.time()
            valid_entries = sum(1 for _, (_, exp) in self._cache.items() if exp > now)
            total_requests = self._hits + self._misses
            hit_ratio = round((self._hits / total_requests * 100), 2) if total_requests > 0 else 0.0
            return {
                "active_entries": valid_entries,
                "total_stored": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio_percent": hit_ratio,
                "invalidation_cycles": self._invalidations,
            }


# Global singleton instance for analytical computations
analytics_cache = AnalyticsCache(default_ttl=60.0)


def cached_query(prefix: str, ttl: float = 60.0):
    """
    Decorator to cache database analytical query results.
    Filters out SQLAlchemy Session arguments to prevent hashing non-serializable objects.
    Ensures that ONLY deterministic analytics results are cached, NEVER user auth credentials.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Extract cacheable arguments (ignore Session or db-like objects)
            clean_args = []
            for a in args:
                # Exclude SQLAlchemy Session instances or connection objects
                if hasattr(a, "execute") or hasattr(a, "query"):
                    continue
                clean_args.append(str(a))

            clean_kwargs = {
                k: str(v) for k, v in kwargs.items()
                if not (hasattr(v, "execute") or hasattr(v, "query"))
            }

            key_repr = f"{prefix}:{func.__name__}:{','.join(clean_args)}:{sorted(clean_kwargs.items())}"
            cached_val = analytics_cache.get(key_repr)
            if cached_val is not None:
                return cached_val

            result = func(*args, **kwargs)
            analytics_cache.set(key_repr, result, ttl=ttl)
            return result
        return wrapper
    return decorator
