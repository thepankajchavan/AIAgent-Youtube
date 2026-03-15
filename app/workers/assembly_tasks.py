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
        project = None
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
            settings = get_settings()

            # Mood-as-creative-glue: let mood drive caption/transition style
            script_data = merged.get("script_data") or {}
            mood_glue_caption = None
            mood_glue_transition = None
            if getattr(settings, "mood_creative_glue_enabled", False):
                try:
                    from app.services.scene_director_service import (
                        mood_to_caption_style,
                        mood_to_transition_style,
                    )
                    _mood = script_data.get("mood", settings.bgm_default_mood)
                    mood_glue_caption = mood_to_caption_style(_mood)
                    mood_glue_transition = mood_to_transition_style(_mood)
                    logger.info(
                        "Mood glue active — mood={} caption={} transition={}",
                        _mood, mood_glue_caption, mood_glue_transition,
                    )
                except Exception as glue_exc:
                    logger.warning("Mood glue failed: {}", glue_exc)

            caption_ass_path = None
            if settings.captions_enabled and audio_path_str:
                try:
                    caption_style = mood_glue_caption or getattr(settings, "captions_style", "classic")
                    caption_ass_path = asyncio.run(
                        generate_captions(
                            audio_path=Path(audio_path_str),
                            style=caption_style,
                        )
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

            # 5b. Compute transitions from config (with mood glue override)
            transitions = None
            transition_durations = None
            if getattr(settings, "transitions_enabled", True):
                from app.services.transition_service import compute_transitions_for_clips
                _style_override = mood_glue_transition  # None if mood glue disabled
                transitions, transition_durations = compute_transitions_for_clips(
                    len(clip_paths_str),
                    style_override=_style_override,
                )

            # 5c. Fetch background music (optional — graceful degradation)
            bgm_path = None
            if getattr(settings, "bgm_enabled", False):
                try:
                    from app.services.music_service import fetch_bgm_for_mood
                    mood = script_data.get("mood", settings.bgm_default_mood)
                    bgm_path = asyncio.run(
                        fetch_bgm_for_mood(mood, audio_duration or 30.0)
                    )
                    if bgm_path:
                        logger.info("BGM fetched for mood='{}' → {}", mood, bgm_path)
                except Exception as bgm_exc:
                    logger.warning(
                        "BGM fetch failed — proceeding without music: {}",
                        bgm_exc,
                    )
                    bgm_path = None

            # 5d. Apply pacing (speed effects) per scene
            if getattr(settings, "pacing_enabled", False):
                try:
                    from app.services.pacing_service import compute_scene_pacing, apply_speed_effect
                    _pace_mood = script_data.get("mood", "uplifting")
                    _pace_style = getattr(settings, "pacing_style", "auto")
                    speeds = compute_scene_pacing(
                        num_scenes=len(clip_paths_str),
                        mood=_pace_mood,
                        pacing_style=_pace_style,
                    )
                    _paced_clips = []
                    for idx, (clip_str, speed) in enumerate(zip(clip_paths_str, speeds)):
                        if abs(speed - 1.0) > 0.01:
                            clip_p = Path(clip_str)
                            paced_p = clip_p.with_name(f"{clip_p.stem}_paced{clip_p.suffix}")
                            apply_speed_effect(clip_p, paced_p, speed)
                            _paced_clips.append(str(paced_p))
                        else:
                            _paced_clips.append(clip_str)
                    clip_paths_str = _paced_clips
                    logger.info("Pacing applied — speeds={}", speeds)
                except Exception as pace_exc:
                    logger.warning("Pacing failed — proceeding without: {}", pace_exc)

            # 6. Assemble video
            #    Extract per-scene durations so clips are trimmed/looped to match audio
            scene_plan = merged.get("scene_plan") or []
            scene_durations: list[float] | None = None
            if scene_plan:
                scene_durations = [
                    s["duration_seconds"] for s in scene_plan if "duration_seconds" in s
                ]
                if len(scene_durations) != len(clip_paths_str):
                    logger.warning(
                        "scene_durations count ({}) != clip count ({}) — skipping duration matching",
                        len(scene_durations), len(clip_paths_str),
                    )
                    scene_durations = None

            _assembly_mood = script_data.get("mood") if script_data else None
            output_path = assemble_video(
                clip_paths=[Path(p) for p in clip_paths_str],
                audio_path=Path(audio_path_str),
                video_format=video_format,
                project_id=project_id,
                caption_ass_path=caption_ass_path,
                scene_durations=scene_durations,
                transitions=transitions,
                transition_durations=transition_durations,
                bgm_path=bgm_path,
                bgm_volume_db=getattr(settings, "bgm_volume_db", -18.0),
                tts_volume_db=getattr(settings, "tts_volume_db", -3.0),
                bgm_fade_in=getattr(settings, "bgm_fade_in_duration", 1.0),
                bgm_fade_out=getattr(settings, "bgm_fade_out_duration", 2.0),
                bgm_ducking_enabled=getattr(settings, "bgm_ducking_enabled", True),
                mood=_assembly_mood,
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
                expected_duration = audio_duration

                post_mismatch = abs(final_duration - expected_duration) / expected_duration
                if post_mismatch > 0.10:
                    logger.warning(
                        "Post-assembly drift {:.0%}: final={:.1f}s vs expected={:.1f}s "
                        "(audio={:.1f}s) — project={}",
                        post_mismatch,
                        final_duration,
                        expected_duration,
                        audio_duration,
                        project_id,
                    )
                else:
                    logger.info(
                        "Post-assembly OK — final={:.1f}s expected={:.1f}s (audio={:.1f}s)",
                        final_duration,
                        expected_duration,
                        audio_duration,
                    )

            # 7. Generate thumbnail
            thumbnail_path = None
            _use_ai_thumb = getattr(settings, "ai_thumbnail_enabled", False)
            if _use_ai_thumb:
                try:
                    from app.services.thumbnail_service import generate_ai_thumbnail
                    _title = script_data.get("title", "")
                    _topic = script_data.get("topic", _title)
                    _thumb_mood = script_data.get("mood", "uplifting")
                    thumbnail_path = asyncio.run(
                        generate_ai_thumbnail(
                            title=_title,
                            topic=_topic,
                            mood=_thumb_mood,
                            project_id=project_id,
                        )
                    )
                    project.thumbnail_path = str(thumbnail_path)
                    logger.info(
                        "AI thumbnail generated — project={} thumbnail={}",
                        project_id, thumbnail_path,
                    )
                except Exception as ai_thumb_exc:
                    logger.warning(
                        "AI thumbnail failed, falling back to frame extraction: {}",
                        ai_thumb_exc,
                    )
                    _use_ai_thumb = False  # Fall through to frame extraction

            if not _use_ai_thumb:
                try:
                    thumbnail_path = generate_thumbnail(
                        video_path=output_path, timestamp=-1
                    )
                    project.thumbnail_path = str(thumbnail_path)
                    logger.info(
                        "Thumbnail generated — project={} thumbnail={}",
                        project_id, thumbnail_path,
                    )
                except Exception as thumb_exc:
                    logger.warning(
                        "Thumbnail generation failed for project={}: {}",
                        project_id, thumb_exc,
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
