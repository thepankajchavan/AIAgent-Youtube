"""Unit tests for SchedulingBrain (auto-schedule service)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SETTINGS_PATH = "app.services.auto_schedule_service.get_settings"
SYNC_DB_PATH = "app.workers.db.get_sync_db"
ASYNCIO_RUN_PATH = "asyncio.run"
DB_FACTORY = "app.core.database.async_session_factory"
TREND_AGGREGATOR_PATH = "app.services.trend_service.TrendAggregator"
IS_ENABLED_SYNC_PATH = (
    "app.services.auto_schedule_service.SchedulingBrain.is_enabled_sync"
)


def _make_settings(**overrides) -> MagicMock:
    """Build a mock settings object with auto-schedule defaults."""
    defaults = {
        "auto_schedule_enabled": True,
        "auto_schedule_max_daily": 3,
        "auto_schedule_cooldown_hours": 4,
        "auto_schedule_niche": "science",
        "auto_schedule_visual_strategy": "stock_only",
        "auto_schedule_skip_upload": False,
        "auto_schedule_diversity_window": 3,
        "auto_schedule_performance_feedback": True,
        "auto_schedule_quality_threshold": 40.0,
        "auto_schedule_admin_chat_id": 0,
        "redis_url": "redis://localhost:6379/0",
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


@contextmanager
def _fake_sync_db(session):
    """Mimic get_sync_db() context manager returning a mock session."""
    yield session


def _make_db_mock(execute_results):
    """Create a mock for get_sync_db that returns fresh context managers.

    ``execute_results`` can be:
    - A single MagicMock result -> same session for all calls.
    - A list of MagicMock results -> session.execute uses side_effect.

    Returns (mock_db_func, session) where mock_db_func is suitable for
    assigning to ``mock_db.side_effect`` or ``mock_db.return_value``.
    """
    session = MagicMock()
    if isinstance(execute_results, list):
        session.execute.side_effect = execute_results
    else:
        session.execute.return_value = execute_results

    def _fresh_ctx():
        return _fake_sync_db(session)

    return _fresh_ctx, session


def _mock_session_ctx(mock_session):
    """Create an async context manager mock for async_session_factory."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ===========================================================================
# TestShouldAutoSchedule
# ===========================================================================


