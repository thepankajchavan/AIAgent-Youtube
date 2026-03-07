"""
Search Service — fetches real-time web context via Tavily before script generation.

Provides current facts, names, dates, and statistics so the LLM can write
accurate, timely scripts instead of generic or fictional content.

Graceful degradation: returns None on any failure so the pipeline
continues without search context (same as before this feature).
"""

from __future__ import annotations

import httpx
from loguru import logger

from app.core.config import get_settings

settings = get_settings()

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


async def search_topic_context(
    topic: str,
    max_results: int | None = None,
) -> str | None:
    """
    Search the web for real-time context about a topic.

    Args:
        topic: The video topic to research.
        max_results: Number of results (defaults to settings.web_search_max_results).

    Returns:
        Formatted string of search results for LLM prompt injection,
        or None if search is disabled, unconfigured, or fails.
    """
    if not settings.web_search_enabled:
        logger.debug("Web search disabled — skipping")
        return None

    if not settings.tavily_api_key:
        logger.debug("Tavily API key not configured — skipping web search")
        return None

    if max_results is None:
        max_results = settings.web_search_max_results

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                TAVILY_SEARCH_URL,
                json={
                    "api_key": settings.tavily_api_key,
                    "query": topic,
                    "search_depth": "basic",
                    "max_results": max_results,
                    "include_answer": True,
                },
            )
            response.raise_for_status()
            data = response.json()

        return _format_search_results(data)

    except httpx.TimeoutException:
        logger.warning("Tavily search timed out for topic: {}", topic)
        return None
    except httpx.HTTPStatusError as exc:
        logger.warning("Tavily API error {}: {}", exc.response.status_code, exc)
        return None
    except Exception as exc:
        logger.warning("Web search failed (non-fatal): {}", exc)
        return None


def _format_search_results(data: dict) -> str | None:
    """Format Tavily API response into a text block for LLM prompt injection."""
    parts: list[str] = []

    # AI-generated summary (Tavily's answer)
    answer = data.get("answer")
    if answer:
        parts.append(f"Summary: {answer}")

    # Individual search results
    results = data.get("results", [])
    for i, result in enumerate(results, 1):
        title = result.get("title", "")
        content = result.get("content", "")
        if title or content:
            parts.append(f"Source {i}: {title}\n{content}")

    if not parts:
        return None

    formatted = "\n\n".join(parts)
    logger.info(
        "Web search context ready — {} sources, {} chars",
        len(results),
        len(formatted),
    )
    return formatted
