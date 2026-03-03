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


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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

    # Mark as SCRIPT_GENERATING
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project is None:
            raise ValueError(f"VideoProject {project_id} not found")
        project.status = VideoStatus.SCRIPT_GENERATING
        db.add(project)

    try:
        llm_provider = LLMProvider(provider)
        script_data = _run_async(
            generate_script(topic=topic, video_format=video_format, provider=llm_provider)
        )
    except Exception as exc:
        logger.error("Script generation failed for project={}: {}", project_id, exc)

        with get_sync_db() as db:
            project = db.get(VideoProject, project_id)
            if project:
                project.status = VideoStatus.FAILED
                project.error_message = f"Script generation failed: {exc}"
                db.add(project)

        raise self.retry(exc=exc)

    # Persist script to DB
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.script = script_data["script"]
            db.add(project)

    logger.info(
        "Script generated — project={} title='{}'",
        project_id,
        script_data.get("title", ""),
    )

    return {
        "project_id": project_id,
        "script_data": script_data,
        "video_format": video_format,
    }
