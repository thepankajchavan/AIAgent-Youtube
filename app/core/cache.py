"""
Query Result Caching - Redis-backed caching for database queries.

Caches frequently accessed data to reduce database load:
- Project lists (recent, by status)
- Project details (by ID)
- User statistics
- External API responses (Pexels, ElevenLabs, YouTube)
"""

import hashlib
import json
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from loguru import logger

from app.core.redis_client import get_redis_client

# Type variable for generic function return types
T = TypeVar("T")


class QueryCache:
    """Redis-backed query result caching."""

    # Cache key prefixes
    PREFIX_PROJECT = "cache:project:"
    PREFIX_PROJECT_LIST = "cache:project_list:"
    PREFIX_USER_STATS = "cache:user_stats:"
    PREFIX_PEXELS = "cache:pexels:"
    PREFIX_ELEVENLABS = "cache:elevenlabs:"
    PREFIX_YOUTUBE = "cache:youtube:"

    # Default TTLs (in seconds)
    TTL_PROJECT = 60 * 5  # 5 minutes (projects change frequently)
    TTL_PROJECT_LIST = 60 * 2  # 2 minutes (lists change very frequently)
    TTL_USER_STATS = 60 * 10  # 10 minutes
    TTL_PEXELS = 60 * 60 * 24  # 24 hours (search results don't change often)
    TTL_ELEVENLABS = 60 * 60  # 1 hour (voice list rarely changes)
    TTL_YOUTUBE = 60 * 60 * 12  # 12 hours (categories/metadata)

    @classmethod
    async def get(cls, key: str) -> Any | None:
        """
        Get cached value by key.

        Args:
            key: Cache key

        Returns:
            Cached value (deserialized from JSON) or None if not found
        """
        redis = await get_redis_client()

        try:
            value = await redis.get(key)

            if value is None:
                return None

            # Deserialize JSON
            if isinstance(value, bytes):
                value = value.decode("utf-8")

            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to deserialize cached value for key {key}: {e}")
            # Delete corrupted cache entry
            await redis.delete(key)
            return None
        except Exception as e:
            logger.error(f"Cache get error for key {key}: {e}")
            return None

    @classmethod
    async def set(cls, key: str, value: Any, ttl: int | None = None) -> bool:
        """
        Set cached value with optional TTL.

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time to live in seconds (None = no expiry)

        Returns:
            True if successful, False otherwise
        """
        redis = await get_redis_client()

        try:
            # Serialize to JSON
            serialized = json.dumps(value)

            if ttl:
                await redis.setex(key, ttl, serialized)
            else:
                await redis.set(key, serialized)

            return True
        except (TypeError, ValueError) as e:
            logger.error(f"Failed to serialize value for key {key}: {e}")
            return False
        except Exception as e:
            logger.error(f"Cache set error for key {key}: {e}")
            return False

    @classmethod
    async def delete(cls, key: str) -> bool:
        """
        Delete cached value.

        Args:
            key: Cache key

        Returns:
            True if key existed and was deleted, False otherwise
        """
        redis = await get_redis_client()

        try:
            result = await redis.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"Cache delete error for key {key}: {e}")
            return False

    @classmethod
    async def delete_pattern(cls, pattern: str) -> int:
        """
        Delete all keys matching a pattern.

        Args:
            pattern: Redis key pattern (e.g., "cache:project:*")

        Returns:
            Number of keys deleted
        """
        redis = await get_redis_client()

        try:
            # Find all matching keys
            cursor = 0
            keys_deleted = 0

            while True:
                cursor, keys = await redis.scan(cursor, match=pattern, count=100)

                if keys:
                    deleted = await redis.delete(*keys)
                    keys_deleted += deleted

                if cursor == 0:
                    break

            logger.info(f"Deleted {keys_deleted} keys matching pattern: {pattern}")
            return keys_deleted
        except Exception as e:
            logger.error(f"Cache delete pattern error for {pattern}: {e}")
            return 0

    @classmethod
    async def invalidate_project(cls, project_id: int | str) -> None:
        """
        Invalidate all caches related to a specific project.

        Args:
            project_id: Project ID
        """
        await cls.delete(f"{cls.PREFIX_PROJECT}{project_id}")
        # Also invalidate project lists (they might contain this project)
        await cls.delete_pattern(f"{cls.PREFIX_PROJECT_LIST}*")
        logger.debug(f"Invalidated cache for project {project_id}")

    @classmethod
    async def invalidate_user_stats(cls, user_id: int) -> None:
        """
        Invalidate user statistics cache.

        Args:
            user_id: Telegram user ID
        """
        await cls.delete(f"{cls.PREFIX_USER_STATS}{user_id}")
        logger.debug(f"Invalidated user stats cache for user {user_id}")

    @classmethod
    def cache_key_hash(cls, *args, **kwargs) -> str:
        """
        Generate a deterministic cache key from function arguments.

        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            MD5 hash of arguments
        """
        # Create a stable string representation of arguments
        key_parts = []

        for arg in args:
            key_parts.append(str(arg))

        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}={v}")

        key_str = ":".join(key_parts)

        # Hash to keep key length reasonable
        return hashlib.md5(key_str.encode()).hexdigest()


