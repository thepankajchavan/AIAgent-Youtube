"""Tests for pattern analysis Celery tasks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestAnalyzePatternsTask:
    """Tests for the analyze_patterns_task Celery task."""

    @patch("app.workers.pattern_tasks._run_async")
    @patch("app.workers.pattern_tasks.get_settings")
    def test_analyze_patterns_disabled(self, mock_settings, mock_run_async):
        from app.workers.pattern_tasks import analyze_patterns_task

        settings = MagicMock()
        settings.self_improvement_enabled = False
        mock_settings.return_value = settings

        result = analyze_patterns_task()

        assert result["status"] == "disabled"
        mock_run_async.assert_not_called()

    @patch("app.workers.pattern_tasks._run_async")
    @patch("app.workers.pattern_tasks.get_settings")
    def test_analyze_patterns_skipped_insufficient_data(
        self, mock_settings, mock_run_async
    ):
        from app.workers.pattern_tasks import analyze_patterns_task

        settings = MagicMock()
        settings.self_improvement_enabled = True
        mock_settings.return_value = settings

        # should_run_analysis returns False
        mock_run_async.return_value = False

        result = analyze_patterns_task()

        assert result["status"] == "skipped"
        assert result["reason"] == "insufficient_data"

    @patch("app.workers.pattern_tasks._run_async")
    @patch("app.workers.pattern_tasks.get_settings")
    def test_analyze_patterns_success(self, mock_settings, mock_run_async):
        from app.workers.pattern_tasks import analyze_patterns_task

        settings = MagicMock()
        settings.self_improvement_enabled = True
        mock_settings.return_value = settings

        # First call: should_run_analysis → True
        # Second call: analyze_patterns → list of patterns
        mock_run_async.side_effect = [
            True,
            [
                {"pattern_type": "hook_style", "description": "Use questions"},
                {"pattern_type": "topic", "description": "Tech topics win"},
            ],
        ]

        result = analyze_patterns_task()

        assert result["status"] == "success"
        assert result["patterns_discovered"] == 2

    @patch("app.workers.pattern_tasks._run_async")
    @patch("app.workers.pattern_tasks.get_settings")
    def test_analyze_patterns_failure_retries(self, mock_settings, mock_run_async):
        from app.workers.pattern_tasks import analyze_patterns_task

        settings = MagicMock()
        settings.self_improvement_enabled = True
        mock_settings.return_value = settings

        mock_run_async.side_effect = Exception("LLM failed")

        with patch.object(analyze_patterns_task, "max_retries", 0):
            with pytest.raises(Exception):
                analyze_patterns_task()

    @patch("app.workers.pattern_tasks._run_async")
    @patch("app.workers.pattern_tasks.get_settings")
    def test_analyze_patterns_creates_improved_version(
        self, mock_settings, mock_run_async
    ):
        from app.workers.pattern_tasks import analyze_patterns_task

        settings = MagicMock()
        settings.self_improvement_enabled = True
        mock_settings.return_value = settings

        patterns = [
            {"pattern_type": "hook_style", "description": "P1"},
            {"pattern_type": "topic", "description": "P2"},
            {"pattern_type": "length", "description": "P3"},
        ]

        # should_run → True, analyze → patterns, maybe_create → None
        mock_run_async.side_effect = [True, patterns, None]

        result = analyze_patterns_task()

        assert result["status"] == "success"
        assert result["patterns_discovered"] == 3
        # maybe_create_improved_version should have been called (3rd _run_async call)
        assert mock_run_async.call_count == 3