class TestShouldAutoSchedule:
    """Tests for SchedulingBrain.should_schedule_now() (and backward-compat alias)."""

    @patch(IS_ENABLED_SYNC_PATH, return_value=False)
    @patch(SETTINGS_PATH)
    def test_returns_false_when_disabled(self, mock_settings, _mock_enabled):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_enabled=False)

        service = SchedulingBrain()
        assert service.should_schedule_now() is False

    @patch(SYNC_DB_PATH)
    @patch(IS_ENABLED_SYNC_PATH, return_value=True)
    @patch(SETTINGS_PATH)
    def test_returns_false_when_daily_limit_reached(
        self, mock_settings, _mock_enabled, mock_db
    ):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_max_daily=2)

        mock_result = MagicMock()
        mock_result.scalar.return_value = 2

        factory, _ = _make_db_mock(mock_result)
        mock_db.side_effect = lambda: factory()

        service = SchedulingBrain()
        assert service.should_schedule_now() is False

    @patch(SYNC_DB_PATH)
    @patch(IS_ENABLED_SYNC_PATH, return_value=True)
    @patch(SETTINGS_PATH)
    def test_returns_false_when_daily_limit_exceeded(
        self, mock_settings, _mock_enabled, mock_db
    ):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_max_daily=3)

        mock_result = MagicMock()
        mock_result.scalar.return_value = 5

        factory, _ = _make_db_mock(mock_result)
        mock_db.side_effect = lambda: factory()

        service = SchedulingBrain()
        assert service.should_schedule_now() is False

    @patch(SYNC_DB_PATH)
    @patch(IS_ENABLED_SYNC_PATH, return_value=True)
    @patch(SETTINGS_PATH)
    def test_returns_false_when_cooldown_not_elapsed(
        self, mock_settings, _mock_enabled, mock_db
    ):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(
            auto_schedule_cooldown_hours=4, auto_schedule_max_daily=10
        )

        recent_time = datetime.now(timezone.utc) - timedelta(hours=1)

        mock_result_count = MagicMock()
        mock_result_count.scalar.return_value = 0

        mock_result_cooldown = MagicMock()
        mock_result_cooldown.scalar_one_or_none.return_value = recent_time

        factory, _ = _make_db_mock([mock_result_count, mock_result_cooldown])
        mock_db.side_effect = lambda: factory()

        service = SchedulingBrain()
        assert service.should_schedule_now() is False

    @patch(SYNC_DB_PATH)
    @patch(IS_ENABLED_SYNC_PATH, return_value=True)
    @patch(SETTINGS_PATH)
    def test_returns_true_when_all_checks_pass(
        self, mock_settings, _mock_enabled, mock_db
    ):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(
            auto_schedule_cooldown_hours=4, auto_schedule_max_daily=5
        )

        old_time = datetime.now(timezone.utc) - timedelta(hours=10)

        mock_result_count = MagicMock()
        mock_result_count.scalar.return_value = 2

        mock_result_cooldown = MagicMock()
        mock_result_cooldown.scalar_one_or_none.return_value = old_time

        factory, _ = _make_db_mock([mock_result_count, mock_result_cooldown])
        mock_db.side_effect = lambda: factory()

        service = SchedulingBrain()
        assert service.should_schedule_now() is True

    @patch(SYNC_DB_PATH)
    @patch(IS_ENABLED_SYNC_PATH, return_value=True)
    @patch(SETTINGS_PATH)
    def test_returns_true_when_zero_videos_today(
        self, mock_settings, _mock_enabled, mock_db
    ):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_max_daily=3)

        mock_result_count = MagicMock()
        mock_result_count.scalar.return_value = 0

        mock_result_cooldown = MagicMock()
        mock_result_cooldown.scalar_one_or_none.return_value = None

        factory, _ = _make_db_mock([mock_result_count, mock_result_cooldown])
        mock_db.side_effect = lambda: factory()

        service = SchedulingBrain()
        assert service.should_schedule_now() is True

    @patch(SYNC_DB_PATH)
    @patch(IS_ENABLED_SYNC_PATH, return_value=True)
    @patch(SETTINGS_PATH)
    def test_returns_true_when_no_previous_auto_scheduled_video(
        self, mock_settings, _mock_enabled, mock_db
    ):
        """First ever auto-schedule should pass cooldown check."""
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(
            auto_schedule_cooldown_hours=6, auto_schedule_max_daily=5
        )

        mock_result_count = MagicMock()
        mock_result_count.scalar.return_value = 0

        mock_result_cooldown = MagicMock()
        mock_result_cooldown.scalar_one_or_none.return_value = None

        factory, _ = _make_db_mock([mock_result_count, mock_result_cooldown])
        mock_db.side_effect = lambda: factory()

        service = SchedulingBrain()
        assert service.should_schedule_now() is True

    @patch(IS_ENABLED_SYNC_PATH, return_value=False)
    @patch(SETTINGS_PATH)
    def test_disabled_overrides_other_checks(self, mock_settings, _mock_enabled):
        """Even if all other conditions pass, disabled=False blocks scheduling."""
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(
            auto_schedule_enabled=False,
            auto_schedule_max_daily=100,
            auto_schedule_cooldown_hours=0,
        )

        service = SchedulingBrain()
        assert service.should_schedule_now() is False


# ===========================================================================
# TestGetTodayCount
# ===========================================================================


class TestGetTodayCount:
    """Tests for SchedulingBrain._get_today_count()."""

    @patch(SYNC_DB_PATH)
    @patch(SETTINGS_PATH)
    def test_returns_count_from_db(self, mock_settings, mock_db):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings()

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        session.execute.return_value = mock_result

        mock_db.return_value = _fake_sync_db(session)

        service = SchedulingBrain()
        assert service._get_today_count() == 5

    @patch(SYNC_DB_PATH)
    @patch(SETTINGS_PATH)
    def test_returns_zero_when_no_results(self, mock_settings, mock_db):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings()

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = None
        session.execute.return_value = mock_result

        mock_db.return_value = _fake_sync_db(session)

        service = SchedulingBrain()
        assert service._get_today_count() == 0

    @patch(SYNC_DB_PATH)
    @patch(SETTINGS_PATH)
    def test_queries_db_session(self, mock_settings, mock_db):
        """Verify the DB is queried (session.execute called)."""
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings()

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        session.execute.return_value = mock_result

        mock_db.return_value = _fake_sync_db(session)

        service = SchedulingBrain()
        result = service._get_today_count()

        assert result == 3
        session.execute.assert_called_once()


# ===========================================================================
# TestCooldownElapsed
# ===========================================================================


