"""
Pytest Configuration and Fixtures
---------------------------------
Sets up isolated in-memory SQLite databases for automated testing,
loads test fixtures, and configures FastAPI test clients.
"""

import sys
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.models import Base
from backend.database import get_db
from backend.data_loader import load_and_sync_csv_to_db
from backend.main import app

# Shared In-Memory SQLite Engine using StaticPool
TEST_DATABASE_URL = "sqlite://"


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine


@pytest.fixture(scope="function")
def db_session(test_engine):
    """Provides a clean in-memory database session populated with the sales dataset."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()
    
    # Load default dataset into this in-memory DB
    load_and_sync_csv_to_db(db=session)
    
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db_session, test_engine, monkeypatch):
    """FastAPI TestClient with overridden database dependency and session factory."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    from backend.config import settings
    monkeypatch.setattr(settings, "LLM_PROVIDER", "fallback")
    monkeypatch.setattr("backend.database.engine", test_engine)
    monkeypatch.setattr("backend.database.SessionLocal", TestingSessionLocal)
    monkeypatch.setattr("backend.main.SessionLocal", TestingSessionLocal)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
