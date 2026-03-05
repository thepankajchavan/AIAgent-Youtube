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
from app.services.media_service import assemble_video, generate_thumbnail
from app.workers.db import get_sync_db
from app.workers.events import emit_status_update


def _mark_project_failed(project_id: str, error_message: str) -> None:
    """Commit FAILED status in an independent session (survives outer rollback)."""
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.status = VideoStatus.FAILED
            project.error_message = error_message


@celery_app.task(
    bind=True,
    name="app.workers.assembly_tasks.assemble_video_task",
    queue="media",
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
    time_limit=600,  # hard kill after 10 min
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
    # Merge results from both parallel tasks — explicit key extraction
    merged: dict = {}
    for result in parallel_results:
        for key in ("project_id", "script_data", "video_format"):
            if key in result and key not in merged:
                merged[key] = result[key]
        if "audio_path" in result:
            merged["audio_path"] = result["audio_path"]
        if "clip_paths" in result:
            merged["clip_paths"] = result["clip_paths"]

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

    # SINGLE session for entire task
    with get_sync_db() as db:
        try:
            # 1. Load project
            project = db.get(VideoProject, project_id)
            if project is None:
                raise ValueError(f"VideoProject {project_id} not found")

            # 2. Validate inputs
            if not audio_path_str:
                raise ValueError("No audio_path in parallel results")

            if not clip_paths_str:
                raise ValueError("No clip_paths in parallel results")

            # 3. Validate and update status
            project.validate_status_transition(VideoStatus.ASSEMBLING)
            project.status = VideoStatus.ASSEMBLING
            db.flush()  # Visible to monitoring

            # Emit status update event
            emit_status_update(
                project_id=str(project.id),
                status="ASSEMBLING",
                telegram_user_id=project.telegram_user_id,
                telegram_chat_id=project.telegram_chat_id,
                telegram_message_id=project.telegram_message_id,
            )

            # 4. Assemble video
            output_path = assemble_video(
                clip_paths=[Path(p) for p in clip_paths_str],
                audio_path=Path(audio_path_str),
                video_format=video_format,
                project_id=project_id,
            )

            # 5. Generate thumbnail from middle of video
            try:
                thumbnail_path = generate_thumbnail(
                    video_path=output_path, timestamp=-1  # Extract from middle
                )
                project.thumbnail_path = str(thumbnail_path)
                logger.info(
                    "Thumbnail generated — project={} thumbnail={}", project_id, thumbnail_path
                )
            except Exception as thumb_exc:
                # Don't fail the entire pipeline if thumbnail generation fails
                logger.warning(
                    "Thumbnail generation failed for project={}: {}", project_id, thumb_exc
                )
                project.thumbnail_path = None

            # 6. Persist results
            project.output_path = str(output_path)
            # Commit happens automatically on context exit

            logger.info("Assembly complete — project={} output={}", project_id, output_path)

            return {
                **merged,
                "output_path": str(output_path),
                "thumbnail_path": str(thumbnail_path) if project.thumbnail_path else None,
            }

        except Exception as exc:
            logger.error("Assembly failed for project={}: {}", project_id, exc)

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
                _mark_project_failed(
                    project_id,
                    f"Video assembly failed after {self.max_retries + 1} attempts: {exc}",
                )
                raise
            raise self.retry(exc=exc)
