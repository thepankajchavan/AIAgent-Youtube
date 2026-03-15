"""Tests for auto-schedule Celery tasks (fixed-time + legacy).

After the event-loop consolidation fix, _run_async is called with consolidated
async helpers instead of individual coroutines:
- _fetch_trends_and_select_topic() → (topic, trend_count)
- _log_decision(action, topic, reason, details) → None
- _evaluate_and_select() → (dispatch_result, topic)
- _enqueue_and_log(topic) → (queue_id, scheduled_for_iso, next_time)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SETTINGS_PATH = "app.workers.auto_schedule_tasks.get_settings"
RUN_ASYNC_PATH = "app.workers.auto_schedule_tasks._run_async"
NOTIFY_PATH = "app.workers.auto_schedule_tasks._notify_admin"
BRAIN_PATH = "app.services.auto_schedule_service.SchedulingBrain"
TREND_AGG_PATH = "app.services.trend_service.TrendAggregator"


def _make_settings(**overrides) -> MagicMock:
    """Build a mock settings object with auto-schedule defaults."""
    defaults = {
        "auto_schedule_enabled": True,
        "auto_schedule_max_daily": 2,
        "auto_schedule_cooldown_hours": 4,
        "auto_schedule_niche": "science",
        "auto_schedule_visual_strategy": "stock_only",
        "auto_schedule_skip_upload": False,
        "auto_schedule_admin_chat_id": 0,
        "auto_schedule_times": "10:00,18:00",
        "telegram_bot_token": "",
        "redis_url": "redis://localhost",
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


# ===========================================================================
# scheduled_video_task (fixed-time all-in-one task)
# ===========================================================================


class TestScheduledVideoTask:
    """Tests for the fixed-time scheduled_video_task."""

    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_disabled_returns_disabled(self, mock_settings, mock_brain_cls):
        """When autopilot is disabled, task returns disabled."""
        from app.workers.auto_schedule_tasks import scheduled_video_task

        mock_settings.return_value = _make_settings(auto_schedule_enabled=False)
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = False

        result = scheduled_video_task()

        assert result["status"] == "disabled"

    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_daily_limit_returns_skipped(self, mock_settings, mock_brain_cls):
        """When daily limit reached, task returns skipped."""
        from app.workers.auto_schedule_tasks import scheduled_video_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = False

        result = scheduled_video_task()

        assert result["status"] == "skipped"
        assert result["reason"] == "daily limit or cooldown"

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_fetches_trends_then_dispatches(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """Happy path: fetch trends → pick topic → dispatch pipeline."""
        from app.workers.auto_schedule_tasks import scheduled_video_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True
        brain._create_and_dispatch.return_value = ("proj-123", MagicMock())

        topic = {"topic": "AI Revolution 2026", "quality_score": 85.0}

        # _run_async calls:
        # 1. _fetch_trends_and_select_topic() -> (topic, 5)
        # 2. _log_decision(dispatched) -> None
        mock_run_async.side_effect = [(topic, 5), None]

        result = scheduled_video_task()

        assert result["status"] == "dispatched"
        assert result["project_id"] == "proj-123"
        assert result["topic"] == "AI Revolution 2026"
        assert result["quality_score"] == 85.0
        brain._create_and_dispatch.assert_called_once()
        mock_notify.assert_called()

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_no_topics_uses_fallback(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """When no suitable topics found, task uses a curated fallback topic."""
        from app.workers.auto_schedule_tasks import scheduled_video_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True
        brain._create_and_dispatch.return_value = ("proj-fallback", MagicMock())

        # _run_async calls:
        # 1. _fetch_trends_and_select_topic() -> (None, 3) — no topic found
        # 2. _log_decision(fallback) -> None
        # 3. _log_decision(dispatched) -> None
        mock_run_async.side_effect = [(None, 3), None, None]

        result = scheduled_video_task()

        assert result["status"] == "dispatched"
        assert result["project_id"] == "proj-fallback"
        # Should have notified about using fallback + dispatch
        assert mock_notify.call_count >= 1
        brain._create_and_dispatch.assert_called_once()

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_trend_fetch_failure_still_picks_existing(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """If trend fetch fails inside helper, still returns topic from existing trends."""
        from app.workers.auto_schedule_tasks import scheduled_video_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True
        brain._create_and_dispatch.return_value = ("proj-456", MagicMock())

        topic = {"topic": "Quantum Computing", "quality_score": 70.0}

        # _fetch_trends_and_select_topic handles the error internally
        # and still returns a topic from existing DB trends
        mock_run_async.side_effect = [(topic, 0), None]

        result = scheduled_video_task()

        assert result["status"] == "dispatched"
        assert result["topic"] == "Quantum Computing"

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_dispatch_failure_returns_failed(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """When pipeline dispatch fails after retries, task returns failed."""
        from app.workers.auto_schedule_tasks import scheduled_video_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True
        brain._create_and_dispatch.side_effect = Exception("DB connection lost")

        topic = {"topic": "Mars Mission", "quality_score": 60.0}
        # _fetch_trends_and_select_topic -> (topic, 5)
        mock_run_async.side_effect = [(topic, 5)]

        with patch.object(scheduled_video_task, "max_retries", 0):
            result = scheduled_video_task()

        assert result["status"] == "failed"
        assert "DB connection lost" in result["error"]

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_notification_contains_topic_name(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """Admin notification includes the selected topic name."""
        from app.workers.auto_schedule_tasks import scheduled_video_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True
        brain._create_and_dispatch.return_value = ("proj-789", MagicMock())

        topic = {"topic": "Neural Networks Breakthrough", "quality_score": 92.0}
        mock_run_async.side_effect = [(topic, 10), None]

        scheduled_video_task()

        # The notify call (after dispatch) should contain the topic
        notify_calls = mock_notify.call_args_list
        assert any("Neural Networks" in str(c) for c in notify_calls)

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_logs_decision_on_dispatch(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """_log_decision is called after successful dispatch."""
        from app.workers.auto_schedule_tasks import scheduled_video_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True
        brain._create_and_dispatch.return_value = ("proj-abc", MagicMock())

        topic = {"topic": "Space Exploration", "quality_score": 80.0}
        # 1. _fetch_trends_and_select_topic -> (topic, 5)
        # 2. _log_decision(dispatched) -> None
        mock_run_async.side_effect = [(topic, 5), None]

        scheduled_video_task()

        # 2 _run_async calls: fetch+select, log_decision
        assert mock_run_async.call_count == 2


# ===========================================================================
# schedule_evaluation_task (legacy — backward compatibility)
# ===========================================================================


class TestScheduleEvaluationTask:
    """Tests for the legacy schedule_evaluation_task Celery task."""

    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_disabled_returns_disabled(self, mock_settings, mock_brain_cls):
        """When is_enabled_sync returns False, task returns disabled."""
        from app.workers.auto_schedule_tasks import schedule_evaluation_task

        mock_settings.return_value = _make_settings(auto_schedule_enabled=False)
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = False

        result = schedule_evaluation_task()

        assert result["status"] == "disabled"

    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_skipped_limit_or_cooldown(self, mock_settings, mock_brain_cls):
        """When should_schedule_now returns False, task returns skipped."""
        from app.workers.auto_schedule_tasks import schedule_evaluation_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = False

        result = schedule_evaluation_task()

        assert result["status"] == "skipped"
        assert result["reason"] == "daily limit or cooldown"

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_dispatches_queued_item(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """When _evaluate_and_select returns dispatch_result, task returns dispatched."""
        from app.workers.auto_schedule_tasks import schedule_evaluation_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True

        dispatch_result = {
            "queue_id": "q-123",
            "project_id": "proj-abc",
            "topic": "AI breakthroughs",
        }
        # _evaluate_and_select -> (dispatch_result, None)
        mock_run_async.return_value = (dispatch_result, None)

        result = schedule_evaluation_task()

        assert result["status"] == "dispatched"
        assert result["topic"] == "AI breakthroughs"
        assert result["project_id"] == "proj-abc"
        mock_notify.assert_called_once()

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_no_topics_returns_skipped(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """When _evaluate_and_select returns (None, None), task skips."""
        from app.workers.auto_schedule_tasks import schedule_evaluation_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True

        # 1. _evaluate_and_select -> (None, None) — no dispatch, no topic
        # 2. _log_decision(no_topics) -> None
        mock_run_async.side_effect = [(None, None), None]

        result = schedule_evaluation_task()

        assert result["status"] == "skipped"
        assert result["reason"] == "no topics available"

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_enqueues_new_topic(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """When _evaluate_and_select finds topic, _enqueue_and_log enqueues it."""
        from app.workers.auto_schedule_tasks import schedule_evaluation_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True

        now = datetime.now(timezone.utc)
        topic = {"topic": "AI trend in robotics", "quality_score": 75.0}

        # 1. _evaluate_and_select -> (None, topic) — no dispatch, but found topic
        # 2. _enqueue_and_log -> (queue_id, iso_str, next_time)
        mock_run_async.side_effect = [
            (None, topic),
            ("queue-123", now.isoformat(), now),
        ]

        result = schedule_evaluation_task()

        assert result["status"] == "enqueued"
        assert result["queue_id"] == "queue-123"
        assert result["topic"] == "AI trend in robotics"
        assert result["quality_score"] == 75.0
        assert "scheduled_for" in result

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_enqueue_sends_admin_notification(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """Verify _notify_admin is called when a topic is enqueued."""
        from app.workers.auto_schedule_tasks import schedule_evaluation_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True

        now = datetime.now(timezone.utc)
        topic = {"topic": "Quantum computing 2026", "quality_score": 88.0}

        mock_run_async.side_effect = [
            (None, topic),
            ("queue-456", now.isoformat(), now),
        ]

        schedule_evaluation_task()

        mock_notify.assert_called_once()
        call_args = mock_notify.call_args[0][0]
        assert "Quantum computing 2026" in call_args

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_dispatch_notification_includes_project_id(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """When a queued item is dispatched, notification includes project_id."""
        from app.workers.auto_schedule_tasks import schedule_evaluation_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True

        dispatch_result = {
            "queue_id": "q-999",
            "project_id": "proj-xyz",
            "topic": "Neural networks",
        }
        # _evaluate_and_select -> (dispatch_result, None)
        mock_run_async.return_value = (dispatch_result, None)

        schedule_evaluation_task()

        call_args = mock_notify.call_args[0][0]
        assert "proj-xyz" in call_args

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_enqueued_result_contains_scheduled_for_isoformat(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """Enqueued result scheduled_for is an ISO-format datetime string."""
        from app.workers.auto_schedule_tasks import schedule_evaluation_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True

        scheduled_time = datetime(2026, 3, 15, 14, 0, 0, tzinfo=timezone.utc)
        topic = {"topic": "Mars colonization", "quality_score": 90.0}

        mock_run_async.side_effect = [
            (None, topic),
            ("q-789", "2026-03-15T14:00:00+00:00", scheduled_time),
        ]

        result = schedule_evaluation_task()

        assert result["scheduled_for"] == "2026-03-15T14:00:00+00:00"

    @patch(NOTIFY_PATH)
    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_no_topics_logs_decision(
        self, mock_settings, mock_brain_cls, mock_run_async, mock_notify
    ):
        """When no topics available, _log_decision is called."""
        from app.workers.auto_schedule_tasks import schedule_evaluation_task

        mock_settings.return_value = _make_settings()
        brain = mock_brain_cls.return_value
        brain.is_enabled_sync.return_value = True
        brain.should_schedule_now.return_value = True

        # 1. _evaluate_and_select -> (None, None)
        # 2. _log_decision(no_topics) -> None
        mock_run_async.side_effect = [(None, None), None]

        schedule_evaluation_task()

        # 2 _run_async calls: evaluate+select, log_decision
        assert mock_run_async.call_count == 2


# ===========================================================================
# dispatch_scheduled_task
# ===========================================================================


class TestDispatchScheduledTask:
    """Tests for the dispatch_scheduled_task Celery task."""

    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_success_dispatches(self, mock_settings, mock_brain_cls, mock_run_async):
        """When dispatch_queued returns a result, task returns dispatched."""
        from app.workers.auto_schedule_tasks import dispatch_scheduled_task

        mock_settings.return_value = _make_settings()

        dispatch_result = {
            "queue_id": "q-dispatch-1",
            "project_id": "proj-dispatch-1",
            "topic": "Space exploration update",
        }
        mock_run_async.return_value = dispatch_result

        result = dispatch_scheduled_task("q-dispatch-1")

        assert result["status"] == "dispatched"
        assert result["project_id"] == "proj-dispatch-1"
        assert result["topic"] == "Space exploration update"

    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_nothing_due(self, mock_settings, mock_brain_cls, mock_run_async):
        """When dispatch_queued returns None, task returns nothing_due."""
        from app.workers.auto_schedule_tasks import dispatch_scheduled_task

        mock_settings.return_value = _make_settings()
        mock_run_async.return_value = None

        result = dispatch_scheduled_task("q-empty")

        assert result["status"] == "nothing_due"

    @patch(RUN_ASYNC_PATH)
    @patch(BRAIN_PATH)
    @patch(SETTINGS_PATH)
    def test_failure_retries_exhausted(
        self, mock_settings, mock_brain_cls, mock_run_async
    ):
        """When dispatch raises and retries are exhausted, returns failed."""
        from app.workers.auto_schedule_tasks import dispatch_scheduled_task

        mock_settings.return_value = _make_settings()
        mock_run_async.side_effect = Exception("DB connection lost")

        with patch.object(dispatch_scheduled_task, "max_retries", 0):
            result = dispatch_scheduled_task("q-fail")

        assert result["status"] == "failed"
        assert "DB connection lost" in result["error"]
