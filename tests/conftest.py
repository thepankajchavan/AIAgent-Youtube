"""Pytest configuration and shared fixtures."""

import asyncio
import pytest
from pathlib import Path
from typing import AsyncGenerator
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.main import app
from app.core.config import Settings, get_settings
from app.models.base import Base
from app.core.database import get_db

# Test database URL
TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/content_engine_test"
TEST_DATABASE_URL_SYNC = "postgresql+psycopg2://postgres:postgres@localhost:5432/content_engine_test"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Override settings for testing."""
    return Settings(
        database_url=TEST_DATABASE_URL,
        database_url_sync=TEST_DATABASE_URL_SYNC,
        debug=True,
        api_auth_enabled=False,  # Disable auth for testing
        cors_allowed_origins="*",
        # Provide minimal valid API keys to prevent validation errors
        openai_api_key="sk-test",
        anthropic_api_key="sk-ant-test",
        elevenlabs_api_key="test_key",
        pexels_api_key="test_key",
        telegram_bot_token="test:token",
    )


@pytest.fixture(scope="session")
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database session for each test."""
    async_session = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session
        await session.rollback()  # Rollback after each test


@pytest.fixture
async def client(db_session, test_settings) -> AsyncGenerator[AsyncClient, None]:
    """Create test client with database override."""

    async def override_get_db():
        yield db_session

    # Override settings
    app.dependency_overrides[get_db] = override_get_db

    # Temporarily override get_settings
    def override_get_settings():
        return test_settings

    from app.core import config
    original_get_settings = config.get_settings
    config.get_settings = override_get_settings

    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

    # Restore original functions
    app.dependency_overrides.clear()
    config.get_settings = original_get_settings


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_script(fixtures_dir) -> dict:
    """Load sample LLM script response."""
    import json
    script_path = fixtures_dir / "sample_script.json"
    if not script_path.exists():
        # Return default if file doesn't exist yet
        return {
            "title": "Test Video Title",
            "script": "Test script content",
            "tags": ["test", "shorts"],
            "description": "Test description"
        }
    with open(script_path) as f:
        return json.load(f)


@pytest.fixture
def sample_audio_path(fixtures_dir) -> Path:
    """Return path to sample audio file."""
    return fixtures_dir / "sample_audio.mp3"


@pytest.fixture
def sample_video_path(fixtures_dir) -> Path:
    """Return path to sample video file."""
    return fixtures_dir / "sample_video.mp4"
