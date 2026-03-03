"""
Media Generation Tasks — Celery tasks for TTS audio and stock video fetching.

These two tasks are designed to run in parallel via a Celery group,
then feed their results into the assembly step.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from celery import Task
from loguru import logger

from app.core.celery_app import celery_app
from app.models.video import VideoProject, VideoStatus
from app.services.tts_service import generate_speech
from app.services.visual_service import fetch_clips
from app.workers.db import get_sync_db


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── TTS Audio Task ───────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="app.workers.media_tasks.generate_audio_task",
    queue="media",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def generate_audio_task(
    self: Task,
    pipeline_data: dict,
) -> dict:
    """
    Convert the script text to speech via ElevenLabs.

    Expects pipeline_data with keys: project_id, script_data, video_format.
    Updates VideoProject.audio_path in the database.

    Returns:
        Updated pipeline_data with audio_path added.
    """
    project_id = pipeline_data["project_id"]
    script_text = pipeline_data["script_data"]["script"]
    video_format = pipeline_data["video_format"]

    logger.info(
        "Task start: generate_audio — project={} script_len={}",
        project_id,
        len(script_text),
    )

    # Update status
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.status = VideoStatus.AUDIO_GENERATING
            db.add(project)

    try:
        audio_path: Path = _run_async(
            generate_speech(
                text=script_text,
                output_filename=f"tts_{project_id}.mp3",
            )
        )
    except Exception as exc:
        logger.error("TTS failed for project={}: {}", project_id, exc)

        with get_sync_db() as db:
            project = db.get(VideoProject, project_id)
            if project:
                project.status = VideoStatus.FAILED
                project.error_message = f"TTS generation failed: {exc}"
                db.add(project)

        raise self.retry(exc=exc)

    # Persist path
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.audio_path = str(audio_path)
            db.add(project)

    logger.info("Audio generated — project={} path={}", project_id, audio_path)

    return {
        **pipeline_data,
        "audio_path": str(audio_path),
    }


# ── Stock Video Fetch Task ───────────────────────────────────

@celery_app.task(
    bind=True,
    name="app.workers.media_tasks.fetch_visuals_task",
    queue="media",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def fetch_visuals_task(
    self: Task,
    pipeline_data: dict,
) -> dict:
    """
    Search and download stock B-roll clips from Pexels.

    Uses tags from the LLM script_data to build search queries.
    Downloads multiple clips, returns their paths.

    Returns:
        Updated pipeline_data with clip_paths added.
    """
    project_id = pipeline_data["project_id"]
    script_data = pipeline_data["script_data"]
    video_format = pipeline_data["video_format"]

    # Use tags as search queries; fall back to topic keywords
    tags = script_data.get("tags", [])
    queries = tags[:4] if tags else [script_data.get("title", "nature")]

    orientation = "portrait" if video_format == "short" else "landscape"

    logger.info(
        "Task start: fetch_visuals — project={} queries={} orientation={}",
        project_id,
        queries,
        orientation,
    )

    # Update status
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.status = VideoStatus.VIDEO_GENERATING
            db.add(project)

    try:
        clip_paths: list[Path] = _run_async(
            fetch_clips(
                queries=queries,
                orientation=orientation,
                clips_per_query=2,
            )
        )
    except Exception as exc:
        logger.error("Visual fetch failed for project={}: {}", project_id, exc)

        with get_sync_db() as db:
            project = db.get(VideoProject, project_id)
            if project:
                project.status = VideoStatus.FAILED
                project.error_message = f"Visual fetch failed: {exc}"
                db.add(project)

        raise self.retry(exc=exc)

    clip_paths_str = [str(p) for p in clip_paths]

    # Store first clip path as reference
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project and clip_paths_str:
            project.video_path = clip_paths_str[0]
            db.add(project)

    logger.info(
        "Visuals fetched — project={} clips={}",
        project_id,
        len(clip_paths_str),
    )

    return {
        **pipeline_data,
        "clip_paths": clip_paths_str,
    }
