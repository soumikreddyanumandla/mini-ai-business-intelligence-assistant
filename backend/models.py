"""
Database Models Module
----------------------
Defines SQLAlchemy ORM models for sales transactions and data quality audit logs.
Ensures strong typing, constraints, indexation for fast analytical aggregations,
and separation between raw transaction recording and business eligibility.
"""

from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    Date,
    DateTime,
    Text,
    Index,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class SalesTransaction(Base):
    """
    Represents an individual sales transaction from the CSV dataset.
    Preserves audit integrity by tracking eligibility status and exclusion reasons
    rather than dropping or mutating records.
    """
    __tablename__ = "sales_transactions"

    transaction_id = Column(String(50), primary_key=True, index=True)
    order_date = Column(Date, nullable=False, index=True)
    product = Column(String(100), nullable=False, index=True)
    category = Column(String(100), nullable=False, index=True)
    region = Column(String(50), nullable=False, index=True)
    sales_channel = Column(String(50), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=True)
    discount_amount = Column(Float, nullable=False, default=0.0)
    gross_revenue = Column(Float, nullable=True)
    net_revenue = Column(Float, nullable=True)
    status = Column(String(50), nullable=False, index=True)
    
    # Data Quality and Business Eligibility Flags
    is_eligible = Column(Boolean, nullable=False, default=True, index=True)
    exclusion_reason = Column(String(255), nullable=True)
    
    imported_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_eligible_status_date", "is_eligible", "order_date"),
        Index("idx_eligible_product", "is_eligible", "product"),
        Index("idx_eligible_region", "is_eligible", "region"),
    )

    def to_dict(self) -> dict:
        """Convert transaction model instance to dictionary."""
        return {
            "transaction_id": self.transaction_id,
            "order_date": self.order_date.isoformat() if self.order_date else None,
            "product": self.product,
            "category": self.category,
            "region": self.region,
            "sales_channel": self.sales_channel,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "discount_amount": self.discount_amount,
            "gross_revenue": self.gross_revenue,
            "net_revenue": self.net_revenue,
            "status": self.status,
            "is_eligible": bool(self.is_eligible),
            "exclusion_reason": self.exclusion_reason,
            "imported_at": self.imported_at.isoformat() if self.imported_at else None,
        }


class DataQualityLog(Base):
    """
    Audit log of data import runs and quality metrics.
    Tracks lineage, cleanliness ratios, and anomaly counts.
    """
    __tablename__ = "data_quality_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    import_timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    source_filename = Column(String(255), nullable=False)
    total_records = Column(Integer, nullable=False)
    eligible_records = Column(Integer, nullable=False)
    excluded_records = Column(Integer, nullable=False)
    notes = Column(Text, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "import_timestamp": self.import_timestamp.isoformat(),
            "source_filename": self.source_filename,
            "total_records": self.total_records,
            "eligible_records": self.eligible_records,
            "excluded_records": self.excluded_records,
            "notes": self.notes,
        }
