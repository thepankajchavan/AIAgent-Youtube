"""Tests for trend collection, cleanup, and health-check Celery tasks."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SETTINGS_PATH = "app.workers.trend_tasks.get_settings"
RUN_ASYNC_PATH = "app.workers.trend_tasks._run_async"


def _make_settings(**overrides) -> MagicMock:
    """Build a mock settings object with trend-task defaults."""
    defaults = {
        "trends_enabled": True,
        "auto_schedule_admin_chat_id": 0,
        "telegram_bot_token": "",
        "redis_url": "redis://localhost",
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


@contextmanager
def _fake_sync_db(session):
    """Mimic get_sync_db() context manager returning a mock session."""
    yield session


# ===========================================================================
# collect_all_trends_task
# ===========================================================================


class TestCollectAllTrendsTask:
    """Tests for collect_all_trends_task."""

    @patch(RUN_ASYNC_PATH)
    @patch(SETTINGS_PATH)
    def test_disabled(self, mock_settings, mock_run_async):
        """When trends_enabled=False the task returns disabled immediately."""
        from app.workers.trend_tasks import collect_all_trends_task

        mock_settings.return_value = _make_settings(trends_enabled=False)

        result = collect_all_trends_task()

        assert result["status"] == "disabled"
        mock_run_async.assert_not_called()

    @patch(RUN_ASYNC_PATH)
    @patch(SETTINGS_PATH)
    def test_success(self, mock_settings, mock_run_async):
        """Successful collection records health and returns trend count."""
        from app.workers.trend_tasks import collect_all_trends_task

        mock_settings.return_value = _make_settings()

        # First _run_async: collect_and_store_trends -> 5
        # Second _run_async: record_successful_fetch -> None
        mock_run_async.side_effect = [5, None]

        result = collect_all_trends_task()

        assert result["status"] == "success"
        assert result["trends_collected"] == 5
        assert mock_run_async.call_count == 2

    @patch(RUN_ASYNC_PATH)
    @patch(SETTINGS_PATH)
    def test_failure_retries_exhausted(self, mock_settings, mock_run_async):
        """When collection raises and retries exhausted, returns failed."""
        from app.workers.trend_tasks import collect_all_trends_task

        mock_settings.return_value = _make_settings()
        mock_run_async.side_effect = Exception("API timeout")

        with patch.object(collect_all_trends_task, "max_retries", 0):
            result = collect_all_trends_task()

        assert result["status"] == "failed"
        assert "API timeout" in result["error"]

    @patch(RUN_ASYNC_PATH)
    @patch(SETTINGS_PATH)
    def test_zero_results(self, mock_settings, mock_run_async):
        """When no trends found, still returns success with count 0."""
        from app.workers.trend_tasks import collect_all_trends_task

        mock_settings.return_value = _make_settings()
        # collect_and_store_trends -> 0, record_successful_fetch -> None
        mock_run_async.side_effect = [0, None]

        result = collect_all_trends_task()

        assert result["status"] == "success"
        assert result["trends_collected"] == 0


# ===========================================================================
# cleanup_expired_trends_task
# ===========================================================================


class TestCleanupExpiredTrendsTask:
    """Tests for cleanup_expired_trends_task."""

    @patch(SETTINGS_PATH)
    def test_disabled(self, mock_settings):
        """When trends_enabled=False the task returns disabled."""
        from app.workers.trend_tasks import cleanup_expired_trends_task

        mock_settings.return_value = _make_settings(trends_enabled=False)

        result = cleanup_expired_trends_task()

        assert result["status"] == "disabled"

    @patch("app.workers.db.get_sync_db")
    @patch(SETTINGS_PATH)
    def test_success_deletes_expired(self, mock_settings, mock_db):
        """Deletes expired trends and returns the count."""
        from app.workers.trend_tasks import cleanup_expired_trends_task

        mock_settings.return_value = _make_settings()

        session = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        session.execute.return_value = mock_result
        mock_db.return_value = _fake_sync_db(session)

        result = cleanup_expired_trends_task()

        assert result["status"] == "success"
        assert result["deleted"] == 3
        session.execute.assert_called_once()


# ===========================================================================
# check_trend_health_task
# ===========================================================================


class TestCheckTrendHealthTask:
    """Tests for check_trend_health_task."""

    @patch(SETTINGS_PATH)
    def test_disabled(self, mock_settings):
        """When trends_enabled=False the task returns disabled."""
        from app.workers.trend_tasks import check_trend_health_task

        mock_settings.return_value = _make_settings(trends_enabled=False)

        result = check_trend_health_task()

        assert result["status"] == "disabled"

    @patch(RUN_ASYNC_PATH)
    @patch(SETTINGS_PATH)
    def test_healthy(self, mock_settings, mock_run_async):
        """When health check reports healthy, returns status=healthy."""
        from app.workers.trend_tasks import check_trend_health_task

        mock_settings.return_value = _make_settings()
        mock_run_async.return_value = {
            "healthy": True,
            "last_fetch_ago_hours": 1.5,
            "last_fetch_at": "2026-03-12T10:00:00+00:00",
            "status": "healthy",
        }

        result = check_trend_health_task()

        assert result["status"] == "healthy"
        assert result["healthy"] is True
        assert result["last_fetch_ago_hours"] == 1.5
