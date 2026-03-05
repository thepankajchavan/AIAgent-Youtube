"""
Script Generation Tasks — Celery tasks that call the LLM service
to produce video scripts and persist results to the database.
"""

from __future__ import annotations

import asyncio

from celery import Task
from loguru import logger

from app.core.celery_app import celery_app
from app.models.video import VideoProject, VideoStatus
from app.services.llm_service import LLMProvider, generate_script
from app.workers.db import get_sync_db
from app.workers.events import emit_status_update


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
)
def generate_script_task(
    self: Task,
    project_id: str,
    topic: str,
    video_format: str = "short",
    provider: str = "openai",
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

    Returns:
        Dict with script_data and project_id for chaining.
    """
    logger.info(
        "Task start: generate_script — project={} topic='{}' provider={}",
        project_id,
        topic,
        provider,
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

            # 3. Generate script
            llm_provider = LLMProvider(provider)
            script_data = _run_async(
                generate_script(topic=topic, video_format=video_format, provider=llm_provider)
            )

            # 4. Persist result
            project.script = script_data["script"]
            # Commit happens automatically on context exit

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
            }

        except Exception as exc:
            logger.error("Script generation failed for project={}: {}", project_id, exc)

            # Emit failure event (best-effort, before retry/raise)
            # Guard: project may be None if db.get() failed
            if project is not None:
                emit_status_update(
                    project_id=project_id,
                    status="FAILED",
                    telegram_user_id=project.telegram_user_id,
                    telegram_chat_id=project.telegram_chat_id,
                    telegram_message_id=project.telegram_message_id,
                    extra={"error": str(exc)},
                )

            if self.request.retries >= self.max_retries:
                # Final failure — commit FAILED in a SEPARATE session
                # so the rollback of the main session doesn't undo it
                _mark_project_failed(
                    project_id,
                    f"Script generation failed after {self.max_retries + 1} attempts: {exc}",
                )
                raise  # Don't retry, just propagate
            raise self.retry(exc=exc)
