"""
Dead Letter Queue (DLQ) - Handles permanently failed Celery tasks.

Tasks that fail after all retry attempts are moved to the DLQ for:
- Manual inspection
- Error analysis
- Potential retry
- User notification
"""

from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.core.database import get_async_session
from app.core.redis_client import get_redis_client
from app.models.video_project import ProjectStatus, VideoProject


class DeadLetterQueue:
    """Manages permanently failed tasks in Redis."""

    DLQ_KEY_PREFIX = "dlq:"
    DLQ_LIST_KEY = "dlq:tasks"
    DLQ_TASK_KEY = "dlq:task:{task_id}"

    @classmethod
    async def add_failed_task(
        cls,
        task_id: str,
        task_name: str,
        args: tuple,
        kwargs: dict,
        exception: Exception,
        traceback_str: str,
        project_id: int | None = None,
    ) -> None:
        """
        Add a permanently failed task to the DLQ.

        Args:
            task_id: Celery task ID
            task_name: Name of the failed task
            args: Task positional arguments
            kwargs: Task keyword arguments
            exception: Exception that caused the failure
            traceback_str: Full traceback string
            project_id: Associated VideoProject ID (if applicable)
        """
        redis = await get_redis_client()

        # Create DLQ entry
        dlq_entry = {
            "task_id": task_id,
            "task_name": task_name,
            "args": str(args),
            "kwargs": str(kwargs),
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
            "traceback": traceback_str,
            "project_id": project_id,
            "failed_at": datetime.now(UTC).isoformat(),
            "retry_count": 0,
            "status": "failed",
        }

        # Store task details
        task_key = cls.DLQ_TASK_KEY.format(task_id=task_id)
        await redis.hset(task_key, mapping=dlq_entry)

        # Add to DLQ list (for enumeration)
        await redis.lpush(cls.DLQ_LIST_KEY, task_id)

        # Set expiry (keep for 30 days)
        await redis.expire(task_key, 30 * 24 * 60 * 60)

        logger.error(
            f"Task {task_id} ({task_name}) added to DLQ. "
            f"Project: {project_id}, Error: {exception}"
        )

        # Update project status if applicable
        if project_id:
            await cls._update_project_status(project_id, str(exception))

    @classmethod
    async def _update_project_status(cls, project_id: int, error_message: str) -> None:
        """Mark project as permanently failed in database."""
        async for session in get_async_session():
            try:
                result = await session.execute(
                    select(VideoProject).where(VideoProject.id == project_id)
                )
                project = result.scalar_one_or_none()

                if project and project.status != ProjectStatus.COMPLETED:
                    project.status = ProjectStatus.FAILED
                    project.error_message = f"Permanent failure (DLQ): {error_message}"
                    await session.commit()

                    logger.info(f"Project {project_id} marked as permanently failed")
            except Exception as e:
                logger.error(f"Failed to update project status: {e}")
                await session.rollback()
            finally:
                await session.close()
                break

    @classmethod
    async def get_all_tasks(cls, limit: int = 100) -> list[dict[str, Any]]:
        """
        Retrieve all tasks in the DLQ.

        Args:
            limit: Maximum number of tasks to retrieve

        Returns:
            List of DLQ task entries
        """
        redis = await get_redis_client()

        # Get task IDs from list
        task_ids = await redis.lrange(cls.DLQ_LIST_KEY, 0, limit - 1)

        if not task_ids:
            return []

        tasks = []
        for task_id in task_ids:
            task_key = cls.DLQ_TASK_KEY.format(task_id=task_id.decode())
            task_data = await redis.hgetall(task_key)

            if task_data:
                # Convert bytes to strings
                task_dict = {
                    k.decode(): v.decode() if isinstance(v, bytes) else v
                    for k, v in task_data.items()
                }
                tasks.append(task_dict)

        return tasks

    @classmethod
    async def get_task(cls, task_id: str) -> dict[str, Any] | None:
        """
        Retrieve a specific task from the DLQ.

        Args:
            task_id: Celery task ID

        Returns:
            DLQ task entry or None if not found
        """
        redis = await get_redis_client()

        task_key = cls.DLQ_TASK_KEY.format(task_id=task_id)
        task_data = await redis.hgetall(task_key)

        if not task_data:
            return None

        # Convert bytes to strings
        return {k.decode(): v.decode() if isinstance(v, bytes) else v for k, v in task_data.items()}

    @classmethod
    async def remove_task(cls, task_id: str) -> bool:
        """
        Remove a task from the DLQ (after manual resolution).

        Args:
            task_id: Celery task ID

        Returns:
            True if removed, False if not found
        """
        redis = await get_redis_client()

        task_key = cls.DLQ_TASK_KEY.format(task_id=task_id)

        # Remove from hash
        deleted = await redis.delete(task_key)

        # Remove from list
        await redis.lrem(cls.DLQ_LIST_KEY, 0, task_id)

        if deleted:
            logger.info(f"Task {task_id} removed from DLQ")
            return True

        return False

    @classmethod
    async def mark_retried(cls, task_id: str) -> None:
        """
        Mark a DLQ task as retried.

        Args:
            task_id: Celery task ID
        """
        redis = await get_redis_client()

        task_key = cls.DLQ_TASK_KEY.format(task_id=task_id)

        await redis.hset(task_key, "status", "retried")
        await redis.hincrby(task_key, "retry_count", 1)
        await redis.hset(task_key, "retried_at", datetime.now(UTC).isoformat())

        logger.info(f"Task {task_id} marked as retried in DLQ")

    @classmethod
    async def get_dlq_stats(cls) -> dict[str, Any]:
        """
        Get DLQ statistics.

        Returns:
            Dictionary with DLQ statistics
        """
        redis = await get_redis_client()

        total_tasks = await redis.llen(cls.DLQ_LIST_KEY)

        # Get all tasks to compute stats
        tasks = await cls.get_all_tasks(limit=1000)

        failed_count = sum(1 for t in tasks if t.get("status") == "failed")
        retried_count = sum(1 for t in tasks if t.get("status") == "retried")

        # Group by exception type
        exception_types: dict[str, int] = {}
        for task in tasks:
            exc_type = task.get("exception_type", "Unknown")
            exception_types[exc_type] = exception_types.get(exc_type, 0) + 1

        return {
            "total_tasks": total_tasks,
            "failed_tasks": failed_count,
            "retried_tasks": retried_count,
            "exception_types": exception_types,
            "oldest_task": tasks[-1].get("failed_at") if tasks else None,
            "newest_task": tasks[0].get("failed_at") if tasks else None,
        }
