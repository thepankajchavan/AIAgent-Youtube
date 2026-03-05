"""
Synchronous database session for Celery workers.

Celery tasks run in a sync context, so we use the psycopg2 (sync) driver
instead of asyncpg. This module provides a context manager that yields
a plain SQLAlchemy Session and handles commit/rollback/close.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_sync_engine = create_engine(
    settings.database_url_sync,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

_SyncSessionFactory = sessionmaker(bind=_sync_engine, expire_on_commit=False)


@contextmanager
def get_sync_db() -> Generator[Session, None, None]:
    """Yield a sync SQLAlchemy session with automatic commit/rollback."""
    session = _SyncSessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Database error in worker — rolled back")
        raise
    finally:
        session.close()
