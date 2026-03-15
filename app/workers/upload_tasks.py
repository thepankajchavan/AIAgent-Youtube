"""
YouTube Upload Task — final pipeline step.

Takes the assembled video and uploads it to YouTube via the Data API v3.
"""

from __future__ import annotations

import asyncio
import traceback
from pathlib import Path

from celery import Task
from loguru import logger

from app.core.celery_app import celery_app
from app.core.dlq import DeadLetterQueue
from app.core.config import get_settings
from app.models.video import VideoProject, VideoStatus
from app.services.youtube_service import set_thumbnail, upload_video
from app.workers.db import get_sync_db
from app.workers.events import emit_status_update
from app.workers.resume_helper import PipelineResume

settings = get_settings()


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
    time_limit=900,  # hard kill after 15 min
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

            # 3b. Persist YouTube metadata to project (for analytics)
            project.youtube_title = script_data.get("title", "")[:200]
            project.youtube_description = script_data.get("description", "")
            project.youtube_tags = script_data.get("tags", [])
            project.youtube_hashtags = script_data.get("hashtags", [])
            project.youtube_category = script_data.get("category", settings.youtube_default_category)
            db.flush()

            # 4. Upload to YouTube (with progress events at 25% milestones)
            last_milestone = [0]  # mutable for closure

            def _progress_callback(progress: float):
                milestone = int(progress * 4) * 25  # 25, 50, 75, 100
                if milestone > last_milestone[0]:
                    last_milestone[0] = milestone
                    emit_status_update(
                        project_id=str(project.id),
                        status="UPLOADING",
                        telegram_user_id=project.telegram_user_id,
                        telegram_chat_id=project.telegram_chat_id,
                        telegram_message_id=project.telegram_message_id,
                        extra={"progress": milestone},
                    )

            yt_result = upload_video(
                file_path=output_path,
                title=script_data["title"],
                description=script_data["description"],
                tags=script_data.get("tags", []),
                hashtags=script_data.get("hashtags", []),
                category=script_data.get("category", settings.youtube_default_category),
                privacy_status=settings.youtube_default_privacy,
                is_short=is_short,
                progress_callback=_progress_callback,
            )

            # 4b. Set thumbnail if available
            thumbnail_path = pipeline_data.get("thumbnail_path")
            if thumbnail_path and yt_result.get("video_id"):
                set_thumbnail(yt_result["video_id"], thumbnail_path)

            # 5. Persist result and mark COMPLETED
            project.youtube_video_id = yt_result["video_id"]
            project.youtube_url = yt_result["url"]
            project.status = VideoStatus.COMPLETED
            db.flush()

            # Mark step completed for resume tracking
            PipelineResume.mark_step_completed(project, "upload")

            # Emit completion event with YouTube URL and output path for video preview
            emit_status_update(
                project_id=str(project.id),
                status="COMPLETED",
                telegram_user_id=project.telegram_user_id,
                telegram_chat_id=project.telegram_chat_id,
                telegram_message_id=project.telegram_message_id,
                extra={
                    "youtube_url": yt_result["url"],
                    "output_path": str(output_path),
                },
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

            # Auth errors are permanent — skip retries to avoid wasting minutes
            is_auth_error = (
                "OAuth token expired" in str(exc)
                or "RefreshError" in type(exc).__name__
            )

            if is_auth_error or self.request.retries >= self.max_retries:
                if is_auth_error:
                    logger.error(
                        "YouTube auth error (permanent) — skipping retries. "
                        "Run: python scripts/refresh_youtube_token.py"
                    )
                if project is not None:
                    emit_status_update(
                        project_id=project_id,
                        status="FAILED",
                        telegram_user_id=project.telegram_user_id,
                        telegram_chat_id=project.telegram_chat_id,
                        telegram_message_id=project.telegram_message_id,
                        extra={"error": str(exc)},
                    )
                _mark_project_failed(
                    project_id,
                    f"YouTube upload failed: {exc}",
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
                raise

            if project is not None:
                emit_status_update(
                    project_id=project_id,
                    status="UPLOADING",
                    telegram_user_id=project.telegram_user_id,
                    telegram_chat_id=project.telegram_chat_id,
                    telegram_message_id=project.telegram_message_id,
                    extra={"retry": self.request.retries + 1},
                )
            raise self.retry(exc=exc)