class TestCooldownElapsed:
    """Tests for SchedulingBrain._cooldown_elapsed()."""

    @patch(SYNC_DB_PATH)
    @patch(SETTINGS_PATH)
    def test_returns_true_when_no_previous_video(self, mock_settings, mock_db):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_cooldown_hours=4)

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_result

        mock_db.return_value = _fake_sync_db(session)

        service = SchedulingBrain()
        assert service._cooldown_elapsed() is True

    @patch(SYNC_DB_PATH)
    @patch(SETTINGS_PATH)
    def test_returns_true_when_cooldown_passed(self, mock_settings, mock_db):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_cooldown_hours=2)

        old_time = datetime.now(timezone.utc) - timedelta(hours=5)

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = old_time
        session.execute.return_value = mock_result

        mock_db.return_value = _fake_sync_db(session)

        service = SchedulingBrain()
        assert service._cooldown_elapsed() is True

    @patch(SYNC_DB_PATH)
    @patch(SETTINGS_PATH)
    def test_returns_false_when_cooldown_not_passed(self, mock_settings, mock_db):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_cooldown_hours=6)

        recent_time = datetime.now(timezone.utc) - timedelta(hours=2)

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = recent_time
        session.execute.return_value = mock_result

        mock_db.return_value = _fake_sync_db(session)

        service = SchedulingBrain()
        assert service._cooldown_elapsed() is False

    @patch(SYNC_DB_PATH)
    @patch(SETTINGS_PATH)
    def test_returns_true_when_cooldown_exactly_at_boundary(
        self, mock_settings, mock_db
    ):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_cooldown_hours=4)

        boundary_time = datetime.now(timezone.utc) - timedelta(hours=4)

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = boundary_time
        session.execute.return_value = mock_result

        mock_db.return_value = _fake_sync_db(session)

        service = SchedulingBrain()
        assert service._cooldown_elapsed() is True


# ===========================================================================
# TestRedisToggle
# ===========================================================================


class TestRedisToggle:
    """Tests for Redis-based runtime toggle (is_enabled, set_enabled, is_enabled_sync)."""

    @pytest.mark.asyncio
    @patch(SETTINGS_PATH)
    @patch("app.services.auto_schedule_service.aioredis")
    async def test_is_enabled_reads_redis(self, mock_aioredis, mock_settings):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings()

        mock_conn = AsyncMock()
        mock_conn.get = AsyncMock(return_value="1")
        mock_conn.aclose = AsyncMock()
        mock_aioredis.from_url.return_value = mock_conn

        service = SchedulingBrain()
        result = await service.is_enabled()

        assert result is True
        mock_conn.get.assert_awaited_once()

    @pytest.mark.asyncio
    @patch(SETTINGS_PATH)
    @patch("app.services.auto_schedule_service.aioredis")
    async def test_is_enabled_falls_back_to_settings(
        self, mock_aioredis, mock_settings
    ):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_enabled=True)
        mock_aioredis.from_url.side_effect = ConnectionError("Redis down")

        service = SchedulingBrain()
        result = await service.is_enabled()

        assert result is True

    @pytest.mark.asyncio
    @patch(SETTINGS_PATH)
    @patch("app.services.auto_schedule_service.aioredis")
    async def test_set_enabled_writes_redis(self, mock_aioredis, mock_settings):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings()

        mock_conn = AsyncMock()
        mock_conn.set = AsyncMock()
        mock_conn.aclose = AsyncMock()
        mock_aioredis.from_url.return_value = mock_conn

        service = SchedulingBrain()

        await service.set_enabled(True)
        mock_conn.set.assert_awaited_with("autopilot:enabled", "1")

        mock_conn.set.reset_mock()

        await service.set_enabled(False)
        mock_conn.set.assert_awaited_with("autopilot:enabled", "0")

    @patch(SETTINGS_PATH)
    @patch("redis.from_url")
    def test_is_enabled_sync_reads_redis(self, mock_redis_from_url, mock_settings):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings()

        mock_conn = MagicMock()
        mock_conn.get.return_value = "1"
        mock_redis_from_url.return_value = mock_conn

        service = SchedulingBrain()
        result = service.is_enabled_sync()

        assert result is True
        mock_conn.get.assert_called_once_with("autopilot:enabled")


# ===========================================================================
# TestPickBestTrend
# ===========================================================================


