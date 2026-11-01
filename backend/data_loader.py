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
            raw_rows = list(reader)

        if not raw_rows:
            logger.warning(f"CSV file at {path_to_read} is empty.")
            return {
                "total_imported": 0,
                "eligible_count": 0,
                "excluded_count": 0,
                "cleanliness_rate": 0.0,
                "excluded_records": [],
            }

        if replace_existing:
            db.query(SalesTransaction).delete()
            db.commit()

        # Track transactions to prevent duplicate primary keys within the same CSV
        seen_tids = set()
        transactions_to_insert: List[SalesTransaction] = []
        excluded_details: List[Dict[str, Any]] = []
        eligible_count = 0
        excluded_count = 0

        for row in raw_rows:
            val_res: RecordValidationResult = clean_and_validate_record(row)
            
            # Check for duplicate transaction_id in current import
            if val_res.transaction_id in seen_tids:
                val_res.is_eligible = False
                val_res.exclusion_reasons.append("Duplicate Transaction_Id within dataset")
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
                transaction_id=val_res.transaction_id,
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

        db.bulk_save_objects(transactions_to_insert)

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
