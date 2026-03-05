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

    is_short = video_format == "short"

    logger.info(
        "Task start: upload_to_youtube — project={} title='{}' is_short={}",
        project_id,
        script_data.get("title", ""),
        is_short,
    )

    # SINGLE session for entire task
    with get_sync_db() as db:
        try:
            # 1. Load project
            project = db.get(VideoProject, project_id)
            if project is None:
                raise ValueError(f"VideoProject {project_id} not found")

            # 2. Validate inputs
            if not output_path_str:
                raise ValueError("No output_path in pipeline_data")

            output_path = Path(output_path_str)
            if not output_path.exists():
                raise FileNotFoundError(f"Output file missing: {output_path}")

            # 3. Validate and update status
            project.validate_status_transition(VideoStatus.UPLOADING)
            project.status = VideoStatus.UPLOADING
            db.flush()  # Visible to monitoring

            # Emit status update event
            emit_status_update(
                project_id=str(project.id),
                status="UPLOADING",
                telegram_user_id=project.telegram_user_id,
                telegram_chat_id=project.telegram_chat_id,
                telegram_message_id=project.telegram_message_id,
            )

            # 4. Upload to YouTube
            yt_result = upload_video(
                file_path=output_path,
                title=script_data["title"],
                description=script_data["description"],
                tags=script_data.get("tags", []),
                category="entertainment",
                privacy_status="private",  # safe default — switch to public via API later
                is_short=is_short,
            )

            # 5. Persist result and mark COMPLETED
            project.youtube_video_id = yt_result["video_id"]
            project.youtube_url = yt_result["url"]
            project.status = VideoStatus.COMPLETED
            db.flush()

            # Emit completion event with YouTube URL
            emit_status_update(
                project_id=str(project.id),
                status="COMPLETED",
                telegram_user_id=project.telegram_user_id,
                telegram_chat_id=project.telegram_chat_id,
                telegram_message_id=project.telegram_message_id,
                extra={"youtube_url": yt_result["url"]},
            )

            # Commit happens automatically on context exit

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

        except Exception as exc:
            logger.error("YouTube upload failed for project={}: {}", project_id, exc)

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
                _mark_project_failed(project_id, f"YouTube upload failed after {self.max_retries + 1} attempts: {exc}")
                raise
            raise self.retry(exc=exc)
