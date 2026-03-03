"""
YouTube Upload Task — final pipeline step.

Takes the assembled video and uploads it to YouTube via the Data API v3.
"""

from __future__ import annotations

from pathlib import Path

from celery import Task
from loguru import logger

from app.core.celery_app import celery_app
from app.models.video import VideoProject, VideoStatus
from app.services.youtube_service import upload_video
from app.workers.db import get_sync_db


@celery_app.task(
    bind=True,
    name="app.workers.upload_tasks.upload_to_youtube_task",
    queue="upload",
    max_retries=2,
    default_retry_delay=120,
    acks_late=True,
    time_limit=900,       # hard kill after 15 min
    soft_time_limit=840,  # raise SoftTimeLimitExceeded at 14 min
)
def upload_to_youtube_task(
    self: Task,
    pipeline_data: dict,
) -> dict:
    """
    Upload the finished video to YouTube.

    Expects pipeline_data with keys:
        project_id, script_data, video_format, output_path.

    Updates VideoProject with youtube_video_id, youtube_url, and COMPLETED status.

    Returns:
        Final pipeline_data with youtube_video_id and youtube_url.
    """
    project_id = pipeline_data["project_id"]
    script_data = pipeline_data["script_data"]
    video_format = pipeline_data["video_format"]
    output_path_str = pipeline_data.get("output_path")

    if not output_path_str:
        _fail_project(project_id, "Upload failed: no output_path in pipeline data")
        raise ValueError("No output_path in pipeline_data")

    output_path = Path(output_path_str)
    if not output_path.exists():
        _fail_project(project_id, f"Upload failed: file not found — {output_path}")
        raise FileNotFoundError(f"Output file missing: {output_path}")

    is_short = video_format == "short"

    logger.info(
        "Task start: upload_to_youtube — project={} title='{}' is_short={}",
        project_id,
        script_data.get("title", ""),
        is_short,
    )

    # Update status
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.status = VideoStatus.UPLOADING
            db.add(project)

    try:
        yt_result = upload_video(
            file_path=output_path,
            title=script_data["title"],
            description=script_data["description"],
            tags=script_data.get("tags", []),
            category="entertainment",
            privacy_status="private",  # safe default — switch to public via API later
            is_short=is_short,
        )
    except Exception as exc:
        logger.error("YouTube upload failed for project={}: {}", project_id, exc)
        _fail_project(project_id, f"YouTube upload failed: {exc}")
        raise self.retry(exc=exc)

    # Persist YouTube data and mark COMPLETED
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.youtube_video_id = yt_result["video_id"]
            project.youtube_url = yt_result["url"]
            project.status = VideoStatus.COMPLETED
            db.add(project)

    logger.info(
        "Upload complete — project={} youtube_url={}",
        project_id,
        yt_result["url"],
    )

    return {
        **pipeline_data,
        "youtube_video_id": yt_result["video_id"],
        "youtube_url": yt_result["url"],
    }


def _fail_project(project_id: str, error_message: str) -> None:
    """Mark a project as FAILED in the database."""
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.status = VideoStatus.FAILED
            project.error_message = error_message
            db.add(project)
