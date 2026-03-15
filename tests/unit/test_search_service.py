"""Tests for search service — Tavily web search with multi-query + credibility."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.search_service import (
    HIGH_AUTHORITY_DOMAINS,
    _expand_queries,
    _format_search_results,
    _score_and_rank_results,
    _tavily_search,
    search_topic_context,
)


# ── Fixtures ──────────────────────────────────────────────────


def _tavily_results():
    """Sample Tavily API search results (list of dicts)."""
    return [
        {
            "_answer": "The T20 Cricket World Cup final is India vs New Zealand on March 8, 2026 in Mumbai.",
            "title": "T20 World Cup 2026 Final: India vs NZ",
            "content": "India will face New Zealand in the T20 World Cup final at Wankhede Stadium, Mumbai on March 8.",
            "url": "https://example.com/cricket",
        },
        {
            "_answer": None,
            "title": "Cricket Final Preview",
            "content": "Both teams are unbeaten in the tournament so far.",
            "url": "https://example.com/preview",
        },
    ]


# ── search_topic_context tests ───────────────────────────────


class TestSearchTopicContext:
    """Tests for the main search function."""

    @pytest.mark.asyncio
    async def test_success_returns_formatted_context(self):
        """Successful Tavily call returns formatted search results."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "answer": "India vs NZ final",
            "results": [
                {
                    "title": "T20 World Cup Final",
                    "content": "India vs New Zealand at Wankhede Stadium, Mumbai on March 8.",
                    "url": "https://example.com/cricket",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()

        mock_settings = MagicMock()
        mock_settings.web_search_enabled = True
        mock_settings.tavily_api_key = "tvly-test-key"
        mock_settings.web_search_max_results = 5
        mock_settings.search_multi_query_enabled = False  # Single query for simplicity
        mock_settings.search_credibility_enabled = False

        with (
            patch("app.services.search_service.settings", mock_settings),
            patch("app.services.search_service.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await search_topic_context("t20 cricket final")

        assert result is not None
        assert "India vs New Zealand" in result or "India vs NZ" in result

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        """Returns None when web_search_enabled is False."""
        mock_settings = MagicMock()
        mock_settings.web_search_enabled = False

        with patch("app.services.search_service.settings", mock_settings):
            result = await search_topic_context("any topic")

        assert result is None

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self):
        """Returns None when tavily_api_key is empty."""
        mock_settings = MagicMock()
        mock_settings.web_search_enabled = True
        mock_settings.tavily_api_key = ""

        with patch("app.services.search_service.settings", mock_settings):
            result = await search_topic_context("any topic")

        assert result is None

    @pytest.mark.asyncio
    async def test_api_error_returns_none(self):
        """Returns None on HTTP error (graceful degradation)."""
        mock_settings = MagicMock()
        mock_settings.web_search_enabled = True
        mock_settings.tavily_api_key = "tvly-test-key"
        mock_settings.web_search_max_results = 5
        mock_settings.search_multi_query_enabled = False
        mock_settings.search_credibility_enabled = False

        with (
            patch("app.services.search_service.settings", mock_settings),
            patch("app.services.search_service.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Unauthorized", request=MagicMock(), response=mock_response
            )
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await search_topic_context("any topic")

        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        """Returns None on timeout (graceful degradation)."""
        mock_settings = MagicMock()
        mock_settings.web_search_enabled = True
        mock_settings.tavily_api_key = "tvly-test-key"
        mock_settings.web_search_max_results = 5
        mock_settings.search_multi_query_enabled = False
        mock_settings.search_credibility_enabled = False

        with (
            patch("app.services.search_service.settings", mock_settings),
            patch("app.services.search_service.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await search_topic_context("any topic")

        assert result is None

    @pytest.mark.asyncio
    async def test_multi_query_expands_searches(self):
        """Multi-query mode sends 3 search queries."""
        call_count = 0

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "answer": "Answer",
            "results": [
                {"title": "Result", "content": "Content", "url": "https://example.com/1"},
            ],
        }
        mock_response.raise_for_status = MagicMock()

        mock_settings = MagicMock()
        mock_settings.web_search_enabled = True
        mock_settings.tavily_api_key = "tvly-test-key"
        mock_settings.web_search_max_results = 3
        mock_settings.search_multi_query_enabled = True
        mock_settings.search_credibility_enabled = False

        async def track_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_response

        with (
            patch("app.services.search_service.settings", mock_settings),
            patch("app.services.search_service.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=track_post)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await search_topic_context("mars exploration")

        # Should have made 3 API calls (one per expanded query)
        assert call_count == 3


# ── _expand_queries tests ──────────────────────────────────────


class TestExpandQueries:
    """Tests for multi-query expansion."""

    def test_returns_three_queries(self):
        queries = _expand_queries("mars exploration")
        assert len(queries) == 3

    def test_first_is_original_topic(self):
        queries = _expand_queries("black holes")
        assert queries[0] == "black holes"

    def test_all_contain_topic(self):
        queries = _expand_queries("neutron stars")
        for q in queries:
            assert "neutron stars" in q.lower()


# ── _score_and_rank_results tests ─────────────────────────────


class TestScoreAndRank:
    """Tests for credibility scoring and ranking."""

    def test_high_authority_ranked_first(self):
        results = [
            {"url": "https://random-blog.com/post", "title": "Blog Post"},
            {"url": "https://www.nasa.gov/article", "title": "NASA Article"},
        ]
        ranked = _score_and_rank_results(results)
        assert ranked[0]["title"] == "NASA Article"
        assert ranked[0]["credibility"] == 0.9

    def test_unknown_domain_gets_low_score(self):
        results = [{"url": "https://myblog.xyz/post", "title": "My Blog"}]
        ranked = _score_and_rank_results(results)
        assert ranked[0]["credibility"] == 0.5

    def test_multiple_authority_domains(self):
        results = [
            {"url": "https://www.bbc.com/news", "title": "BBC"},
            {"url": "https://random.com/x", "title": "Random"},
            {"url": "https://nature.com/paper", "title": "Nature"},
        ]
        ranked = _score_and_rank_results(results)
        # Both authority domains should be first
        assert ranked[0]["credibility"] == 0.9
        assert ranked[1]["credibility"] == 0.9
        assert ranked[2]["credibility"] == 0.5

    def test_empty_results(self):
        assert _score_and_rank_results([]) == []


# ── _format_search_results tests ─────────────────────────────


class TestFormatSearchResults:
    """Tests for result formatting."""

    def test_formats_answer_and_sources(self):
        results = _tavily_results()
        formatted = _format_search_results(results)

        assert formatted is not None
        assert "Summary:" in formatted
        assert "Source 1:" in formatted
        assert "Source 2:" in formatted

    def test_high_authority_tag_in_output(self):
        results = [
            {
                "_answer": None,
                "title": "NASA Discovery",
                "content": "New findings.",
                "url": "https://www.nasa.gov/discovery",
                "credibility": 0.9,
            },
        ]
        formatted = _format_search_results(results)
        assert "[HIGH AUTHORITY]" in formatted

    def test_no_answer_still_includes_sources(self):
        results = [{"title": "Test", "content": "Some content", "url": "https://example.com"}]
        formatted = _format_search_results(results)

        assert formatted is not None
        assert "Source 1: Test" in formatted
        assert "Summary:" not in formatted

    def test_empty_results_returns_none(self):
        result = _format_search_results([])
        assert result is None

    def test_answer_only_from_first_result(self):
        results = [
            {"_answer": "Quick answer here", "title": "T", "content": "C", "url": "https://x.com"},
        ]
        formatted = _format_search_results(results)
        assert "Summary: Quick answer here" in formatted
