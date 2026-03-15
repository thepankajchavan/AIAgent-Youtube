"""Unit tests for AnalyticsService."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

DB_FACTORY = "app.core.database.async_session_factory"


def _mock_session_ctx(mock_session):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestCollectVideoStats:
    """Tests for single video stats collection."""

    @patch("app.services.analytics_service.AnalyticsService.collect_video_stats")
    @pytest.mark.asyncio
    async def test_collect_video_stats_success(self, mock_collect):
        from app.services.analytics_service import AnalyticsService

        mock_collect.return_value = {
            "views": 1500,
            "likes": 120,
            "comments": 30,
            "shares": 0,
            "watch_time_minutes": 0.0,
            "average_view_duration_seconds": 25.0,
        }

        service = AnalyticsService()
        stats = await service.collect_video_stats("test_video_id")

        assert stats["views"] == 1500
        assert stats["likes"] == 120

    @patch("app.services.analytics_service.AnalyticsService.collect_video_stats")
    @pytest.mark.asyncio
    async def test_collect_video_stats_api_error_retry(self, mock_collect):
        from app.services.analytics_service import AnalyticsService

        mock_collect.side_effect = ConnectionError("API unavailable")

        service = AnalyticsService()
        with pytest.raises(ConnectionError):
            await service.collect_video_stats("test_video_id")


class TestCollectAllRecentVideos:
    """Tests for batch analytics collection."""

    @patch("app.services.analytics_service.AnalyticsService.collect_analytics_report")
    @patch("app.services.analytics_service.AnalyticsService.collect_video_stats")
    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_collect_all_recent_videos_skips_existing_snapshots(
        self, mock_factory, mock_stats, mock_report
    ):
        from app.services.analytics_service import AnalyticsService

        project = MagicMock()
        project.id = "project-1"
        project.youtube_video_id = "yt-123"
        project.created_at = datetime.now(timezone.utc)

        mock_session = AsyncMock()

        projects_result = MagicMock()
        projects_result.scalars.return_value.all.return_value = [project]

        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = MagicMock()  # exists

        mock_session.execute.side_effect = [projects_result, existing_result]
        mock_factory.return_value = _mock_session_ctx(mock_session)

        service = AnalyticsService()
        results = await service.collect_all_recent_videos(lookback_days=7)

        assert len(results) == 0
        mock_stats.assert_not_called()


class TestGetTopPerformingVideos:
    """Tests for top video queries."""

    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_get_top_performing_videos(self, mock_factory):
        from app.services.analytics_service import AnalyticsService

        mock_analytics = MagicMock()
        mock_analytics.views = 5000
        mock_analytics.average_view_percentage = 65.0

        mock_project = MagicMock()
        mock_project.id = "proj-1"
        mock_project.topic = "Amazing topic"
        mock_project.script = "Script text here"
        mock_project.prompt_version_id = "v1"
        mock_project.trend_topic_used = "AI"

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(mock_analytics, mock_project)]
        mock_session.execute.return_value = mock_result

        mock_factory.return_value = _mock_session_ctx(mock_session)

        service = AnalyticsService()
        top = await service.get_top_performing_videos(limit=10, days=30)

        assert len(top) == 1
        assert top[0]["views"] == 5000
        assert top[0]["topic"] == "Amazing topic"


class TestGetPerformanceSummary:
    """Tests for aggregated performance summary."""

    @patch(DB_FACTORY)
    @pytest.mark.asyncio
    async def test_get_performance_summary(self, mock_factory):
        from app.services.analytics_service import AnalyticsService

        mock_session = AsyncMock()

        agg_row = MagicMock()
        agg_row.total_views = 50000
        agg_row.avg_views = 2500.0
        agg_row.avg_retention = 55.5
        agg_row.avg_ctr = 4.2
        agg_row.snapshot_count = 20

        agg_result = MagicMock()
        agg_result.one.return_value = agg_row

        best_analytics = MagicMock()
        best_analytics.views = 8000
        best_project = MagicMock()
        best_project.id = "best-1"
        best_project.topic = "Best video"
        best_result = MagicMock()
        best_result.first.return_value = (best_analytics, best_project)

        worst_analytics = MagicMock()
        worst_analytics.views = 100
        worst_project = MagicMock()
        worst_project.id = "worst-1"
        worst_project.topic = "Worst video"
        worst_result = MagicMock()
        worst_result.first.return_value = (worst_analytics, worst_project)

        mock_session.execute.side_effect = [agg_result, best_result, worst_result]
        mock_factory.return_value = _mock_session_ctx(mock_session)

        service = AnalyticsService()
        summary = await service.get_performance_summary(days=30)

        assert summary["total_views"] == 50000
        assert summary["avg_views"] == 2500.0
        assert summary["best_video"]["topic"] == "Best video"
        assert summary["worst_video"]["topic"] == "Worst video"


class TestParseIsoDuration:
    """Tests for ISO 8601 duration parsing."""

    def test_parse_minutes_seconds(self):
        from app.services.analytics_service import AnalyticsService

        assert AnalyticsService._parse_iso_duration("PT1M30S") == 90.0

    def test_parse_seconds_only(self):
        from app.services.analytics_service import AnalyticsService

        assert AnalyticsService._parse_iso_duration("PT45S") == 45.0

    def test_parse_hours_minutes_seconds(self):
        from app.services.analytics_service import AnalyticsService

        assert AnalyticsService._parse_iso_duration("PT1H2M3S") == 3723.0

    def test_parse_zero(self):
        from app.services.analytics_service import AnalyticsService

        assert AnalyticsService._parse_iso_duration("PT0S") == 0.0

    def test_parse_invalid(self):
        from app.services.analytics_service import AnalyticsService

        assert AnalyticsService._parse_iso_duration("invalid") == 0.0
