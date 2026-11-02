#!/usr/bin/env python3
"""
SQLite Database Restore Script
------------------------------
Restores an SQLite database from a point-in-time backup snapshot.

Guarantees:
- Verifies source backup file integrity with PRAGMA integrity_check before restoring.
- Performs restoration using SQLite Online Backup API.
- Re-verifies the restored target database integrity.
"""

import sys
import sqlite3
import logging
from pathlib import Path
from typing import Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("restore_db")


def restore_database_from_backup(
    backup_file_path: str,
    target_db_path: str,
) -> Tuple[bool, str]:
    """
    Restores the SQLite database at target_db_path from the backup at backup_file_path.
    """
    bak_path = Path(backup_file_path).resolve()
    target_path = Path(target_db_path).resolve()

    if not bak_path.exists():
        err = f"Backup file not found: {bak_path}"
        logger.error(err)
        return False, err

    # Step 1: Pre-flight integrity check on backup file
    logger.info(f"Validating integrity of backup snapshot: {bak_path}")
    try:
        chk_conn = sqlite3.connect(str(bak_path))
        cursor = chk_conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        res = cursor.fetchone()
        chk_conn.close()

        if not res or res[0] != "ok":
            err = f"Backup file failed pre-restore integrity check: {res}"
            logger.error(err)
            return False, err
    except Exception as e:
        err = f"Cannot read backup file for validation: {e}"
        logger.error(err)
        return False, err

    # Step 2: Ensure target directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Restoring database: {bak_path} -> {target_path}")

    src_conn = None
    dst_conn = None
    try:
        src_conn = sqlite3.connect(str(bak_path))
        dst_conn = sqlite3.connect(str(target_path))

        with dst_conn:
            src_conn.backup(dst_conn, pages=100)

        dst_conn.close()
        dst_conn = None

        # Step 3: Post-restore verification
        verify_conn = sqlite3.connect(str(target_path))
        cursor = verify_conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        check_result = cursor.fetchone()
        verify_conn.close()

        if check_result and check_result[0] == "ok":
            msg = f"Database successfully restored to: {target_path} (integrity: ok)"
            logger.info(msg)
            return True, msg
        else:
            err = f"Restored database failed integrity check: {check_result}"
            logger.error(err)
            return False, err

    except Exception as e:
        err = f"Failed to restore database: {e}"
        logger.error(err)
        return False, err
    finally:
        if src_conn:
            src_conn.close()
        if dst_conn:
            dst_conn.close()


def main():
    if len(sys.argv) < 3:
        logger.error("Usage: python3 restore_db.py <path_to_backup.db> <target_database.db>")
        sys.exit(1)

    backup_file = sys.argv[1]
    target_db = sys.argv[2]
    success, msg = restore_database_from_backup(backup_file, target_db)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
