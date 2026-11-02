"""
Tests for SQLite Online Backup and Restore Scripts
--------------------------------------------------
Validates Requirement 9:
"Test backup and restoration using a separate temporary database
before touching the actual project database."
"""

import sqlite3
import tempfile
from pathlib import Path
import pytest

from scripts.backup_db import perform_online_backup
from scripts.restore_db import restore_database_from_backup


@pytest.fixture
def temp_db_env(tmp_path):
    """
    Creates an isolated temporary database with WAL mode and sample transactions.
    """
    db_file = tmp_path / "temp_source.db"
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("""
        CREATE TABLE test_sales (
            id TEXT PRIMARY KEY,
            product TEXT,
            amount REAL
        );
    """)
    cursor.execute("INSERT INTO test_sales VALUES ('T1', 'Laptop', 55000.0);")
    cursor.execute("INSERT INTO test_sales VALUES ('T2', 'Headphones', 2500.0);")
    conn.commit()
    conn.close()

    backup_dir = tmp_path / "backups"
    restore_target = tmp_path / "temp_restored.db"

    return {
        "source": str(db_file),
        "backup_dir": str(backup_dir),
        "restore_target": str(restore_target),
        "tmp_path": tmp_path,
    }


def test_online_backup_and_restore_cycle(temp_db_env):
    """
    Verifies that a separate temporary database in WAL mode is cleanly backed up,
    verified, and restored with 100% data fidelity.
    """
    src = temp_db_env["source"]
    bdir = temp_db_env["backup_dir"]
    dst = temp_db_env["restore_target"]

    # 1. Perform online backup
    success, backup_file = perform_online_backup(src, backup_dir=bdir)
    assert success is True
    assert Path(backup_file).exists()

    # 2. Perform restoration to fresh target path
    res_success, res_msg = restore_database_from_backup(backup_file, dst)
    assert res_success is True
    assert Path(dst).exists()

    # 3. Verify data in restored database
    restored_conn = sqlite3.connect(dst)
    cursor = restored_conn.cursor()
    cursor.execute("SELECT id, product, amount FROM test_sales ORDER BY id;")
    rows = cursor.fetchall()
    restored_conn.close()

    assert len(rows) == 2
    assert rows[0] == ("T1", "Laptop", 55000.0)
    assert rows[1] == ("T2", "Headphones", 2500.0)


def test_backup_handles_nonexistent_source(tmp_path):
    """Verifies that attempting to backup a non-existent file returns graceful error."""
    fake_path = str(tmp_path / "ghost.db")
    success, msg = perform_online_backup(fake_path)
    assert success is False
    assert "does not exist" in msg


def test_restore_rejects_corrupted_backup(tmp_path):
    """Verifies that pre-restore integrity check catches corrupted files."""
    corrupt_file = tmp_path / "corrupt_backup.db"
    corrupt_file.write_text("NOT A VALID SQLITE DATABASE FILE GARBAGE CONTENT")

    target_db = str(tmp_path / "should_not_create.db")
    success, msg = restore_database_from_backup(str(corrupt_file), target_db)
    assert success is False
    assert ("Cannot read backup" in msg or "integrity check" in msg)
