"""Tests for app.services.viral_service — ViralOptimizer."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.viral_service import (
    GENERIC_VIRAL_HASHTAGS,
    NICHE_HASHTAG_POOLS,
    ViralOptimizer,
)


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture
def optimizer():
    with patch("app.services.viral_service.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock()
        return ViralOptimizer()


# ── get_niche_hashtag_pool ───────────────────────────────────

class TestGetNicheHashtagPool:
    def test_science_niche(self, optimizer):
        result = optimizer.get_niche_hashtag_pool("science")
        assert len(result) <= 6
        assert all(tag.startswith("#") for tag in result)
        assert "#ScienceFacts" in result

    def test_technology_niche(self, optimizer):
        result = optimizer.get_niche_hashtag_pool("technology")
        assert "#TechNews" in result
        assert "#AI" in result

    def test_history_niche(self, optimizer):
        result = optimizer.get_niche_hashtag_pool("history")
        assert "#HistoryFacts" in result

    def test_motivation_niche(self, optimizer):
        result = optimizer.get_niche_hashtag_pool("motivation")
        assert "#Motivation" in result

    def test_psychology_niche(self, optimizer):
        result = optimizer.get_niche_hashtag_pool("psychology")
        assert "#Psychology" in result

    def test_space_niche(self, optimizer):
        result = optimizer.get_niche_hashtag_pool("space")
        assert "#Space" in result

    def test_entertainment_niche(self, optimizer):
        result = optimizer.get_niche_hashtag_pool("entertainment")
        assert "#Entertainment" in result

    def test_unknown_niche_returns_generic(self, optimizer):
        result = optimizer.get_niche_hashtag_pool("cooking")
        assert result == GENERIC_VIRAL_HASHTAGS[:5]

    def test_none_niche_returns_generic(self, optimizer):
        result = optimizer.get_niche_hashtag_pool(None)
        assert result == GENERIC_VIRAL_HASHTAGS[:5]

    def test_all_niches_have_hashtag_prefix(self, optimizer):
        for niche in NICHE_HASHTAG_POOLS:
            result = optimizer.get_niche_hashtag_pool(niche)
            for tag in result:
                assert tag.startswith("#"), f"Tag '{tag}' in niche '{niche}' missing #"


# ── build_viral_prompt_context ───────────────────────────────

class TestBuildViralPromptContext:
    def test_full_context(self, optimizer):
        data = {
            "trending_hashtags": ["#AIRevolution", "#TechTrends2026"],
            "trending_keywords": ["ai agents explained", "ai automation 2026"],
            "velocity": "rising",
            "viral_potential": 0.8,
            "niche_hashtags": ["#TechShorts", "#AI"],
        }
        result = optimizer.build_viral_prompt_context(data)

        assert "TRENDING CONTEXT" in result
        assert "#AIRevolution" in result
        assert "ai agents explained" in result
        assert "RISING" in result
        assert "HIGH VIRAL POTENTIAL" in result
        assert "#TechShorts" in result

    def test_empty_context(self, optimizer):
        data = {
            "trending_hashtags": [],
            "trending_keywords": [],
            "velocity": "rising",
            "viral_potential": 0.0,
            "niche_hashtags": [],
        }
        result = optimizer.build_viral_prompt_context(data)

        assert "TRENDING CONTEXT" in result
        assert "RISING" in result
        # No HIGH VIRAL POTENTIAL for low score
        assert "HIGH VIRAL POTENTIAL" not in result

    def test_peaked_velocity(self, optimizer):
        data = {
            "trending_hashtags": [],
            "trending_keywords": [],
            "velocity": "peaked",
            "viral_potential": 0.0,
            "niche_hashtags": [],
        }
        result = optimizer.build_viral_prompt_context(data)
        assert "PEAKED" in result

    def test_declining_velocity(self, optimizer):
        data = {
            "trending_hashtags": [],
            "trending_keywords": [],
            "velocity": "declining",
            "viral_potential": 0.0,
            "niche_hashtags": [],
        }
        result = optimizer.build_viral_prompt_context(data)
        assert "DECLINING" in result

    def test_moderate_viral_potential(self, optimizer):
        data = {
            "trending_hashtags": [],
            "trending_keywords": [],
            "velocity": "rising",
            "viral_potential": 0.4,
            "niche_hashtags": [],
        }
        result = optimizer.build_viral_prompt_context(data)
        # 0.4 < 0.5, so no HIGH VIRAL POTENTIAL
        assert "HIGH VIRAL POTENTIAL" not in result


# ── ensure_trending_hashtags ─────────────────────────────────

class TestEnsureTrendingHashtags:
    def test_injects_missing_hashtags(self, optimizer):
        script_data = {"hashtags": ["#Shorts", "#Facts"]}
        trending = ["#AIRevolution", "#TechTrends2026", "#FutureTech"]

        result = optimizer.ensure_trending_hashtags(script_data, trending)
        assert "#AIRevolution" in result["hashtags"]
        assert "#TechTrends2026" in result["hashtags"]
        assert "#FutureTech" in result["hashtags"]

    def test_does_not_duplicate_existing(self, optimizer):
        script_data = {"hashtags": ["#Shorts", "#AIRevolution"]}
        trending = ["#AIRevolution", "#TechTrends2026"]

        result = optimizer.ensure_trending_hashtags(script_data, trending)
        # #AIRevolution should appear only once
        count = sum(1 for h in result["hashtags"] if h.lower() == "#airevolution")
        assert count == 1

    def test_respects_max_inject(self, optimizer):
        script_data = {"hashtags": ["#Shorts"]}
        trending = ["#A", "#B", "#C", "#D", "#E"]

        result = optimizer.ensure_trending_hashtags(script_data, trending, max_inject=2)
        # Only 2 should be injected (+ 1 existing = 3 total)
        assert len(result["hashtags"]) == 3

    def test_caps_at_8_total(self, optimizer):
        script_data = {"hashtags": ["#1", "#2", "#3", "#4", "#5", "#6"]}
        trending = ["#A", "#B", "#C"]

        result = optimizer.ensure_trending_hashtags(script_data, trending)
        assert len(result["hashtags"]) <= 8

    def test_empty_trending_returns_unchanged(self, optimizer):
        script_data = {"hashtags": ["#Shorts", "#Facts"]}
        result = optimizer.ensure_trending_hashtags(script_data, [])
        assert result["hashtags"] == ["#Shorts", "#Facts"]

    def test_no_existing_hashtags(self, optimizer):
        script_data = {"hashtags": []}
        trending = ["#AI", "#Tech"]

        result = optimizer.ensure_trending_hashtags(script_data, trending)
        assert "#AI" in result["hashtags"]
        assert "#Tech" in result["hashtags"]

    def test_case_insensitive_dedup(self, optimizer):
        script_data = {"hashtags": ["#shorts"]}
        trending = ["#Shorts"]

        result = optimizer.ensure_trending_hashtags(script_data, trending)
        assert len(result["hashtags"]) == 1  # Not duplicated


# ── reorder_hashtags_for_youtube ─────────────────────────────

class TestReorderHashtagsForYoutube:
    def test_shorts_always_last(self, optimizer):
        tags = ["#Shorts", "#Science", "#Facts"]
        result = optimizer.reorder_hashtags_for_youtube(tags)
        assert result[-1] == "#Shorts"

    def test_viral_before_shorts(self, optimizer):
        tags = ["#Facts", "#Shorts", "#Viral", "#Science"]
        result = optimizer.reorder_hashtags_for_youtube(tags)
        assert result[-1] == "#Shorts"
        # #Viral should be second to last
        assert "#Viral" in result[-3:-1] or result[-2] == "#Viral"

    def test_trending_moves_to_end(self, optimizer):
        tags = ["#Trending", "#Science", "#Facts"]
        result = optimizer.reorder_hashtags_for_youtube(tags)
        # #Trending should be at end (no #Shorts)
        assert result[-1] == "#Trending"

    def test_empty_list(self, optimizer):
        assert optimizer.reorder_hashtags_for_youtube([]) == []

    def test_no_special_tags(self, optimizer):
        tags = ["#Science", "#Facts", "#Space"]
        result = optimizer.reorder_hashtags_for_youtube(tags)
        assert result == ["#Science", "#Facts", "#Space"]

    def test_multiple_viral_indicators(self, optimizer):
        tags = ["#Science", "#Viral", "#FYP", "#Trending", "#Shorts"]
        result = optimizer.reorder_hashtags_for_youtube(tags)
        assert result[-1] == "#Shorts"
        assert result[0] == "#Science"


# ── _get_youtube_autocomplete ────────────────────────────────

class TestGetYoutubeAutocomplete:
    @pytest.mark.asyncio
    async def test_successful_autocomplete(self, optimizer):
        mock_response = MagicMock()
        mock_response.text = 'window.google.ac.h([["ai agents",[["ai agents tutorial",0],["ai agents explained",0],["ai agents 2026",0]],{}]])'
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200

        # The response format for YouTube is JSONP-like: starts with data
        # Simplify by returning proper JSON array format
        mock_response.text = '["ai agents",[["ai agents tutorial"],["ai agents explained"],["ai agents 2026"]]]'

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await optimizer._get_youtube_autocomplete("ai agents")

        assert "ai agents tutorial" in result
        assert len(result) <= 8

    @pytest.mark.asyncio
    async def test_autocomplete_failure(self, optimizer):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client_cls.return_value = mock_client

            with pytest.raises(httpx.TimeoutException):
                await optimizer._get_youtube_autocomplete("test")

    @pytest.mark.asyncio
    async def test_autocomplete_empty_response(self, optimizer):
        mock_response = MagicMock()
        mock_response.text = "no json here"
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await optimizer._get_youtube_autocomplete("test")
            assert result == []


# ── _get_signals_from_trends ─────────────────────────────────

class TestGetSignalsFromTrends:
    @pytest.mark.asyncio
    async def test_signals_with_matching_trends(self, optimizer):
        now = datetime.now(timezone.utc)
        mock_trend = MagicMock()
        mock_trend.topic = "AI Agents 2026"
        mock_trend.related_queries = json.dumps(["ai automation", "chatgpt agents"])
        mock_trend.velocity = "rising"
        mock_trend.viral_potential = 0.7
        mock_trend.quality_score = 85.0

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_trend]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.database.async_session_factory", return_value=mock_session):
            result = await optimizer._get_signals_from_trends("AI Agents", "technology")

        assert len(result["keywords"]) > 0
        assert result["velocity"] == "rising"

    @pytest.mark.asyncio
    async def test_signals_no_trends(self, optimizer):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.database.async_session_factory", return_value=mock_session):
            result = await optimizer._get_signals_from_trends("unknown topic", None)

        assert result["hashtags"] == []
        assert result["keywords"] == []
        assert result["velocity"] == "rising"

    @pytest.mark.asyncio
    async def test_signals_with_json_string_related_queries(self, optimizer):
        mock_trend = MagicMock()
        mock_trend.topic = "Space exploration"
        mock_trend.related_queries = '["mars mission", "nasa update"]'
        mock_trend.velocity = "peaked"
        mock_trend.viral_potential = 0.5

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_trend]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.database.async_session_factory", return_value=mock_session):
            result = await optimizer._get_signals_from_trends("space exploration", "space")

        assert "mars mission" in result["keywords"]


# ── get_trending_context (integration) ───────────────────────

class TestGetTrendingContext:
    @pytest.mark.asyncio
    async def test_full_context_all_sources(self, optimizer):
        with patch.object(
            optimizer, "_get_signals_from_trends", new_callable=AsyncMock
        ) as mock_db, patch.object(
            optimizer, "_get_youtube_autocomplete", new_callable=AsyncMock
        ) as mock_yt:
            mock_db.return_value = {
                "hashtags": ["#AI", "#Tech"],
                "keywords": ["ai agents"],
                "velocity": "rising",
                "viral_potential": 0.6,
            }
            mock_yt.return_value = ["ai agents tutorial", "ai agents 2026"]

            result = await optimizer.get_trending_context("AI agents", "technology")

        assert "#AI" in result["trending_hashtags"]
        assert "ai agents" in result["trending_keywords"]
        assert "ai agents tutorial" in result["trending_keywords"]
        assert result["velocity"] == "rising"
        assert result["viral_potential"] == 0.6
        assert len(result["niche_hashtags"]) > 0

    @pytest.mark.asyncio
    async def test_graceful_db_failure(self, optimizer):
        with patch.object(
            optimizer, "_get_signals_from_trends", new_callable=AsyncMock,
            side_effect=Exception("DB connection failed"),
        ), patch.object(
            optimizer, "_get_youtube_autocomplete", new_callable=AsyncMock,
            return_value=["test suggestion"],
        ):
            result = await optimizer.get_trending_context("test topic", None)

        # Should still return results from YouTube autocomplete
        assert "test suggestion" in result["trending_keywords"]
        assert result["velocity"] == "rising"  # default

    @pytest.mark.asyncio
    async def test_graceful_autocomplete_failure(self, optimizer):
        with patch.object(
            optimizer, "_get_signals_from_trends", new_callable=AsyncMock,
            return_value={
                "hashtags": ["#Test"], "keywords": [],
                "velocity": "rising", "viral_potential": 0.0,
            },
        ), patch.object(
            optimizer, "_get_youtube_autocomplete", new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("timeout"),
        ):
            result = await optimizer.get_trending_context("test topic", None)

        assert "#Test" in result["trending_hashtags"]

    @pytest.mark.asyncio
    async def test_deduplicates_keywords(self, optimizer):
        with patch.object(
            optimizer, "_get_signals_from_trends", new_callable=AsyncMock,
            return_value={
                "hashtags": [], "keywords": ["ai agents"],
                "velocity": "rising", "viral_potential": 0.0,
            },
        ), patch.object(
            optimizer, "_get_youtube_autocomplete", new_callable=AsyncMock,
            return_value=["ai agents", "ai agents tutorial"],
        ):
            result = await optimizer.get_trending_context("ai agents", None)

        # "ai agents" should appear only once
        lower_kw = [k.lower() for k in result["trending_keywords"]]
        assert lower_kw.count("ai agents") == 1

    @pytest.mark.asyncio
    async def test_limits_results(self, optimizer):
        with patch.object(
            optimizer, "_get_signals_from_trends", new_callable=AsyncMock,
            return_value={
                "hashtags": [f"#Tag{i}" for i in range(20)],
                "keywords": [f"keyword{i}" for i in range(20)],
                "velocity": "rising", "viral_potential": 0.0,
            },
        ), patch.object(
            optimizer, "_get_youtube_autocomplete", new_callable=AsyncMock,
            return_value=[],
        ):
            result = await optimizer.get_trending_context("test", None)

        assert len(result["trending_hashtags"]) <= 10
        assert len(result["trending_keywords"]) <= 10
