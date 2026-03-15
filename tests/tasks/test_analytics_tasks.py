"""Tests for analytics Celery tasks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestCollectAnalyticsTask:
    """Tests for the collect_analytics_task Celery task."""

    @patch("app.workers.analytics_tasks._run_async")
    @patch("app.workers.analytics_tasks.get_settings")
    def test_collect_analytics_disabled(self, mock_settings, mock_run_async):
        from app.workers.analytics_tasks import collect_analytics_task

        settings = MagicMock()
        settings.youtube_analytics_enabled = False
        mock_settings.return_value = settings

        result = collect_analytics_task()

        assert result["status"] == "disabled"
        mock_run_async.assert_not_called()

    @patch("app.workers.analytics_tasks._run_async")
    @patch("app.workers.analytics_tasks.get_settings")
    def test_collect_analytics_success(self, mock_settings, mock_run_async):
        from app.workers.analytics_tasks import collect_analytics_task

        settings = MagicMock()
        settings.youtube_analytics_enabled = True
        settings.youtube_analytics_lookback_days = 7
        settings.self_improvement_enabled = False
        mock_settings.return_value = settings

        mock_run_async.return_value = [{"views": 100}, {"views": 200}]

        result = collect_analytics_task()

        assert result["status"] == "success"
        assert result["videos_collected"] == 2

    @patch("app.workers.analytics_tasks._run_async")
    @patch("app.workers.analytics_tasks.get_settings")
    def test_collect_analytics_with_prompt_update(self, mock_settings, mock_run_async):
        from app.workers.analytics_tasks import collect_analytics_task

        settings = MagicMock()
        settings.youtube_analytics_enabled = True
        settings.youtube_analytics_lookback_days = 7
        settings.self_improvement_enabled = True
        mock_settings.return_value = settings

        # First call: collect_all_recent_videos, second call: update_all_prompt_performance
        mock_run_async.side_effect = [
            [{"views": 100}],  # analytics results
            None,  # prompt update
        ]

        result = collect_analytics_task()

        assert result["status"] == "success"
        assert mock_run_async.call_count == 2

    @patch("app.workers.analytics_tasks._run_async")
    @patch("app.workers.analytics_tasks.get_settings")
    def test_collect_analytics_failure_retries(self, mock_settings, mock_run_async):
        from app.workers.analytics_tasks import collect_analytics_task

        settings = MagicMock()
        settings.youtube_analytics_enabled = True
        settings.youtube_analytics_lookback_days = 7
        mock_settings.return_value = settings

        mock_run_async.side_effect = ConnectionError("YouTube API down")

        with patch.object(collect_analytics_task, "max_retries", 0):
            with pytest.raises(ConnectionError):
                collect_analytics_task()