def cached(prefix: str, ttl: int = 300, key_builder: Callable | None = None):
    """
    Decorator to cache function results in Redis.

    Args:
        prefix: Cache key prefix
        ttl: Time to live in seconds
        key_builder: Optional custom function to build cache key from args/kwargs

    Example:
        @cached(prefix="cache:project:", ttl=300)
        async def get_project(project_id: int):
            # ... expensive database query ...
            return project

    Returns:
        Decorated function with caching
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            # Build cache key
            if key_builder:
                cache_key = f"{prefix}{key_builder(*args, **kwargs)}"
            else:
                # Default: use function name + hash of arguments
                key_hash = QueryCache.cache_key_hash(*args, **kwargs)
                cache_key = f"{prefix}{func.__name__}:{key_hash}"

            # Try to get from cache
            cached_value = await QueryCache.get(cache_key)

            if cached_value is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return cached_value

            logger.debug(f"Cache MISS: {cache_key}")

            # Call original function
            result = await func(*args, **kwargs)

            # Cache the result
            await QueryCache.set(cache_key, result, ttl=ttl)

            return result

        return wrapper

    return decorator


# ── Convenience Functions for Common Cache Operations ─────────


async def cache_project(
    project_id: int, project_data: dict, ttl: int = QueryCache.TTL_PROJECT
) -> bool:
    """Cache project details."""
    key = f"{QueryCache.PREFIX_PROJECT}{project_id}"
    return await QueryCache.set(key, project_data, ttl=ttl)


async def get_cached_project(project_id: int) -> dict | None:
    """Get cached project details."""
    key = f"{QueryCache.PREFIX_PROJECT}{project_id}"
    return await QueryCache.get(key)


async def cache_pexels_search(query: str, results: list, ttl: int = QueryCache.TTL_PEXELS) -> bool:
    """Cache Pexels search results."""
    key = f"{QueryCache.PREFIX_PEXELS}{query}"
    return await QueryCache.set(key, results, ttl=ttl)


async def get_cached_pexels_search(query: str) -> list | None:
    """Get cached Pexels search results."""
    key = f"{QueryCache.PREFIX_PEXELS}{query}"
    return await QueryCache.get(key)


async def cache_elevenlabs_voices(voices: list, ttl: int = QueryCache.TTL_ELEVENLABS) -> bool:
    """Cache ElevenLabs voice list."""
    key = f"{QueryCache.PREFIX_ELEVENLABS}voices"
    return await QueryCache.set(key, voices, ttl=ttl)


async def get_cached_elevenlabs_voices() -> list | None:
    """Get cached ElevenLabs voice list."""
    key = f"{QueryCache.PREFIX_ELEVENLABS}voices"
    return await QueryCache.get(key)
