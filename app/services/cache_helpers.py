"""
Cache Helpers - Caching wrappers for external API responses.

Provides cached access to:
- ElevenLabs voice list
- YouTube video categories
- Common API metadata
"""

from typing import Any
from loguru import logger

from app.core.cache import QueryCache


async def get_elevenlabs_voices_cached() -> list[dict] | None:
    """
    Get ElevenLabs voice list with caching.

    Caches for 1 hour since voice list rarely changes.

    Returns:
        List of voice dictionaries or None if not cached
    """
    cache_key = f"{QueryCache.PREFIX_ELEVENLABS}voices"
    cached = await QueryCache.get(cache_key)

    if cached:
        logger.debug("Cache HIT: ElevenLabs voices")
        return cached

    logger.debug("Cache MISS: ElevenLabs voices")
    return None


async def cache_elevenlabs_voices(voices: list[dict]) -> bool:
    """
    Cache ElevenLabs voice list.

    Args:
        voices: List of voice dictionaries

    Returns:
        True if successfully cached
    """
    cache_key = f"{QueryCache.PREFIX_ELEVENLABS}voices"
    success = await QueryCache.set(cache_key, voices, ttl=QueryCache.TTL_ELEVENLABS)

    if success:
        logger.info(f"Cached {len(voices)} ElevenLabs voices")

    return success


async def get_youtube_categories_cached(region_code: str = "US") -> list[dict] | None:
    """
    Get YouTube video categories with caching.

    Caches for 12 hours since categories don't change often.

    Args:
        region_code: YouTube region code (e.g., "US", "GB")

    Returns:
        List of category dictionaries or None if not cached
    """
    cache_key = f"{QueryCache.PREFIX_YOUTUBE}categories:{region_code}"
    cached = await QueryCache.get(cache_key)

    if cached:
        logger.debug(f"Cache HIT: YouTube categories ({region_code})")
        return cached

    logger.debug(f"Cache MISS: YouTube categories ({region_code})")
    return None


async def cache_youtube_categories(categories: list[dict], region_code: str = "US") -> bool:
    """
    Cache YouTube video categories.

    Args:
        categories: List of category dictionaries
        region_code: YouTube region code

    Returns:
        True if successfully cached
    """
    cache_key = f"{QueryCache.PREFIX_YOUTUBE}categories:{region_code}"
    success = await QueryCache.set(cache_key, categories, ttl=QueryCache.TTL_YOUTUBE)

    if success:
        logger.info(f"Cached {len(categories)} YouTube categories for {region_code}")

    return success


async def get_script_template_cached(provider: str, style: str = "default") -> str | None:
    """
    Get cached script generation template/prompt.

    Args:
        provider: LLM provider (openai, anthropic)
        style: Script style (default, educational, entertainment)

    Returns:
        Cached template or None
    """
    cache_key = f"cache:script_template:{provider}:{style}"
    cached = await QueryCache.get(cache_key)

    if cached:
        logger.debug(f"Cache HIT: Script template ({provider}/{style})")
        return cached

    return None


async def cache_script_template(template: str, provider: str, style: str = "default") -> bool:
    """
    Cache script generation template.

    Args:
        template: Template/prompt string
        provider: LLM provider
        style: Script style

    Returns:
        True if successfully cached
    """
    cache_key = f"cache:script_template:{provider}:{style}"
    # Cache templates for 7 days (they rarely change)
    success = await QueryCache.set(cache_key, template, ttl=60 * 60 * 24 * 7)

    if success:
        logger.info(f"Cached script template ({provider}/{style})")

    return success


async def invalidate_all_caches() -> dict[str, int]:
    """
    Invalidate all application caches.

    Useful for debugging or forcing cache refresh.

    Returns:
        Dictionary with count of keys deleted per cache type
    """
    results = {}

    # Invalidate each cache type
    results["projects"] = await QueryCache.delete_pattern(f"{QueryCache.PREFIX_PROJECT}*")
    results["project_lists"] = await QueryCache.delete_pattern(f"{QueryCache.PREFIX_PROJECT_LIST}*")
    results["user_stats"] = await QueryCache.delete_pattern(f"{QueryCache.PREFIX_USER_STATS}*")
    results["pexels"] = await QueryCache.delete_pattern(f"{QueryCache.PREFIX_PEXELS}*")
    results["elevenlabs"] = await QueryCache.delete_pattern(f"{QueryCache.PREFIX_ELEVENLABS}*")
    results["youtube"] = await QueryCache.delete_pattern(f"{QueryCache.PREFIX_YOUTUBE}*")

    total = sum(results.values())
    logger.warning(f"Invalidated {total} cache keys across all cache types")

    return results


async def get_cache_statistics() -> dict[str, Any]:
    """
    Get cache usage statistics.

    Returns:
        Dictionary with cache statistics
    """
    from app.core.redis_client import get_redis_client

    redis = await get_redis_client()

    # Get memory usage
    info = await redis.info("memory")

    # Count keys by prefix
    stats = {
        "memory": {
            "used_memory": info.get("used_memory"),
            "used_memory_human": info.get("used_memory_human"),
            "used_memory_peak": info.get("used_memory_peak"),
            "used_memory_peak_human": info.get("used_memory_peak_human")
        },
        "key_counts": {}
    }

    # Count keys for each cache type
    for cache_type, prefix in [
        ("projects", QueryCache.PREFIX_PROJECT),
        ("project_lists", QueryCache.PREFIX_PROJECT_LIST),
        ("user_stats", QueryCache.PREFIX_USER_STATS),
        ("pexels", QueryCache.PREFIX_PEXELS),
        ("elevenlabs", QueryCache.PREFIX_ELEVENLABS),
        ("youtube", QueryCache.PREFIX_YOUTUBE)
    ]:
        # Use SCAN to count keys matching pattern
        count = 0
        cursor = 0

        while True:
            cursor, keys = await redis.scan(cursor, match=f"{prefix}*", count=100)
            count += len(keys)

            if cursor == 0:
                break

        stats["key_counts"][cache_type] = count

    stats["total_cached_keys"] = sum(stats["key_counts"].values())

    return stats
