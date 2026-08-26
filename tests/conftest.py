"""Pytest configuration and shared fixtures."""
import os
import sys
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
import pytest
from fastapi.testclient import TestClient

# Set test environment before importing app modules
os.environ.update({
    "ADMIN_PASSWORD": "test_password",
    "SECRET_KEY": "test_secret_key_for_testing_only",
    "WORKER_TOKEN": "test_worker_token",
    "LLM_API_KEY": "test_llm_key",
})

# Pre-mock MCP to avoid v1/v2 incompatibility
# The mock must return an async callable for asgi_dispatcher to work
_async_app = AsyncMock(return_value=None)
sys.modules['mcp'] = MagicMock()
sys.modules['mcp.server'] = MagicMock()
sys.modules['mcp.server.fastmcp'] = MagicMock()
_mcp_app_module = MagicMock()
_mcp_app_module.get_mcp_app = lambda: _async_app
sys.modules['app.api.mcp'] = _mcp_app_module

from app.database import init_db, get_conn, connect
from app.main import app
from app.config import settings


@pytest.fixture(scope="function")
def test_db_path(tmp_path):
    """Create a temporary database file for testing."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    yield db_path


@pytest.fixture(scope="function")
def db_conn(test_db_path):
    """Provide a database connection with autocommit for testing."""
    conn = connect(test_db_path)
    conn.isolation_level = None  # autocommit so data is visible to client fixture
    yield conn
    conn.close()


@pytest.fixture(scope="function")
def client(test_db_path):
    """Create a test client with isolated database."""
    original_path = settings.database_path
    settings.database_path = test_db_path
    try:
        with TestClient(app) as client:
            yield client
    finally:
        settings.database_path = original_path


@pytest.fixture(scope="function")
def authenticated_client(client):
    """Create an authenticated test client."""
    response = client.post("/login", data={
        "password": "test_password",
        "next_url": "/admin"
    }, follow_redirects=False)
    assert response.status_code in [200, 303]
    yield client


@pytest.fixture
def sample_video_data():
    return {
        "youtube_id": "dQw4w9WgXcQ",
        "title": "Rick Astley - Never Gonna Give You Up",
        "channel": "Rick Astley",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "duration_seconds": 213
    }


@pytest.fixture
def sample_article_data():
    return {
        "title": "Test Article",
        "slug": "test-article",
        "content_markdown": "# Test Article\n\nThis is a test article.",
        "category": "test",
        "source_channel": "Test Channel",
        "source_url": "https://youtube.com/watch?v=test",
        "dtc_codes": "P0123,P0456",
        "vehicle_refs": "Honda Civic,Toyota Corolla",
        "tools_used": "OBD scanner,Multimeter",
        "status": "draft"
    }


@pytest.fixture
def sample_transcript_data():
    return {
        "raw_text": "Hello world. This is a test transcript.",
        "segments": [
            {"start": 0.0, "duration": 2.5, "text": "Hello world."},
            {"start": 2.5, "duration": 3.0, "text": "This is a test transcript."}
        ],
        "language": "en",
        "is_auto_generated": True
    }


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)
