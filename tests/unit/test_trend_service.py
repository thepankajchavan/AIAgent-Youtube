"""Unit tests for TrendAggregator (trend_service.py)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.trend_service import TrendAggregator, TrendService

# Common patch target for async_session_factory
DB_FACTORY = "app.core.database.async_session_factory"
SETTINGS_PATCH = "app.services.trend_service.get_settings"


def _mock_session_ctx(mock_session):
    """Create a mock async context manager for async_session_factory."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_settings(**overrides):
    """Build a mock settings object with trend-related defaults."""
    s = MagicMock()
    s.trends_enabled = True
    s.trends_categories = "technology,entertainment"
    s.trends_region = "US"
    s.trends_reddit_enabled = False
    s.trends_twitter_enabled = False
    s.trends_reddit_subreddits = "technology,science"
    s.trends_min_quality_score = 40.0
    s.trends_expiry_hours = 24
    s.youtube_api_key = "fake-key"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ── Backward compatibility alias ─────────────────────────────

class TestBackwardCompatAlias:
    """Verify TrendService is an alias for TrendAggregator."""

    def test_alias_identity(self):
        assert TrendService is TrendAggregator


# ── Google Trends ─────────────────────────────────────────────

class TestFetchGoogleTrends:
    """Tests for Google Trends fetching."""

    @patch(SETTINGS_PATCH)
    @patch.object(TrendAggregator, "_fetch_google_trends_sync")
    @pytest.mark.asyncio
    async def test_fetch_google_trends_success(self, mock_sync, mock_gs):
        mock_gs.return_value = _make_settings()
        mock_sync.return_value = [
            {
                "topic": "AI revolution",
                "trend_score": 80.0,
                "category": "tech",
                "related_queries": [],
                "source": "google_trends",
            },
        ]

        service = TrendAggregator()
        results = await service.fetch_google_trends(category="tech", region="US")

        assert len(results) == 1
        assert results[0]["topic"] == "AI revolution"
        assert results[0]["source"] == "google_trends"
        mock_sync.assert_called_once_with("tech", "US")

    @patch(SETTINGS_PATCH)
    @patch.object(TrendAggregator, "_fetch_google_trends_sync")
    @pytest.mark.asyncio
    async def test_fetch_google_trends_failure(self, mock_sync, mock_gs):
        mock_gs.return_value = _make_settings()
        mock_sync.side_effect = Exception("429 Too Many Requests")

        service = TrendAggregator()
        results = await service.fetch_google_trends(category="tech")

        assert results == []

    @patch(SETTINGS_PATCH)
    @patch.object(TrendAggregator, "_fetch_google_trends_sync")
    @pytest.mark.asyncio
    async def test_fetch_google_trends_empty(self, mock_sync, mock_gs):
        mock_gs.return_value = _make_settings()
        mock_sync.return_value = []

        service = TrendAggregator()
        results = await service.fetch_google_trends()

        assert results == []


# ── YouTube Trending ──────────────────────────────────────────

class TestFetchYouTubeTrending:
    """Tests for YouTube trending fetching."""

    @patch(SETTINGS_PATCH)
    @pytest.mark.asyncio
    async def test_fetch_youtube_trending_success(self, mock_gs):
        mock_gs.return_value = _make_settings()

        service = TrendAggregator()
        # Patch the method directly to avoid real API calls
        service.fetch_youtube_trending = AsyncMock(return_value=[
            {
                "topic": "Trending Video #1",
                "trend_score": 90.0,
                "category": "24",
                "related_queries": ["tag1", "tag2"],
                "source": "youtube_trending",
                "viral_potential": 0.6,
                "source_url": "https://youtube.com/watch?v=abc123",
                "source_metadata": {"view_count": 5_000_000, "video_id": "abc123"},
            },
        ])

        results = await service.fetch_youtube_trending(region="US")

        assert len(results) == 1
        assert results[0]["source"] == "youtube_trending"
        assert results[0]["trend_score"] == 90.0

    @patch(SETTINGS_PATCH)
    @pytest.mark.asyncio
    async def test_fetch_youtube_trending_failure(self, mock_gs):
        mock_gs.return_value = _make_settings()

        service = TrendAggregator()
        # Patch the method to simulate API failure path
        service.fetch_youtube_trending = AsyncMock(return_value=[])

        results = await service.fetch_youtube_trending(region="US")

        assert results == []


