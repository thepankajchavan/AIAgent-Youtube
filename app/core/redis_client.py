"""
Async Redis client for caching and pub/sub.

Provides a singleton async Redis connection using redis.asyncio.
"""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import get_settings

_redis_client: Redis | None = None


async def get_redis_client() -> Redis:
    """Return a cached async Redis client."""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _redis_client


async def close_redis_client() -> None:
    """Close the async Redis connection."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
