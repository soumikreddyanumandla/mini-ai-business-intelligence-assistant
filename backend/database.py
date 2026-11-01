"""
Database Management Module
--------------------------
Configures SQLAlchemy SQLite engine, session factories, transaction scopes,
and schema initialization routines.
"""

import logging
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from backend.config import settings
from backend.models import Base

logger = logging.getLogger(__name__)

# SQLite requires check_same_thread=False for multithreaded FastAPI / background workers
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=settings.DEBUG,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(drop_existing: bool = False) -> None:
    """
    Initializes database schema.
    If drop_existing is True, drops all existing tables before recreating.
    """
    if drop_existing:
        logger.warning("Dropping all existing database tables for fresh schema creation.")
        Base.metadata.drop_all(bind=engine)
    
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema initialized successfully.")


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency yielding a scoped database session.
    Ensures safe rollback on uncaught exceptions and cleanup upon request completion.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_health() -> bool:
    """Performs a lightweight ping query to verify database connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False
