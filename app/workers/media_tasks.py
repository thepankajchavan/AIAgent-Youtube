"""
Media Generation Tasks — Celery tasks for TTS audio and stock video fetching.

These two tasks are designed to run in parallel via a Celery group,
then feed their results into the assembly step.
"""

from __future__ import annotations

import asyncio
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path

from celery import Task
from loguru import logger

from app.core.celery_app import celery_app
from app.core.dlq import DeadLetterQueue
from app.models.video import VideoProject, VideoStatus
from app.services.ai_video_service import generate_all_visuals, split_script_to_scenes
from app.services.media_service import probe_duration
from app.services.tts_service import generate_speech
from app.services.visual_service import fetch_clips  # Pexels (stock footage) - fallback only
from app.workers.db import get_sync_db
from app.workers.events import emit_status_update
from app.workers.resume_helper import PipelineResume


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


# ── TTS Audio Task ───────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.workers.media_tasks.generate_audio_task",
    queue="media",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
    time_limit=300,
    soft_time_limit=270,
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
    pipeline_data["video_format"]

    logger.info(
        "Task start: generate_audio — project={} script_len={}",
        project_id,
        len(script_text),
    )

    # SINGLE session for entire task
    with get_sync_db() as db:
        project = None
        try:
            # 1. Load project
            project = db.get(VideoProject, project_id)
            if project is None:
                raise ValueError(f"VideoProject {project_id} not found")

            # 2. Validate and update status
            project.validate_status_transition(VideoStatus.AUDIO_GENERATING)
            project.status = VideoStatus.AUDIO_GENERATING
            db.flush()  # Visible to monitoring

            # Emit status update event
            emit_status_update(
                project_id=str(project.id),
                status="AUDIO_GENERATING",
                telegram_user_id=project.telegram_user_id,
                telegram_chat_id=project.telegram_chat_id,
                telegram_message_id=project.telegram_message_id,
            )

            # 3. Generate audio (with unique filename to avoid collision on retry)
            from app.core.config import get_settings as _get_settings
            _settings = _get_settings()
            _mood = pipeline_data.get("script_data", {}).get("mood", "uplifting")

            # Resolve voice_id (multi-voice selection)
            _voice_id = None
            if getattr(_settings, "multi_voice_enabled", False):
                try:
                    from app.services.voice_selection_service import select_voice
                    from app.services.llm_service import _detect_niche
                    _niche = _detect_niche(pipeline_data.get("script_data", {}).get("title", ""))
                    _user_voice = pipeline_data.get("voice_id")
                    _voice_id = select_voice(niche=_niche, mood=_mood, user_voice_id=_user_voice)
                    project.voice_id = _voice_id
                    logger.info("Multi-voice selected — niche={} mood={} voice={}", _niche, _mood, _voice_id)
                except Exception as voice_exc:
                    logger.warning("Multi-voice selection failed: {}", voice_exc)

            # Per-beat TTS: split script into beats with varying expressiveness
            if getattr(_settings, "per_beat_tts_enabled", False) and getattr(
                _settings, "voice_profile_enabled", True
            ):
                from app.services.beat_tts_service import generate_speech_per_beat
                _scenes = pipeline_data.get("script_data", {}).get("scenes")
                audio_path: Path = _run_async(
                    generate_speech_per_beat(
                        script_text=script_text,
                        mood=_mood,
                        scenes=_scenes,
                        voice_id=_voice_id,
                    )
                )
                logger.info("Per-beat TTS generated — mood={} voice={}", _mood, _voice_id)

            else:
                # Standard TTS with optional mood-based voice profile
                _tts_kwargs: dict = {
                    "text": script_text,
                    "output_filename": f"tts_{project_id}_{uuid.uuid4().hex[:8]}.mp3",
                }
                if _voice_id:
                    _tts_kwargs["voice_id"] = _voice_id

                if getattr(_settings, "voice_profile_enabled", True):
                    from app.services.voice_profile_service import get_voice_profile_for_mood
                    _profile = get_voice_profile_for_mood(_mood)
                    _tts_kwargs.update({
                        "stability": _profile.stability,
                        "similarity_boost": _profile.similarity_boost,
                        "style": _profile.style,
                    })
                    logger.info(
                        "Voice profile applied — mood={} stability={} style={}",
                        _mood, _profile.stability, _profile.style,
                    )

                audio_path: Path = _run_async(
                    generate_speech(**_tts_kwargs)
                )

            # 4. Probe audio duration for downstream sync checks
            audio_duration = probe_duration(audio_path)
            logger.info(
                "Audio generated — project={} path={} duration={:.1f}s chars={}",
                project_id,
                audio_path,
                audio_duration,
                len(script_text),
            )

            # 5. Persist result
            project.audio_path = str(audio_path)

            # Mark step completed for resume tracking
            PipelineResume.mark_step_completed(project, "audio")
            PipelineResume.mark_artifact_available(project, "audio", audio_path)
            # Commit happens automatically on context exit

            return {
                **pipeline_data,
                "audio_path": str(audio_path),
                "audio_duration": audio_duration,
            }

        except Exception as exc:
            logger.error("TTS failed for project={}: {}", project_id, exc)

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
                    f"TTS generation failed after {self.max_retries + 1} attempts: {exc}",
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
                    status="AUDIO_GENERATING",
                    telegram_user_id=project.telegram_user_id,
                    telegram_chat_id=project.telegram_chat_id,
                    telegram_message_id=project.telegram_message_id,
                    extra={"retry": self.request.retries + 1},
                )
            raise self.retry(exc=exc)


