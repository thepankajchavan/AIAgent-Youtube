"""
Search Service — fetches real-time web context via Tavily before script generation.

Provides current facts, names, dates, and statistics so the LLM can write
accurate, timely scripts instead of generic or fictional content.

Features:
  - Multi-query expansion: generates 2-3 related queries for broader coverage
  - Credibility scoring: ranks results by domain authority
  - Graceful degradation: returns None on any failure

Graceful degradation: returns None on any failure so the pipeline
continues without search context (same as before this feature).
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from loguru import logger

from app.core.config import get_settings

settings = get_settings()

TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# ── Domain Authority ──────────────────────────────────────────────

HIGH_AUTHORITY_DOMAINS: set[str] = {
    "nature.com",
    "sciencedirect.com",
    "bbc.com",
    "reuters.com",
    "nasa.gov",
    "nih.gov",
    "wikipedia.org",
    "smithsonianmag.com",
    "nationalgeographic.com",
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "apnews.com",
    "nytimes.com",
    "theguardian.com",
    "sciencemag.org",
    "britannica.com",
    "who.int",
    "un.org",
    "noaa.gov",
    "usgs.gov",
}


def _expand_queries(topic: str) -> list[str]:
    """Generate 2-3 search queries for broader coverage of a topic."""
    return [
        topic,
        f"{topic} facts statistics",
        f"{topic} surprising unknown",
    ]


def _score_and_rank_results(results: list[dict]) -> list[dict]:
    """Score results by domain authority and sort descending.

    High-authority domains (.gov, known publications) get 0.9,
    others get 0.5. Results are sorted by credibility score.
    """
    for r in results:
        url = r.get("url", "")
        try:
            domain = urlparse(url).netloc.lstrip("www.")
        except Exception:
            domain = ""

        # Check exact match or if domain ends with a known authority
        is_authority = domain in HIGH_AUTHORITY_DOMAINS or any(
            domain.endswith(f".{d}") or domain == d
            for d in HIGH_AUTHORITY_DOMAINS
        )
        r["credibility"] = 0.9 if is_authority else 0.5

    return sorted(results, key=lambda r: r.get("credibility", 0.5), reverse=True)


async def _tavily_search(
    query: str,
    max_results: int = 5,
) -> list[dict]:
    """Execute a single Tavily search query. Returns list of result dicts."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                TAVILY_SEARCH_URL,
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                    "include_answer": True,
                },
            )
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        answer = data.get("answer")

        # Attach the AI answer to results for later formatting
        return [{"_answer": answer, **r} for r in results] if results else []

    except Exception as exc:
        logger.warning("Tavily search failed for query '{}': {}", query[:50], exc)
        return []


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
        # Multi-query expansion
        if getattr(settings, "search_multi_query_enabled", True):
            queries = _expand_queries(topic)
        else:
            queries = [topic]

        # Execute all queries
        all_results: list[dict] = []
        for query in queries:
            results = await _tavily_search(query, max_results=max_results)
            all_results.extend(results)

        if not all_results:
            return None

        # Deduplicate by URL
        seen_urls: set[str] = set()
        unique_results: list[dict] = []
        for r in all_results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(r)

        # Credibility scoring and ranking
        if getattr(settings, "search_credibility_enabled", True):
            unique_results = _score_and_rank_results(unique_results)

        # Take top results (double the max for multi-query coverage)
        top_results = unique_results[:max_results * 2]

        return _format_search_results(top_results)

    except httpx.TimeoutException:
        logger.warning("Tavily search timed out for topic: {}", topic)
        return None
    except httpx.HTTPStatusError as exc:
        logger.warning("Tavily API error {}: {}", exc.response.status_code, exc)
        return None
    except Exception as exc:
        logger.warning("Web search failed (non-fatal): {}", exc)
        return None


def _format_search_results(results: list[dict]) -> str | None:
    """Format search results into a text block for LLM prompt injection."""
    parts: list[str] = []

    # Extract AI-generated summary from first result (if available)
    answer = None
    for r in results:
        if "_answer" in r and r["_answer"]:
            answer = r["_answer"]
            break

    if answer:
        parts.append(f"Summary: {answer}")

    # Individual search results
    for i, result in enumerate(results, 1):
        title = result.get("title", "")
        content = result.get("content", "")
        credibility = result.get("credibility")
        credibility_tag = " [HIGH AUTHORITY]" if credibility and credibility >= 0.9 else ""

        if title or content:
            parts.append(f"Source {i}{credibility_tag}: {title}\n{content}")

    if not parts:
        return None

    formatted = "\n\n".join(parts)
    logger.info(
        "Web search context ready — {} sources, {} chars",
        len(results),
        len(formatted),
    )
    return formatted
