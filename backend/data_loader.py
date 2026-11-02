"""
Data Loader Module
------------------
Responsible for loading the sales CSV dataset into the SQLite database.
Applies data cleaning and business eligibility rules, prevents duplicate imports,
and generates audit logs.
"""

import csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from sqlalchemy.orm import Session
from backend.config import settings
from backend.database import SessionLocal, init_db
from backend.data_cleaning import clean_and_validate_record, RecordValidationResult
from backend.exceptions import DatasetNotFoundError
from backend.models import SalesTransaction, DataQualityLog

logger = logging.getLogger(__name__)


MANDATORY_CSV_COLUMNS = [
    "Transaction_Id",
    "Order_date",
    "Product",
    "Category",
    "Region",
    "Sales_channel",
    "Quantity",
    "Unit_price",
    "Discount_amount",
    "Status",
]


def validate_csv_schema(fieldnames: Optional[List[str]]) -> Tuple[bool, List[str]]:
    """
    Validates that all mandatory column headers exist in the CSV file.
    Case-insensitive matching to accommodate minor formatting differences.
    """
    if not fieldnames:
        return False, ["CSV file has no header row or is empty."]

    normalized_present = {col.strip().lower() for col in fieldnames if col}
    missing = []
    for required in MANDATORY_CSV_COLUMNS:
        if required.lower() not in normalized_present:
            missing.append(required)

    if missing:
        return False, missing
    return True, []


def reset_default_dataset(db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Restores the database strictly to the original company-provided sales.csv dataset.
    """
    default_path = settings.BASE_DIR / "data" / "sales.csv"
    logger.info("Restoring database to default company sales dataset.")
    return load_and_sync_csv_to_db(csv_path=str(default_path), db=db, replace_existing=True)


def load_and_sync_csv_to_db(
    csv_path: Optional[str] = None,
    db: Optional[Session] = None,
    replace_existing: bool = True,
) -> Dict[str, Any]:
    """
    Loads transactions from CSV file into SQLite database.
    
    Args:
        csv_path: Path to CSV file (defaults to settings.CSV_DATA_PATH).
        db: Optional existing SQLAlchemy session. If None, a new session is managed.
        replace_existing: If True, clears existing transactions to prevent duplicates.
        
    Returns:
        Summary dict containing total_imported, eligible_count, excluded_count,
        cleanliness_rate, and details of excluded records.
    """
    path_to_read = Path(csv_path or settings.CSV_DATA_PATH)
    if not path_to_read.exists():
        raise DatasetNotFoundError(
            f"Sales dataset CSV file not found at path: {path_to_read.resolve()}"
        )

    own_session = False
    if db is None:
        db = SessionLocal()
        own_session = True

    try:
        with open(path_to_read, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            
            valid_schema, missing_cols = validate_csv_schema(fieldnames)
            if not valid_schema:
                raise ValueError(
                    f"CSV schema validation error: Missing required column(s): {', '.join(missing_cols)}"
                )

            raw_rows = list(reader)

        if not raw_rows:
            logger.warning(f"CSV file at {path_to_read} is empty.")
            return {
                "total_imported": 0,
                "eligible_count": 0,
                "excluded_count": 0,
                "duplicate_count": 0,
                "cleanliness_rate": 0.0,
                "excluded_records": [],
            }

        # Track transactions to prevent duplicate primary keys within the same CSV
        seen_tids = set()
        transactions_to_insert: List[SalesTransaction] = []
        excluded_details: List[Dict[str, Any]] = []
        eligible_count = 0
        excluded_count = 0
        duplicate_count = 0

        # Phase 1: In-memory validation of all records before touching database
        for row in raw_rows:
            val_res: RecordValidationResult = clean_and_validate_record(row)
            
            # Check for duplicate transaction_id in current import
            db_tid = val_res.transaction_id
            if val_res.transaction_id in seen_tids:
                val_res.is_eligible = False
                val_res.exclusion_reasons.append("Duplicate Transaction_Id within dataset")
                duplicate_count += 1
                db_tid = f"{val_res.transaction_id}_DUP_{duplicate_count}"
            seen_tids.add(val_res.transaction_id)

            if val_res.is_eligible:
                eligible_count += 1
            else:
                excluded_count += 1
                excluded_details.append({
                    "transaction_id": val_res.transaction_id,
                    "order_date": val_res.order_date.isoformat() if val_res.order_date else None,
                    "product": val_res.product,
                    "quantity": val_res.quantity,
                    "unit_price": val_res.unit_price,
                    "discount_amount": val_res.discount_amount,
                    "status": val_res.status,
                    "exclusion_reasons": val_res.exclusion_reasons,
                })

            txn = SalesTransaction(
                transaction_id=db_tid,
                order_date=val_res.order_date,
                product=val_res.product,
                category=val_res.category,
                region=val_res.region,
                sales_channel=val_res.sales_channel,
                quantity=val_res.quantity,
                unit_price=val_res.unit_price,
                discount_amount=val_res.discount_amount,
                gross_revenue=val_res.gross_revenue,
                net_revenue=val_res.net_revenue,
                status=val_res.status,
                is_eligible=val_res.is_eligible,
                exclusion_reason=val_res.exclusion_reason_str,
            )
            transactions_to_insert.append(txn)

        total_records = len(transactions_to_insert)
        cleanliness_rate = (
            round((eligible_count / total_records) * 100, 2) if total_records > 0 else 0.0
        )

        # Record Data Quality Log
        log_entry = DataQualityLog(
            source_filename=path_to_read.name,
            total_records=total_records,
            eligible_records=eligible_count,
            excluded_records=excluded_count,
            notes=json.dumps({
                "cleanliness_percentage": cleanliness_rate,
                "excluded_count": excluded_count,
            }),
        )

        # Phase 2: Atomic Database Synchronization
        # Deletion of old records and insertion of new records happen in one atomic commit.
        # If any failure occurs, rollback preserves existing database data completely.
        if replace_existing:
            db.query(SalesTransaction).delete()

        db.bulk_save_objects(transactions_to_insert)
        db.add(log_entry)
        db.commit()

        logger.info(
            f"Successfully synced {total_records} records to SQLite "
            f"({eligible_count} eligible, {excluded_count} excluded)."
        )

        return {
            "total_imported": total_records,
            "eligible_count": eligible_count,
            "excluded_count": excluded_count,
            "duplicate_count": duplicate_count,
            "cleanliness_rate": cleanliness_rate,
            "excluded_records": excluded_details,
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to load CSV into database: {e}")
        raise e
    finally:
        if own_session:
            db.close()