# ── Stock Video Fetch Task ───────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.workers.media_tasks.fetch_visuals_task",
    queue="media",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
    time_limit=600,
    soft_time_limit=540,
)
def fetch_visuals_task(
    self: Task,
    pipeline_data: dict,
) -> dict:
    """
    Generate visual clips using AI video generation or fetch stock footage.

    AI Video Mode (AI_VIDEO_ENABLED=true):
      - Splits script into scenes using LLM
      - Generates custom AI videos for each scene
      - Falls back to stock footage if budget exceeded or AI fails

    Stock Footage Mode (AI_VIDEO_ENABLED=false):
      - Uses tags from script_data to search Pexels
      - Downloads stock video clips

    Returns:
        Updated pipeline_data with clip_paths added.
    """
    from app.core.config import get_settings

    settings = get_settings()

    project_id = pipeline_data["project_id"]
    script_data = pipeline_data["script_data"]
    video_format = pipeline_data["video_format"]
    provider = pipeline_data.get("provider", "openai")

    logger.info(
        "Task start: fetch_visuals — project={} format={} ai_enabled={}",
        project_id,
        video_format,
        settings.ai_video_enabled,
    )

    # SINGLE session for entire task
    with get_sync_db() as db:
        project = None
        try:
            # 1. Load project
            project = db.get(VideoProject, project_id)
            if project is None:
                raise ValueError(f"VideoProject {project_id} not found")

            # 2. Validate and update status
            project.validate_status_transition(VideoStatus.VIDEO_GENERATING)
            project.status = VideoStatus.VIDEO_GENERATING
            db.flush()  # Visible to monitoring

            # Emit status update event
            emit_status_update(
                project_id=str(project.id),
                status="VIDEO_GENERATING",
                telegram_user_id=project.telegram_user_id,
                telegram_chat_id=project.telegram_chat_id,
                telegram_message_id=project.telegram_message_id,
            )

            # 3. Generate or fetch visual clips
            # Use project's visual_strategy (not global setting) to decide mode.
            # This task is only called in the stock_only pipeline path;
            # the AI path uses scene_tasks.generate_visuals_task instead.
            use_ai = project.visual_strategy != "stock_only" and settings.ai_video_enabled
            if use_ai:
                # ═══ AI VIDEO GENERATION MODE ═══
                logger.info("Using AI video generation (strategy={})", settings.ai_video_strategy)

                # Split script into scenes using LLM
                full_script = script_data.get("script", "")
                scenes = _run_async(
                    split_script_to_scenes(
                        script=full_script,
                        video_format=video_format,
                        provider=provider,
                        visual_strategy=project.visual_strategy,
                    )
                )

                logger.info("Script split into {} scenes", len(scenes))

                # Generate visuals for all scenes (parallel with fallback)
                clip_paths: list[Path] = _run_async(
                    generate_all_visuals(
                        scenes=scenes,
                        video_format=video_format,
                        project_id=project_id,
                        max_concurrent=3,
                    )
                )

                # Log cost breakdown
                total_cost = sum(s.generation_cost for s in scenes)
                ai_count = sum(
                    1 for s in scenes if s.provider_used in ["runway", "stability", "kling"]
                )
                stock_count = sum(1 for s in scenes if s.provider_used == "pexels")

                # Persist cost and scene plan to DB
                project.ai_video_cost = total_cost
                project.scene_plan = {"scenes": [asdict(s) for s in scenes]}

                logger.info(
                    "Visuals generated — project={} clips={} (AI:{}, stock:{}, cost:${:.2f})",
                    project_id,
                    len(clip_paths),
                    ai_count,
                    stock_count,
                    total_cost,
                )

            else:
                # ═══ STOCK FOOTAGE MODE (PEXELS) ═══
                logger.info("Using stock footage from Pexels")

                orientation = "portrait" if video_format == "short" else "landscape"

                # Use per-scene search keywords for precise stock footage matching
                scenes = script_data.get("scenes", [])
                if scenes:
                    queries = []
                    for scene in scenes:
                        keywords = scene.get("search_keywords", [])
                        if keywords:
                            queries.append(keywords[0])  # Primary keyword per scene
                    clips_per_q = 1  # 1 clip per scene = 4-5 clips total
                else:
                    # Fallback to tags (legacy script format)
                    tags = script_data.get("tags", [])
                    queries = tags[:4] if tags else [script_data.get("title", "nature")]
                    clips_per_q = 2

                if not queries:
                    queries = [script_data.get("title", "nature")]

                logger.info(
                    "Pexels search — queries={} orientation={} clips_per_q={}",
                    queries,
                    orientation,
                    clips_per_q,
                )

                clip_paths: list[Path] = _run_async(
                    fetch_clips(
                        queries=queries,
                        orientation=orientation,
                        clips_per_query=clips_per_q,
                    )
                )

                logger.info(
                    "Stock footage fetched — project={} clips={}",
                    project_id,
                    len(clip_paths),
                )

            clip_paths_str = [str(p) for p in clip_paths]

            # 4. Persist result (store first clip path as reference)
            if clip_paths_str:
                project.video_path = clip_paths_str[0]

            # Mark step completed for resume tracking
            PipelineResume.mark_step_completed(project, "video")
            # Commit happens automatically on context exit

            logger.info(
                "Visuals fetched — project={} clips={}",
                project_id,
                len(clip_paths_str),
            )

            return {
                **pipeline_data,
                "clip_paths": clip_paths_str,
            }

        except Exception as exc:
            logger.error("Visual fetch failed for project={}: {}", project_id, exc)

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
                    project_id, f"Visual fetch failed after {self.max_retries + 1} attempts: {exc}"
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
                    status="VIDEO_GENERATING",
                    telegram_user_id=project.telegram_user_id,
                    telegram_chat_id=project.telegram_chat_id,
                    telegram_message_id=project.telegram_message_id,
                    extra={"retry": self.request.retries + 1},
                )
            raise self.retry(exc=exc)