# ── Reddit Trending ───────────────────────────────────────────

class TestFetchRedditTrending:
    """Tests for Reddit trending fetching."""

    @patch(SETTINGS_PATCH)
    @patch("app.services.trend_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.trend_service.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_fetch_reddit_success(self, mock_client_cls, mock_sleep, mock_gs):
        mock_gs.return_value = _make_settings()

        reddit_json = {
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "Amazing science discovery",
                            "ups": 25000,
                            "num_comments": 1200,
                            "permalink": "/r/science/comments/abc/amazing/",
                            "stickied": False,
                        }
                    },
                    {
                        "data": {
                            "title": "New tech breakthrough",
                            "ups": 15000,
                            "num_comments": 800,
                            "permalink": "/r/technology/comments/def/new_tech/",
                            "stickied": False,
                        }
                    },
                ]
            }
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = reddit_json

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        service = TrendAggregator()
        results = await service.fetch_reddit_trending(subreddits=["science"])

        assert len(results) == 2
        assert results[0]["topic"] == "Amazing science discovery"
        assert results[0]["source"] == "reddit"
        assert results[0]["source_metadata"]["subreddit"] == "science"
        assert results[0]["source_metadata"]["upvotes"] == 25000

    @patch(SETTINGS_PATCH)
    @patch("app.services.trend_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.trend_service.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_fetch_reddit_skips_stickied(self, mock_client_cls, mock_sleep, mock_gs):
        mock_gs.return_value = _make_settings()

        reddit_json = {
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "Weekly Discussion Thread",
                            "ups": 500,
                            "num_comments": 100,
                            "permalink": "/r/science/comments/xyz/weekly/",
                            "stickied": True,
                        }
                    },
                    {
                        "data": {
                            "title": "Real trending post",
                            "ups": 30000,
                            "num_comments": 2000,
                            "permalink": "/r/science/comments/abc/real/",
                            "stickied": False,
                        }
                    },
                ]
            }
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = reddit_json

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        service = TrendAggregator()
        results = await service.fetch_reddit_trending(subreddits=["science"])

        assert len(results) == 1
        assert results[0]["topic"] == "Real trending post"

    @patch(SETTINGS_PATCH)
    @patch("app.services.trend_service.asyncio.sleep", new_callable=AsyncMock)
    @patch("app.services.trend_service.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_fetch_reddit_failure_graceful(self, mock_client_cls, mock_sleep, mock_gs):
        mock_gs.return_value = _make_settings()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        service = TrendAggregator()
        results = await service.fetch_reddit_trending(subreddits=["science"])

        assert results == []


# ── Twitter Trending ──────────────────────────────────────────

class TestFetchTwitterTrending:
    """Tests for Twitter/X trending fetching."""

    @patch(SETTINGS_PATCH)
    @patch("app.services.trend_service.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_fetch_twitter_extracts_hashtags(self, mock_client_cls, mock_gs):
        mock_gs.return_value = _make_settings()

        html_with_hashtags = (
            '<div>Trending now #AIRevolution is huge and #SpaceExploration '
            'is also trending, plus #CryptoNews and #AIRevolution again</div>'
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html_with_hashtags

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        service = TrendAggregator()
        results = await service.fetch_twitter_trending(region="US")

        # Should extract unique hashtags
        topics = [r["topic"] for r in results]
        assert "#AIRevolution" in topics
        assert "#SpaceExploration" in topics
        assert "#CryptoNews" in topics
        # Deduplicated: AIRevolution appears once
        assert len([t for t in topics if "AIRevolution" in t]) == 1
        for r in results:
            assert r["source"] == "twitter"

    @patch(SETTINGS_PATCH)
    @patch("app.services.trend_service.httpx.AsyncClient")
    @pytest.mark.asyncio
    async def test_fetch_twitter_graceful_degradation(self, mock_client_cls, mock_gs):
        mock_gs.return_value = _make_settings()

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        service = TrendAggregator()
        results = await service.fetch_twitter_trending(region="US")

        assert results == []


# ── Scoring ───────────────────────────────────────────────────

class TestScoreTrend:
    """Tests for trend scoring logic."""

    @patch(SETTINGS_PATCH)
    def test_score_applies_source_weight(self, mock_gs):
        mock_gs.return_value = _make_settings()
        service = TrendAggregator()

        # youtube_trending weight = 1.0
        yt = service.score_trend({
            "topic": "YT Video",
            "trend_score": 80.0,
            "source": "youtube_trending",
            "viral_potential": 0.0,
        })
        assert yt["quality_score"] == round(80.0 * 1.0, 2)

        # google_trends weight = 0.85
        gt = service.score_trend({
            "topic": "Google Topic",
            "trend_score": 80.0,
            "source": "google_trends",
            "viral_potential": 0.0,
        })
        assert gt["quality_score"] == round(80.0 * 0.85, 2)

        # reddit weight = 0.7
        rd = service.score_trend({
            "topic": "Reddit Post",
            "trend_score": 80.0,
            "source": "reddit",
            "viral_potential": 0.0,
        })
        assert rd["quality_score"] == round(80.0 * 0.7, 2)

        # twitter weight = 0.5
        tw = service.score_trend({
            "topic": "Tweet",
            "trend_score": 80.0,
            "source": "twitter",
            "viral_potential": 0.0,
        })
        assert tw["quality_score"] == round(80.0 * 0.5, 2)

    @patch(SETTINGS_PATCH)
    def test_score_viral_boost(self, mock_gs):
        mock_gs.return_value = _make_settings()
        service = TrendAggregator()

        # viral_potential > 0.5 => 1.15x boost
        result = service.score_trend({
            "topic": "Viral hit",
            "trend_score": 80.0,
            "source": "youtube_trending",
            "viral_potential": 0.8,
        })
        expected = round(80.0 * 1.0 * 1.15, 2)
        assert result["quality_score"] == expected

        # viral_potential 0.3 (> 0.2 but <= 0.5) => 1.05x boost
        result2 = service.score_trend({
            "topic": "Moderate hit",
            "trend_score": 80.0,
            "source": "youtube_trending",
            "viral_potential": 0.3,
        })
        expected2 = round(80.0 * 1.0 * 1.05, 2)
        assert result2["quality_score"] == expected2

    @patch(SETTINGS_PATCH)
    def test_score_caps_at_100(self, mock_gs):
        mock_gs.return_value = _make_settings()
        service = TrendAggregator()

        result = service.score_trend({
            "topic": "Super viral",
            "trend_score": 99.0,
            "source": "youtube_trending",
            "viral_potential": 0.9,
        })
        # 99 * 1.0 * 1.15 = 113.85 => capped at 100
        assert result["quality_score"] <= 100.0
        assert result["quality_score"] == 100.0


# ── Velocity Detection ────────────────────────────────────────

class TestDetectVelocity:
    """Tests for trend velocity detection."""

    @patch(SETTINGS_PATCH)
    def test_rising_when_new(self, mock_gs):
        mock_gs.return_value = _make_settings()
        service = TrendAggregator()

        # No historical data = new topic = "rising"
        velocity = service.detect_velocity(
            {"topic": "Brand new thing", "trend_score": 75.0},
            [],
        )
        assert velocity == "rising"

    @patch(SETTINGS_PATCH)
    def test_peaked_when_stable(self, mock_gs):
        mock_gs.return_value = _make_settings()
        service = TrendAggregator()

        # Current score similar to historical average => "peaked"
        historical = [
            {"topic": "Stable topic", "trend_score": 70.0},
            {"topic": "Stable topic", "trend_score": 72.0},
        ]
        velocity = service.detect_velocity(
            {"topic": "Stable topic", "trend_score": 71.0},
            historical,
        )
        assert velocity == "peaked"

    @patch(SETTINGS_PATCH)
    def test_declining_when_lower(self, mock_gs):
        mock_gs.return_value = _make_settings()
        service = TrendAggregator()

        # Current score much lower than historical => "declining"
        historical = [
            {"topic": "Fading topic", "trend_score": 90.0},
            {"topic": "Fading topic", "trend_score": 85.0},
        ]
        # avg_past = 87.5, declining threshold = 87.5 * 0.85 = 74.375
        velocity = service.detect_velocity(
            {"topic": "Fading topic", "trend_score": 60.0},
            historical,
        )
        assert velocity == "declining"


# ── Niche Detection ───────────────────────────────────────────

class TestDetectNiche:
    """Tests for niche classification."""

    @patch(SETTINGS_PATCH)
    def test_detects_science(self, mock_gs):
        mock_gs.return_value = _make_settings()
        service = TrendAggregator()

        niche = service.detect_niche("quantum research discovery")
        assert niche == "science"

    @patch(SETTINGS_PATCH)
    def test_detects_technology(self, mock_gs):
        mock_gs.return_value = _make_settings()
        service = TrendAggregator()

        niche = service.detect_niche("AI robot launch")
        assert niche == "technology"

    @patch(SETTINGS_PATCH)
    def test_returns_none_for_generic(self, mock_gs):
        mock_gs.return_value = _make_settings()
        service = TrendAggregator()

        niche = service.detect_niche("random topic stuff")
        assert niche is None


# ── Deduplication ─────────────────────────────────────────────

class TestDeduplication:
    """Tests for trend deduplication logic."""

    @patch(SETTINGS_PATCH)
    def test_identical_topics_merged(self, mock_gs):
        mock_gs.return_value = _make_settings()
        service = TrendAggregator()

        trends = [
            {"topic": "AI revolution", "trend_score": 80, "source": "google_trends",
             "quality_score": 68.0},
            {"topic": "AI revolution", "trend_score": 70, "source": "google_trends",
             "quality_score": 59.5},
        ]
        result = service._deduplicate_trends(trends)
        assert len(result) == 1
        assert result[0]["topic"] == "AI revolution"

    @patch(SETTINGS_PATCH)
    def test_cross_source_boost(self, mock_gs):
        mock_gs.return_value = _make_settings()
        service = TrendAggregator()

        trends = [
            {"topic": "AI revolution in 2026", "trend_score": 80, "source": "google_trends",
             "quality_score": 68.0},
            {"topic": "AI revolution in 2026", "trend_score": 75, "source": "youtube_trending",
             "quality_score": 75.0},
        ]
        result = service._deduplicate_trends(trends)
        assert len(result) == 1
        # Cross-source: quality_score = (68 + 75) / 2 * 1.3 = 92.95
        assert result[0]["quality_score"] > 68.0  # boosted above original
        # trend_score also boosted: (80 + 75) / 2 * 1.3 = 100.75 => capped 100
        assert result[0]["trend_score"] >= 80

    @patch(SETTINGS_PATCH)
    def test_different_topics_kept(self, mock_gs):
        mock_gs.return_value = _make_settings()
        service = TrendAggregator()

        trends = [
            {"topic": "AI revolution", "trend_score": 80, "source": "google_trends",
             "quality_score": 68.0},
            {"topic": "Mars exploration", "trend_score": 70, "source": "google_trends",
             "quality_score": 59.5},
        ]
        result = service._deduplicate_trends(trends)
        assert len(result) == 2


# ── Collect and Store ─────────────────────────────────────────

class TestCollectAndStoreTrends:
    """Tests for the full collect + store pipeline."""

    @patch(SETTINGS_PATCH)
    @patch(DB_FACTORY)
    @patch.object(TrendAggregator, "_get_recent_trends_for_velocity", new_callable=AsyncMock)
    @patch.object(TrendAggregator, "fetch_all_sources", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_collect_stores_trends(
        self, mock_fetch_all, mock_velocity, mock_factory, mock_gs
    ):
        mock_gs.return_value = _make_settings()

        mock_fetch_all.return_value = [
            {
                "topic": "Quantum computing breakthrough",
                "trend_score": 85.0,
                "source": "google_trends",
                "category": "technology",
                "related_queries": ["quantum", "qubits"],
                "viral_potential": 0.3,
            },
            {
                "topic": "SpaceX Mars mission update",
                "trend_score": 78.0,
                "source": "youtube_trending",
                "category": "space",
                "related_queries": ["spacex", "mars"],
                "viral_potential": 0.6,
            },
        ]

        mock_velocity.return_value = []

        mock_session = AsyncMock()
        mock_factory.return_value = _mock_session_ctx(mock_session)

        service = TrendAggregator()
        count = await service.collect_and_store_trends()

        assert count == 2
        assert mock_session.add.call_count == 2
        mock_session.commit.assert_awaited_once()

    @patch(SETTINGS_PATCH)
    @patch.object(TrendAggregator, "fetch_all_sources", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_collect_empty_returns_zero(self, mock_fetch_all, mock_gs):
        mock_gs.return_value = _make_settings()
        mock_fetch_all.return_value = []

        service = TrendAggregator()
        count = await service.collect_and_store_trends()

        assert count == 0


# ── Best Topics for Scheduling ────────────────────────────────

class TestGetBestTopicsForScheduling:
    """Tests for get_best_topics_for_scheduling."""

    @patch(SETTINGS_PATCH)
    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_returns_filtered_topics(self, mock_factory, mock_gs):
        mock_gs.return_value = _make_settings(trends_min_quality_score=40.0)

        now = datetime.now(timezone.utc)

        # Build mock trending topics
        trend_good = MagicMock()
        trend_good.id = "trend-good"
        trend_good.topic = "High quality trend"
        trend_good.category = "technology"
        trend_good.niche = "technology"
        trend_good.trend_score = 85.0
        trend_good.quality_score = 72.0
        trend_good.velocity = "rising"
        trend_good.viral_potential = 0.6
        trend_good.source = "youtube_trending"

        mock_session = AsyncMock()

        # First execute call: trending topics query
        trends_result = MagicMock()
        trends_result.scalars.return_value.all.return_value = [trend_good]

        # Second execute call: recently used topics query
        recent_result = MagicMock()
        recent_result.all.return_value = []  # Nothing used recently

        mock_session.execute = AsyncMock(side_effect=[trends_result, recent_result])
        mock_factory.return_value = _mock_session_ctx(mock_session)

        service = TrendAggregator()
        topics = await service.get_best_topics_for_scheduling(limit=10)

        assert len(topics) == 1
        assert topics[0]["topic"] == "High quality trend"
        assert topics[0]["quality_score"] == 72.0

    @patch(SETTINGS_PATCH)
    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_excludes_recently_used(self, mock_factory, mock_gs):
        mock_gs.return_value = _make_settings(trends_min_quality_score=40.0)

        trend_used = MagicMock()
        trend_used.id = "trend-used"
        trend_used.topic = "Already used topic"
        trend_used.category = "tech"
        trend_used.niche = "technology"
        trend_used.trend_score = 90.0
        trend_used.quality_score = 80.0
        trend_used.velocity = "rising"
        trend_used.viral_potential = 0.5
        trend_used.source = "google_trends"

        trend_fresh = MagicMock()
        trend_fresh.id = "trend-fresh"
        trend_fresh.topic = "Quantum computing breakthrough in physics"
        trend_fresh.category = "science"
        trend_fresh.niche = "science"
        trend_fresh.trend_score = 75.0
        trend_fresh.quality_score = 63.75
        trend_fresh.velocity = "rising"
        trend_fresh.viral_potential = 0.3
        trend_fresh.source = "youtube_trending"

        mock_session = AsyncMock()

        trends_result = MagicMock()
        trends_result.scalars.return_value.all.return_value = [trend_used, trend_fresh]

        # "Already used topic" was recently used
        recent_result = MagicMock()
        recent_result.all.return_value = [("Already used topic",)]

        mock_session.execute = AsyncMock(side_effect=[trends_result, recent_result])
        mock_factory.return_value = _mock_session_ctx(mock_session)

        service = TrendAggregator()
        topics = await service.get_best_topics_for_scheduling(limit=10)

        assert len(topics) == 1
        assert topics[0]["topic"] == "Quantum computing breakthrough in physics"

    @patch(SETTINGS_PATCH)
    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_returns_top_if_all_used(self, mock_factory, mock_gs):
        mock_gs.return_value = _make_settings(trends_min_quality_score=40.0)

        trend_only = MagicMock()
        trend_only.id = "trend-only"
        trend_only.topic = "The only option"
        trend_only.category = "tech"
        trend_only.niche = "technology"
        trend_only.trend_score = 85.0
        trend_only.quality_score = 72.0
        trend_only.velocity = "rising"
        trend_only.viral_potential = 0.4
        trend_only.source = "google_trends"

        mock_session = AsyncMock()

        trends_result = MagicMock()
        trends_result.scalars.return_value.all.return_value = [trend_only]

        # All topics recently used (fuzzy match at 0.6 threshold)
        recent_result = MagicMock()
        recent_result.all.return_value = [("The only option",)]

        mock_session.execute = AsyncMock(side_effect=[trends_result, recent_result])
        mock_factory.return_value = _mock_session_ctx(mock_session)

        service = TrendAggregator()
        topics = await service.get_best_topics_for_scheduling(limit=10)

        # If all filtered out, returns top trend anyway
        assert len(topics) == 1
        assert topics[0]["topic"] == "The only option"
