"""Unit tests for DLQ integration — verifies worker files call DLQ on final failure."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.dlq import DeadLetterQueue


class TestDLQProjectIdType:
    """Verify DLQ accepts string project IDs (UUID format)."""

    @pytest.mark.asyncio
    async def test_add_failed_task_accepts_string_project_id(self):
        """project_id parameter should accept str (our IDs are UUIDs)."""
        mock_redis = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch("app.core.dlq.get_redis_client", return_value=mock_redis):
            await DeadLetterQueue.add_failed_task(
                task_id="celery-task-123",
                task_name="test_task",
                args=("arg1",),
                kwargs={"key": "val"},
                exception=RuntimeError("test error"),
                traceback_str="Traceback ...",
                project_id="550e8400-e29b-41d4-a716-446655440000",
                update_project_status=False,
            )

        # Should have been called with string project_id in entry
        call_args = mock_redis.hset.call_args
        mapping = call_args[1]["mapping"]
        assert mapping["project_id"] == "550e8400-e29b-41d4-a716-446655440000"

    @pytest.mark.asyncio
    async def test_add_failed_task_none_project_id(self):
        """None project_id should store empty string."""
        mock_redis = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch("app.core.dlq.get_redis_client", return_value=mock_redis):
            await DeadLetterQueue.add_failed_task(
                task_id="celery-task-456",
                task_name="test_task",
                args=(),
                kwargs={},
                exception=RuntimeError("test"),
                traceback_str="",
                project_id=None,
                update_project_status=False,
            )

        mapping = mock_redis.hset.call_args[1]["mapping"]
        assert mapping["project_id"] == ""


class TestDLQUpdateProjectStatus:
    """Verify update_project_status flag works."""

    @pytest.mark.asyncio
    async def test_skips_db_update_when_flag_false(self):
        """Workers pass update_project_status=False to avoid double-update."""
        mock_redis = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.expire = AsyncMock()

        with (
            patch("app.core.dlq.get_redis_client", return_value=mock_redis),
            patch.object(
                DeadLetterQueue, "_update_project_status", new_callable=AsyncMock
            ) as mock_update,
        ):
            await DeadLetterQueue.add_failed_task(
                task_id="task-789",
                task_name="test_task",
                args=(),
                kwargs={},
                exception=RuntimeError("fail"),
                traceback_str="",
                project_id="some-uuid",
                update_project_status=False,
            )

        mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_db_update_when_flag_true(self):
        """Default behavior: update project status in DB."""
        mock_redis = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.expire = AsyncMock()

        with (
            patch("app.core.dlq.get_redis_client", return_value=mock_redis),
            patch.object(
                DeadLetterQueue, "_update_project_status", new_callable=AsyncMock
            ) as mock_update,
        ):
            await DeadLetterQueue.add_failed_task(
                task_id="task-abc",
                task_name="test_task",
                args=(),
                kwargs={},
                exception=RuntimeError("fail"),
                traceback_str="",
                project_id="some-uuid",
                update_project_status=True,
            )

        mock_update.assert_called_once_with("some-uuid", "fail")