class TestPickBestTrend:
    """Tests for SchedulingBrain.pick_best_trend() (backward-compat sync wrapper)."""

    @patch(ASYNCIO_RUN_PATH)
    @patch(TREND_AGGREGATOR_PATH)
    @patch(SETTINGS_PATH)
    def test_returns_trend_on_success(
        self, mock_settings, mock_trend_cls, mock_asyncio_run
    ):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings()

        trend_data = {"topic": "AI breakthroughs", "trend_score": 85.0}
        mock_asyncio_run.return_value = trend_data

        service = SchedulingBrain()
        result = service.pick_best_trend(niche="science")

        assert result == trend_data
        mock_asyncio_run.assert_called_once()

    @patch(ASYNCIO_RUN_PATH)
    @patch(TREND_AGGREGATOR_PATH)
    @patch(SETTINGS_PATH)
    def test_returns_none_on_no_trends(
        self, mock_settings, mock_trend_cls, mock_asyncio_run
    ):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings()
        mock_asyncio_run.return_value = None

        service = SchedulingBrain()
        result = service.pick_best_trend(niche="science")

        assert result is None

    @patch(ASYNCIO_RUN_PATH)
    @patch(TREND_AGGREGATOR_PATH)
    @patch(SETTINGS_PATH)
    def test_returns_none_on_exception(
        self, mock_settings, mock_trend_cls, mock_asyncio_run
    ):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings()
        mock_asyncio_run.side_effect = ConnectionError("API unavailable")

        service = SchedulingBrain()
        result = service.pick_best_trend(niche="tech")

        assert result is None

    @patch(ASYNCIO_RUN_PATH)
    @patch(TREND_AGGREGATOR_PATH)
    @patch(SETTINGS_PATH)
    def test_passes_niche_to_trend_service(
        self, mock_settings, mock_trend_cls, mock_asyncio_run
    ):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings()
        mock_asyncio_run.return_value = {"topic": "Mars", "trend_score": 90}

        service = SchedulingBrain()
        service.pick_best_trend(niche="space")

        mock_asyncio_run.assert_called_once()


# ===========================================================================
# TestGetAutoScheduleStats
# ===========================================================================


class TestGetAutoScheduleStats:
    """Tests for SchedulingBrain.get_auto_schedule_stats() (sync backward-compat)."""

    @patch(SYNC_DB_PATH)
    @patch(SETTINGS_PATH)
    def test_returns_correct_dict_structure(self, mock_settings, mock_db):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(
            auto_schedule_enabled=True,
            auto_schedule_max_daily=5,
            auto_schedule_cooldown_hours=3,
            auto_schedule_niche="tech",
            auto_schedule_visual_strategy="ai_images",
        )

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 2
        session.execute.return_value = mock_result

        mock_db.return_value = _fake_sync_db(session)

        service = SchedulingBrain()
        stats = service.get_auto_schedule_stats()

        assert stats["enabled"] is True
        assert stats["today_count"] == 2
        assert stats["max_daily"] == 5
        assert stats["remaining_today"] == 3
        assert stats["cooldown_hours"] == 3
        assert stats["niche"] == "tech"
        assert stats["visual_strategy"] == "ai_images"

    @patch(SYNC_DB_PATH)
    @patch(SETTINGS_PATH)
    def test_remaining_never_negative(self, mock_settings, mock_db):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_max_daily=2)

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 10
        session.execute.return_value = mock_result

        mock_db.return_value = _fake_sync_db(session)

        service = SchedulingBrain()
        stats = service.get_auto_schedule_stats()

        assert stats["remaining_today"] == 0

    @patch(SYNC_DB_PATH)
    @patch(SETTINGS_PATH)
    def test_niche_defaults_to_any(self, mock_settings, mock_db):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_niche=None)

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        session.execute.return_value = mock_result

        mock_db.return_value = _fake_sync_db(session)

        service = SchedulingBrain()
        stats = service.get_auto_schedule_stats()

        assert stats["niche"] == "any"

    @patch(SYNC_DB_PATH)
    @patch(SETTINGS_PATH)
    def test_niche_empty_string_defaults_to_any(self, mock_settings, mock_db):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_niche="")

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        session.execute.return_value = mock_result

        mock_db.return_value = _fake_sync_db(session)

        service = SchedulingBrain()
        stats = service.get_auto_schedule_stats()

        assert stats["niche"] == "any"

    @patch(SYNC_DB_PATH)
    @patch(SETTINGS_PATH)
    def test_disabled_still_returns_stats(self, mock_settings, mock_db):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_enabled=False)

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        session.execute.return_value = mock_result

        mock_db.return_value = _fake_sync_db(session)

        service = SchedulingBrain()
        stats = service.get_auto_schedule_stats()

        assert stats["enabled"] is False
        assert "today_count" in stats
        assert "max_daily" in stats


# ===========================================================================
# TestSelectTopic
# ===========================================================================


