"""
Script Generation Tasks — Celery tasks that call the LLM service
to produce video scripts and persist results to the database.
"""

from __future__ import annotations

import asyncio
import traceback

from celery import Task
from loguru import logger

from app.core.celery_app import celery_app
from app.core.dlq import DeadLetterQueue
from app.models.video import VideoProject, VideoStatus
from app.services.llm_service import LLMProvider, generate_script
from app.services.search_service import search_topic_context
from app.workers.db import get_sync_db
from app.workers.events import emit_status_update
from app.workers.resume_helper import PipelineResume


def _run_async(coro):
    """Run async coroutine from sync Celery task."""
    return asyncio.run(coro)  # Properly manages event loop lifecycle


def _mark_project_failed(project_id: str, error_message: str) -> None:
    """Commit FAILED status in an independent session (survives outer rollback)."""
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.status = VideoStatus.FAILED
            project.error_message = error_message


@celery_app.task(
    bind=True,
    name="app.workers.script_tasks.generate_script_task",
    queue="scripts",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
    time_limit=300,
    soft_time_limit=270,
)
def generate_script_task(
    self: Task,
    project_id: str,
    topic: str,
    video_format: str = "short",
    provider: str = "openai",
    target_duration: int | None = None,
) -> dict:
    """
    Generate a video script for a project.

    Updates the VideoProject row with:
      - status transitions: PENDING → SCRIPT_GENERATING → (next step or FAILED)
      - script text
      - title, tags, description from the LLM response

    Args:
        project_id: UUID of the VideoProject row.
        topic: Topic string for the LLM.
        video_format: "short" or "long".
        provider: "openai" or "anthropic".
        target_duration: Target video duration in seconds (adjusts word count).

    Returns:
        Dict with script_data and project_id for chaining.
    """
    logger.info(
        "Task start: generate_script — project={} topic='{}' provider={} target_duration={}",
        project_id,
        topic,
        provider,
        target_duration,
    )

    # SINGLE session for entire task
    with get_sync_db() as db:
        try:
            # 1. Load project
            project = db.get(VideoProject, project_id)
            if project is None:
                raise ValueError(f"VideoProject {project_id} not found")

            # 2. Validate and update status
            project.validate_status_transition(VideoStatus.SCRIPT_GENERATING)
            project.status = VideoStatus.SCRIPT_GENERATING
            project.provider = provider
            db.flush()  # Visible to monitoring

            # Emit status update event
            emit_status_update(
                project_id=str(project.id),
                status="SCRIPT_GENERATING",
                telegram_user_id=project.telegram_user_id,
                telegram_chat_id=project.telegram_chat_id,
                telegram_message_id=project.telegram_message_id,
            )

            # 3. Fetch real-time web context (graceful — returns None on failure)
            search_context = _run_async(search_topic_context(topic))
            if search_context:
                logger.info(
                    "Web search context fetched — project={} chars={}",
                    project_id,
                    len(search_context),
                )

            # 4. Generate script with search context
            llm_provider = LLMProvider(provider)
            script_data = _run_async(
                generate_script(
                    topic=topic,
                    video_format=video_format,
                    provider=llm_provider,
                    search_context=search_context,
                    target_duration=target_duration,
                )
            )

            # 5. Persist result
            project.script = script_data["script"]
            # Commit happens automatically on context exit

            # Mark step completed for resume tracking
            PipelineResume.mark_step_completed(project, "script")

            logger.info(
                "Script generated — project={} title='{}'",
                project_id,
                script_data.get("title", ""),
            )

            return {
                "project_id": project_id,
                "script_data": script_data,
                "video_format": video_format,
                "provider": provider,
                "visual_strategy": project.visual_strategy,
                "target_duration": target_duration,
            }

        except Exception as exc:
            logger.error("Script generation failed for project={}: {}", project_id, exc)

            if self.request.retries >= self.max_retries:
                # Final failure — emit FAILED to Telegram
                if project is not None:
                    emit_status_update(
                        project_id=project_id,
                        status="FAILED",
                        telegram_user_id=project.telegram_user_id,
                        telegram_chat_id=project.telegram_chat_id,
                        telegram_message_id=project.telegram_message_id,
                        extra={"error": str(exc)},
                    )
                # Commit FAILED in a SEPARATE session
                # so the rollback of the main session doesn't undo it
                _mark_project_failed(
                    project_id,
                    f"Script generation failed after {self.max_retries + 1} attempts: {exc}",
                )
                try:
                    asyncio.run(DeadLetterQueue.add_failed_task(
                        task_id=self.request.id, task_name=self.name,
                        args=self.request.args, kwargs=self.request.kwargs,
                        exception=exc, traceback_str=traceback.format_exc(),
                        project_id=project_id, update_project_status=False,
                    ))
                except Exception as dlq_exc:
                    logger.error("Failed to add task to DLQ: {}", dlq_exc)
                raise  # Don't retry, just propagate

            # Intermediate retry — notify user that we're retrying
            if project is not None:
                emit_status_update(
                    project_id=project_id,
                    status="SCRIPT_GENERATING",
                    telegram_user_id=project.telegram_user_id,
                    telegram_chat_id=project.telegram_chat_id,
                    telegram_message_id=project.telegram_message_id,
                    extra={"retry": self.request.retries + 1},
                )
            raise self.retry(exc=exc)
