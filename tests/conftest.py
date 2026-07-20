import asyncio
import os
from collections.abc import AsyncGenerator
from typing import AsyncGenerator as AsyncGeneratorType

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from mongomock_motor import AsyncMongoMockClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

# Set test environment variable so get_settings() returns test config
os.environ["APP_ENV"] = "development"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["POSTGRES_DSN"] = "sqlite+aiosqlite:///:memory:"
os.environ["MONGO_URI"] = "mongodb://localhost:27017"
os.environ["YOUTUBE_API_KEY"] = "test_yt_key"
os.environ["REDDIT_CLIENT_ID"] = "test_reddit_client"
os.environ["REDDIT_CLIENT_SECRET"] = "test_reddit_secret"

from app.main import app
from app.db.postgres import get_db_session
from app.db import mongodb

# ─── Async Test Environment Setup ──────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()

# ─── Database Fixtures ────────────────────────────────────────────────────────

# Use a memory SQLite database for SQLModel/Postgres tests
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

TestSessionLocal = sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def override_get_db_session() -> AsyncGeneratorType[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session

@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGeneratorType[AsyncSession, None]:
    """Provides a fresh database session for a test function."""
    async with test_engine.begin() as conn:
        # Create all tables before the test
        await conn.run_sync(SQLModel.metadata.create_all)
        
    async with TestSessionLocal() as session:
        yield session
        
    async with test_engine.begin() as conn:
        # Drop all tables after the test
        await conn.run_sync(SQLModel.metadata.drop_all)

# Override FastAPI dependency
app.dependency_overrides[get_db_session] = override_get_db_session

# Mock MongoDB
@pytest_asyncio.fixture(scope="function", autouse=True)
async def mock_mongo(monkeypatch):
    """Patch the motor client with a mongomock instance."""
    mock_client = AsyncMongoMockClient()
    monkeypatch.setattr(mongodb, "_client", mock_client)
    yield mock_client

# ─── FastAPI Client Fixture ───────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def test_client(db_session) -> AsyncGeneratorType[AsyncClient, None]:
    """Test client for FastAPI endpoints. Requires db_session fixture to ensure tables exist."""
    # Note: ASGITransport handles the ASGI app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
