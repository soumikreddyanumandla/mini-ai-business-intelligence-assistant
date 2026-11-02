"""
Automated Concurrency, Scalability, and Atomic Reliability Tests
---------------------------------------------------------------
Validates:
1. Concurrency: Multiple concurrent threads querying SQLite in WAL mode without database locks.
2. Thread-safety: Cache concurrency under simultaneous reads and invalidations.
3. Atomic CSV Ingestion: Validation failure guarantees the existing dataset is preserved intact.
4. Resilience: Rapid concurrent probe requests in HALF-OPEN state enforce single-probe guarantee.
"""

import threading
import sqlite3
import pytest
from backend.database import SessionLocal
from backend.models import SalesTransaction
from backend.analytics import get_total_revenue, get_dashboard_summary_metrics
from backend.data_loader import load_and_sync_csv_to_db
from backend.cache import analytics_cache
from backend.circuit_breaker import CircuitBreaker, CircuitState


def test_concurrent_sqlite_reads_wal_mode():
    """
    Spawns 10 concurrent threads executing analytical queries simultaneously.
    Verifies that SQLite WAL mode and busy_timeout prevent 'database is locked' errors.
    """
    errors = []
    results = []

    def worker():
        try:
            db = SessionLocal()
            res = get_total_revenue(db)
            db.close()
            results.append(res["total_net_revenue"])
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Concurrent database errors occurred: {errors}"
    assert len(results) == 10
    assert all(r == 1439200.0 for r in results)


def test_atomic_csv_ingestion_preserves_dataset_on_failure(tmp_path):
    """
    Requirement 1: "Implement atomic CSV imports first. Never delete the existing
    dataset before successful validation."
    """
    db = SessionLocal()
    initial_count = db.query(SalesTransaction).count()
    assert initial_count > 0, "Initial dataset must not be empty"

    # Create an invalid CSV with invalid headers and corrupted columns
    invalid_csv = tmp_path / "corrupted_import.csv"
    invalid_csv.write_text("Transaction_Id,Product\nTXN999,OnlyTwoCols")

    # Ingestion must raise ValueError and reject the import
    with pytest.raises(ValueError):
        load_and_sync_csv_to_db(csv_path=str(invalid_csv), db=db, replace_existing=True)

    # Re-verify that existing transactions were NOT deleted
    post_count = db.query(SalesTransaction).count()
    db.close()

    assert post_count == initial_count, (
        f"Atomic guarantee violated! Count dropped from {initial_count} to {post_count}"
    )


def test_cache_concurrency_stress():
    """
    Spawns 20 concurrent threads reading, setting, and invalidating the cache.
    Verifies that reentrant locks prevent race conditions or corrupted states.
    """
    errors = []

    def writer_worker(idx):
        try:
            for i in range(50):
                analytics_cache.set(f"key_{idx}_{i}", {"value": idx * i}, ttl=5.0)
                if i % 10 == 0:
                    analytics_cache.invalidate_prefix(f"key_{idx}")
        except Exception as e:
            errors.append(str(e))

    def reader_worker(idx):
        try:
            for i in range(50):
                analytics_cache.get(f"key_{idx}_{i}")
        except Exception as e:
            errors.append(str(e))

    threads = []
    for i in range(10):
        threads.append(threading.Thread(target=writer_worker, args=(i,)))
        threads.append(threading.Thread(target=reader_worker, args=(i,)))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Cache concurrency errors: {errors}"


def test_circuit_breaker_high_concurrency_single_probe():
    """
    Verifies that under a burst of 50 concurrent requests during HALF-OPEN,
    exactly ONE request obtains probe permission while 49 are routed to fallback.
    """
    cb = CircuitBreaker("ConcurrencyTestCB", failure_threshold=2, recovery_timeout=0.01)
    cb.record_failure(Exception("Error 1"))
    cb.record_failure(Exception("Error 2"))
    assert cb.state == CircuitState.OPEN

    import time
    time.sleep(0.02)
    assert cb.state == CircuitState.HALF_OPEN

    allowed_results = []
    lock = threading.Lock()

    def probe_attempt():
        allowed = cb.allow_request()
        with lock:
            allowed_results.append(allowed)

    threads = [threading.Thread(target=probe_attempt) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly 1 True, 49 False
    true_count = sum(1 for a in allowed_results if a is True)
    false_count = sum(1 for a in allowed_results if a is False)
    assert true_count == 1
    assert false_count == 49
