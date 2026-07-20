import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.db.postgres import init_postgres, get_db_session, PlatformAccount, Platform
from app.db.mongodb import connect_mongo, close_mongo, get_mongo_db, get_comments_collection, get_video_payloads_collection

# Marks all tests in this file as async
pytestmark = pytest.mark.asyncio

async def test_postgres_init_success():
    """Test that init_postgres creates tables successfully on the async engine."""
    with patch("app.db.postgres.async_engine") as mock_engine:
        # Mock engine.begin() context manager
        mock_conn = AsyncMock()
        mock_engine.begin.return_value.__aenter__.return_value = mock_conn
        
        await init_postgres()
        
        # Verify run_sync was called to create the tables
        mock_engine.begin.assert_called_once()
        mock_conn.run_sync.assert_called_once_with(SQLModel.metadata.create_all)

async def test_postgres_get_db_session():
    """Test that get_db_session yields an AsyncSession and commits/rolls back properly."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.__aenter__.return_value = mock_session
    
    with patch("app.db.postgres.AsyncSessionLocal", return_value=mock_session):
        # 1. Test success path (should commit)
        generator = get_db_session()
        yielded_session = await generator.__anext__()
        assert yielded_session is mock_session
        
        # Simulating generator exit on success
        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()
        
        mock_session.commit.assert_called_once()
        mock_session.rollback.assert_not_called()

async def test_postgres_get_db_session_rollback():
    """Test that get_db_session rolls back on exception."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.__aenter__.return_value = mock_session
    
    with patch("app.db.postgres.AsyncSessionLocal", return_value=mock_session):
        generator = get_db_session()
        yielded_session = await generator.__anext__()
        assert yielded_session is mock_session
        
        # Simulating exception in route handler
        with pytest.raises(ValueError):
            # Throw exception into generator
            await generator.athrow(ValueError("Database failure"))
            
        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()

async def test_mongo_lifecycle_and_collections():
    """Test that connect_mongo, get_mongo_db, and collections function as expected with a mock client."""
    mock_client = AsyncMock()
    mock_db = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    
    # Mock ping command returning success
    mock_client.admin.command = AsyncMock(return_value={"ok": 1.0})
    
    with patch("app.db.mongodb.AsyncIOMotorClient", return_value=mock_client), \
         patch("app.db.mongodb.certifi") as mock_certifi:
        
        mock_certifi.where.return_value = "/mock/certifi/path"
        
        # 1. Verify get_mongo_db raises if client is not initialized
        from app.db import mongodb
        mongodb._client = None
        with pytest.raises(RuntimeError):
            get_mongo_db()
            
        # 2. Connect
        await connect_mongo()
        
        # 3. Test db retrieval and collection accessors
        db = get_mongo_db()
        assert db is mock_db
        
        # Comments collection
        comments_col = get_comments_collection()
        mock_db.__getitem__.assert_any_call("comments")
        
        # Video payloads collection
        payloads_col = get_video_payloads_collection()
        mock_db.__getitem__.assert_any_call("video_payloads")
        
        # 4. Close client
        await close_mongo()
        
        # 5. Check raises after closing
        with pytest.raises(RuntimeError):
            get_mongo_db()
