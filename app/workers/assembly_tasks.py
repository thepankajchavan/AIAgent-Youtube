"""
Video Assembly Task — takes audio + video clips and renders the final MP4.

This task runs after the audio and visual tasks complete (via a chord callback).
It receives results from both parallel tasks and calls the media service.
"""

from __future__ import annotations

from pathlib import Path

from celery import Task
from loguru import logger

from app.core.celery_app import celery_app
from app.models.video import VideoProject, VideoStatus
from app.services.media_service import assemble_video
from app.workers.db import get_sync_db


@celery_app.task(
    bind=True,
    name="app.workers.assembly_tasks.assemble_video_task",
    queue="media",
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
    time_limit=600,       # hard kill after 10 min
    soft_time_limit=540,  # raise SoftTimeLimitExceeded at 9 min
)
def assemble_video_task(
    self: Task,
    parallel_results: list[dict],
) -> dict:
    """
    Assemble the final video from audio + visual clips.

    Called as a chord callback — receives a list of results from the
    parallel audio and visual tasks.

    parallel_results is a list of two dicts (from generate_audio_task
    and fetch_visuals_task). Each contains the full pipeline_data plus
    their respective artefact paths.

    Returns:
        pipeline_data with output_path added.
    """
    # Merge results from both parallel tasks
    merged: dict = {}
    for result in parallel_results:
        merged.update(result)

    project_id = merged["project_id"]
    video_format = merged["video_format"]
    audio_path_str = merged.get("audio_path")
    clip_paths_str = merged.get("clip_paths", [])

    logger.info(
        "Task start: assemble_video — project={} audio={} clips={}",
        project_id,
        audio_path_str,
        len(clip_paths_str),
    )

    if not audio_path_str:
        _fail_project(project_id, "Assembly failed: no audio path in results")
        raise ValueError("No audio_path in parallel results")

    if not clip_paths_str:
        _fail_project(project_id, "Assembly failed: no video clips in results")
        raise ValueError("No clip_paths in parallel results")

    # Update status
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.status = VideoStatus.ASSEMBLING
            db.add(project)

    try:
        output_path = assemble_video(
            clip_paths=[Path(p) for p in clip_paths_str],
            audio_path=Path(audio_path_str),
            video_format=video_format,
            project_id=project_id,
        )
    except Exception as exc:
        logger.error("Assembly failed for project={}: {}", project_id, exc)
        _fail_project(project_id, f"Video assembly failed: {exc}")
        raise self.retry(exc=exc)

    # Persist output path
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.output_path = str(output_path)
            db.add(project)

    logger.info("Assembly complete — project={} output={}", project_id, output_path)

    return {
        **merged,
        "output_path": str(output_path),
    }


def _fail_project(project_id: str, error_message: str) -> None:
    """Mark a project as FAILED in the database."""
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.status = VideoStatus.FAILED
            project.error_message = error_message
            db.add(project)
