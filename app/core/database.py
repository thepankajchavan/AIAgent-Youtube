from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from loguru import logger

from app.core.config import get_settings

settings = get_settings()

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # Connection pool optimization (Phase 8)
    pool_size=20,              # Base pool size (increased from 10)
    max_overflow=40,           # Max overflow connections (increased from 20)
    pool_pre_ping=True,        # Verify connections before using
    pool_recycle=3600,         # Recycle connections after 1 hour
    pool_timeout=30,           # Connection timeout (seconds)
    connect_args={
        "server_settings": {
            "application_name": "youtube_shorts_automation",
            "jit": "off"       # Disable JIT compilation for faster queries
        }
    }
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async database session and ensures cleanup."""
    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async generator for database sessions (for use in non-FastAPI contexts).

    Usage:
        async for session in get_async_session():
            # Use session
            await session.commit()
    """
    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Gracefully close the connection pool (called on app shutdown)."""
    logger.info("Disposing database engine …")
    await engine.dispose()
