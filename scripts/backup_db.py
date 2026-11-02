#!/usr/bin/env python3
"""
SQLite Online Database Backup Script
------------------------------------
Uses SQLite's official Online Backup API (sqlite3.Connection.backup)
to create a consistent, non-blocking snapshot of the database.

Guarantees:
- Safe with SQLite WAL (Write-Ahead Logging) mode.
- Non-blocking: concurrent read and write transactions can proceed safely.
- Runs an automated PRAGMA integrity_check on the resulting backup file.
"""

import os
import sys
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backup_db")


def perform_online_backup(
    source_db_path: str,
    target_backup_path: Optional[str] = None,
    backup_dir: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Performs an online backup from source_db_path to target_backup_path.
    If target_backup_path is not specified, generates a timestamped file in backup_dir.
    """
    src_path = Path(source_db_path).resolve()
    if not src_path.exists():
        err = f"Source database file does not exist: {src_path}"
        logger.error(err)
        return False, err

    if not target_backup_path:
        out_dir = Path(backup_dir) if backup_dir else src_path.parent / "backups"
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        target_path = out_dir / f"{src_path.stem}_backup_{timestamp}.db"
    else:
        target_path = Path(target_backup_path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Initiating online SQLite backup: {src_path} -> {target_path}")

    src_conn = None
    dst_conn = None
    try:
        # Open source database in read-only or standard mode
        src_conn = sqlite3.connect(str(src_path))
        dst_conn = sqlite3.connect(str(target_path))

        # Perform atomic online backup using SQLite C-API wrapper
        with dst_conn:
            src_conn.backup(dst_conn, pages=100)

        dst_conn.close()
        dst_conn = None

        # Verify integrity of the newly created backup file
        verify_conn = sqlite3.connect(str(target_path))
        cursor = verify_conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        check_result = cursor.fetchone()
        verify_conn.close()

        if check_result and check_result[0] == "ok":
            size_bytes = target_path.stat().st_size
            msg = f"Backup completed successfully: {target_path} ({size_bytes:,} bytes, integrity: ok)"
            logger.info(msg)
            return True, str(target_path)
        else:
            err = f"Backup integrity check failed: {check_result}"
            logger.error(err)
            return False, err

    except Exception as e:
        err = f"Failed to execute online backup: {e}"
        logger.error(err)
        if target_path.exists():
            try:
                target_path.unlink()
            except OSError:
                pass
        return False, err
    finally:
        if src_conn:
            src_conn.close()
        if dst_conn:
            dst_conn.close()


def main():
    base_dir = Path(__file__).resolve().parent.parent
    default_db = base_dir / "data" / "bi_assistant.db"
    
    db_path = sys.argv[1] if len(sys.argv) > 1 else str(default_db)
    dest_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    success, result = perform_online_backup(db_path, target_backup_path=dest_path)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
