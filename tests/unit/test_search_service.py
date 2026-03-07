"""Tests for search service — Tavily web search integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.search_service import _format_search_results, search_topic_context


# ── Fixtures ──────────────────────────────────────────────────


def _tavily_response():
    """Sample Tavily API response."""
    return {
        "answer": "The T20 Cricket World Cup final is India vs New Zealand on March 8, 2026 in Mumbai.",
        "results": [
            {
                "title": "T20 World Cup 2026 Final: India vs NZ",
                "content": "India will face New Zealand in the T20 World Cup final at Wankhede Stadium, Mumbai on March 8.",
                "url": "https://example.com/cricket",
            },
            {
                "title": "Cricket Final Preview",
                "content": "Both teams are unbeaten in the tournament so far.",
                "url": "https://example.com/preview",
            },
        ],
    }


# ── search_topic_context tests ───────────────────────────────


class TestSearchTopicContext:
    """Tests for the main search function."""

    @pytest.mark.asyncio
    async def test_success_returns_formatted_context(self):
        """Successful Tavily call returns formatted search results."""
        mock_response = MagicMock()
        mock_response.json.return_value = _tavily_response()
        mock_response.raise_for_status = MagicMock()

        mock_settings = MagicMock()
        mock_settings.web_search_enabled = True
        mock_settings.tavily_api_key = "tvly-test-key"
        mock_settings.web_search_max_results = 5

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
        assert "India vs New Zealand" in result
        assert "March 8" in result
        assert "Wankhede Stadium" in result

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
    async def test_passes_correct_params_to_tavily(self):
        """Verify correct parameters are sent to Tavily API."""
        mock_response = MagicMock()
        mock_response.json.return_value = _tavily_response()
        mock_response.raise_for_status = MagicMock()

        mock_settings = MagicMock()
        mock_settings.web_search_enabled = True
        mock_settings.tavily_api_key = "tvly-my-key"
        mock_settings.web_search_max_results = 3

        with (
            patch("app.services.search_service.settings", mock_settings),
            patch("app.services.search_service.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await search_topic_context("mars exploration", max_results=3)

        # Check the POST call arguments
        call_kwargs = mock_client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["api_key"] == "tvly-my-key"
        assert payload["query"] == "mars exploration"
        assert payload["max_results"] == 3
        assert payload["include_answer"] is True


# ── _format_search_results tests ─────────────────────────────


class TestFormatSearchResults:
    """Tests for result formatting."""

    def test_formats_answer_and_sources(self):
        """Includes AI summary and numbered sources."""
        result = _format_search_results(_tavily_response())

        assert result is not None
        assert "Summary:" in result
        assert "Source 1:" in result
        assert "Source 2:" in result
        assert "India vs New Zealand" in result

    def test_no_answer_still_includes_sources(self):
        """Works when Tavily returns no AI answer."""
        data = {"results": [{"title": "Test", "content": "Some content"}]}
        result = _format_search_results(data)

        assert result is not None
        assert "Source 1: Test" in result
        assert "Summary:" not in result

    def test_empty_results_returns_none(self):
        """Returns None when no results and no answer."""
        result = _format_search_results({"results": []})
        assert result is None

    def test_answer_only_no_results(self):
        """Works with just an AI answer and no search results."""
        data = {"answer": "Quick answer here", "results": []}
        result = _format_search_results(data)

        assert result is not None
        assert "Summary: Quick answer here" in result