class TestSelectTopic:
    """Tests for SchedulingBrain.select_topic() (async smart topic selection)."""

    @pytest.mark.asyncio
    @patch(SETTINGS_PATH)
    async def test_select_topic_returns_best(self, mock_settings):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(
            auto_schedule_performance_feedback=False,
        )

        candidates = [
            {"topic": "Quantum Computing", "quality_score": 80, "niche": "science"},
            {"topic": "Mars Rover", "quality_score": 60, "niche": "space"},
        ]

        with patch(
            "app.services.trend_service.TrendAggregator.get_best_topics_for_scheduling",
            new_callable=AsyncMock,
            return_value=candidates,
        ), patch.object(
            SchedulingBrain,
            "_get_last_n_categories",
            return_value=[],
        ):
            service = SchedulingBrain()
            result = await service.select_topic()

        assert result is not None
        assert result["topic"] == "Quantum Computing"
        assert result["quality_score"] == 80

    @pytest.mark.asyncio
    @patch(SETTINGS_PATH)
    async def test_select_topic_returns_none_when_empty(self, mock_settings):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(
            auto_schedule_performance_feedback=False,
        )

        with patch(
            "app.services.trend_service.TrendAggregator.get_best_topics_for_scheduling",
            new_callable=AsyncMock,
            return_value=[],
        ):
            service = SchedulingBrain()
            result = await service.select_topic()

        assert result is None

    @pytest.mark.asyncio
    @patch(SETTINGS_PATH)
    async def test_select_topic_applies_diversity(self, mock_settings):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(
            auto_schedule_performance_feedback=False,
            auto_schedule_diversity_window=3,
        )

        candidates = [
            {"topic": "Quantum Computing", "quality_score": 80, "niche": "science"},
            {"topic": "New Galaxy Found", "quality_score": 70, "niche": "space"},
        ]

        with patch(
            "app.services.trend_service.TrendAggregator.get_best_topics_for_scheduling",
            new_callable=AsyncMock,
            return_value=candidates,
        ), patch.object(
            SchedulingBrain,
            "_get_last_n_categories",
            return_value=["science", "science", "tech"],
        ):
            service = SchedulingBrain()
            result = await service.select_topic(niche_rotation=True)

        # "science" candidate should be deprioritized (score * 0.5 = 40),
        # so "space" at 70 should win
        assert result is not None
        assert result["topic"] == "New Galaxy Found"


# ===========================================================================
# TestDiversityFilter
# ===========================================================================


class TestDiversityFilter:
    """Tests for SchedulingBrain._apply_diversity_filter()."""

    @patch(SETTINGS_PATH)
    def test_diversity_reduces_same_category_score(self, mock_settings):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_diversity_window=3)

        candidates = [
            {"topic": "Black Holes", "quality_score": 100, "niche": "science"},
            {"topic": "New Galaxy", "quality_score": 80, "niche": "space"},
        ]

        with patch.object(
            SchedulingBrain,
            "_get_last_n_categories",
            return_value=["science", "tech"],
        ):
            service = SchedulingBrain()
            filtered = service._apply_diversity_filter(candidates)

        # "science" was recently used -> score halved
        science_topic = next(c for c in filtered if c["niche"] == "science")
        space_topic = next(c for c in filtered if c["niche"] == "space")

        assert science_topic["quality_score"] == 50  # 100 * 0.5
        assert space_topic["quality_score"] == 80  # unchanged

    @patch(SETTINGS_PATH)
    def test_diversity_no_change_when_different_category(self, mock_settings):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_diversity_window=3)

        candidates = [
            {"topic": "AI Ethics", "quality_score": 90, "niche": "tech"},
            {"topic": "Mars Mission", "quality_score": 85, "niche": "space"},
        ]

        with patch.object(
            SchedulingBrain,
            "_get_last_n_categories",
            return_value=["science", "history"],
        ):
            service = SchedulingBrain()
            filtered = service._apply_diversity_filter(candidates)

        # Neither category was recently used -> no change
        assert filtered[0]["quality_score"] == 90
        assert filtered[1]["quality_score"] == 85


# ===========================================================================
# Backward Compatibility Alias Check
# ===========================================================================


class TestBackwardCompatAlias:
    """Verify AutoScheduleService is an alias for SchedulingBrain."""

    def test_alias_points_to_scheduling_brain(self):
        from app.services.auto_schedule_service import (
            AutoScheduleService,
            SchedulingBrain,
        )

        assert AutoScheduleService is SchedulingBrain

    @patch(IS_ENABLED_SYNC_PATH, return_value=False)
    @patch(SETTINGS_PATH)
    def test_should_auto_schedule_is_alias_for_should_schedule_now(
        self, mock_settings, _mock_enabled
    ):
        from app.services.auto_schedule_service import SchedulingBrain

        mock_settings.return_value = _make_settings(auto_schedule_enabled=False)

        service = SchedulingBrain()
        # Both should return the same result
        assert service.should_auto_schedule() is False
        assert service.should_schedule_now() is False
