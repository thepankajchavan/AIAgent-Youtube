"""
Video Assembly Task — takes audio + video clips and renders the final MP4.

Supports two input modes:
  - Chord callback (stock_only path): receives list[dict] from parallel tasks
  - Sequential chain (ai_only path): receives a single dict with all keys
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
from app.services.caption_service import generate_captions
from app.services.media_service import assemble_video, generate_thumbnail, probe_duration
from app.workers.db import get_sync_db
from app.workers.events import emit_status_update
from app.workers.resume_helper import PipelineResume


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
    pipeline_input,
) -> dict:
    """
    Assemble the final video from audio + visual clips.

    Accepts two input formats:
      - dict: Sequential chain (ai_only path) — single dict with all keys
      - list[dict]: Chord callback (stock_only path) — merges parallel results

    Returns:
        pipeline_data with output_path added.
    """
    # Handle both sequential (dict) and chord callback (list[dict]) inputs
    if isinstance(pipeline_input, dict):
        # Sequential AI path — pipeline_data already has all keys
        merged = pipeline_input
    elif isinstance(pipeline_input, list):
        # Chord callback — merge results from parallel tasks
        merged = {}
        for result in pipeline_input:
            for key in ("project_id", "script_data", "video_format"):
                if key in result and key not in merged:
                    merged[key] = result[key]
            if "audio_path" in result:
                merged["audio_path"] = result["audio_path"]
            if "audio_duration" in result:
                merged["audio_duration"] = result["audio_duration"]
            if "clip_paths" in result:
                merged["clip_paths"] = result["clip_paths"]
    else:
        raise TypeError(f"Unexpected pipeline_input type: {type(pipeline_input)}")

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

            # 4. Pre-flight: probe clips + audio, warn if mismatch >20%
            audio_duration = merged.get("audio_duration")
            if audio_duration is None:
                audio_duration = probe_duration(Path(audio_path_str))
            total_clip_duration = sum(
                probe_duration(Path(p)) for p in clip_paths_str
            )
            if audio_duration > 0:
                mismatch = abs(total_clip_duration - audio_duration) / audio_duration
                if mismatch > 0.20:
                    logger.warning(
                        "Pre-flight duration mismatch {:.0%}: clips={:.1f}s vs audio={:.1f}s "
                        "— project={}",
                        mismatch,
                        total_clip_duration,
                        audio_duration,
                        project_id,
                    )
                else:
                    logger.info(
                        "Pre-flight OK — clips={:.1f}s audio={:.1f}s (mismatch={:.0%})",
                        total_clip_duration,
                        audio_duration,
                        mismatch,
                    )

            # 5. Generate captions (optional — graceful degradation)
            caption_ass_path = None
            if get_settings().captions_enabled and audio_path_str:
                try:
                    caption_ass_path = asyncio.run(
                        generate_captions(audio_path=Path(audio_path_str))
                    )
                except Exception as caption_exc:
                    logger.warning(
                        "Caption generation failed: {} — proceeding without captions",
                        caption_exc,
                    )
                    caption_ass_path = None
                    # Notify Telegram about caption failure
                    emit_status_update(
                        project_id=str(project.id),
                        status="ASSEMBLING",
                        telegram_user_id=project.telegram_user_id,
                        telegram_chat_id=project.telegram_chat_id,
                        telegram_message_id=project.telegram_message_id,
                        extra={"captions": "failed"},
                    )

            # 6. Assemble video
            output_path = assemble_video(
                clip_paths=[Path(p) for p in clip_paths_str],
                audio_path=Path(audio_path_str),
                video_format=video_format,
                project_id=project_id,
                caption_ass_path=caption_ass_path,
            )

            # 7. Post-assembly: validate final video
            final_duration = probe_duration(output_path)
            file_size = output_path.stat().st_size
            if final_duration < 1.0:
                raise ValueError(
                    f"Final video too short ({final_duration:.1f}s) — likely corrupted"
                )
            if file_size < 10_000:
                raise ValueError(
                    f"Final video too small ({file_size} bytes) — likely corrupted"
                )

            if audio_duration and audio_duration > 0:
                post_mismatch = abs(final_duration - audio_duration) / audio_duration
                if post_mismatch > 0.10:
                    logger.warning(
                        "Post-assembly drift {:.0%}: final={:.1f}s vs audio={:.1f}s — project={}",
                        post_mismatch,
                        final_duration,
                        audio_duration,
                        project_id,
                    )
                else:
                    logger.info(
                        "Post-assembly OK — final={:.1f}s audio={:.1f}s",
                        final_duration,
                        audio_duration,
                    )

            # 7. Generate thumbnail from middle of video
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

            # 8. Persist results
            project.output_path = str(output_path)

            # Mark step completed for resume tracking
            PipelineResume.mark_step_completed(project, "assembly")
            PipelineResume.mark_artifact_available(project, "output", output_path)
            # Commit happens automatically on context exit

            logger.info("Assembly complete — project={} output={}", project_id, output_path)

            return {
                **merged,
                "output_path": str(output_path),
                "thumbnail_path": str(thumbnail_path) if project.thumbnail_path else None,
            }

        except Exception as exc:
            logger.error("Assembly failed for project={}: {}", project_id, exc)

            if self.request.retries >= self.max_retries:
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
                    f"Video assembly failed after {self.max_retries + 1} attempts: {exc}",
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
                    status="ASSEMBLING",
                    telegram_user_id=project.telegram_user_id,
                    telegram_chat_id=project.telegram_chat_id,
                    telegram_message_id=project.telegram_message_id,
                    extra={"retry": self.request.retries + 1},
                )
            raise self.retry(exc=exc)
