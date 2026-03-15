"""
Scene Tasks — Celery tasks for LLM scene splitting and hybrid visual generation.

These tasks extend the pipeline with AI video support:
  - split_scenes_task  (scripts queue) — LLM-based scene planning
  - generate_visuals_task (media queue) — Hybrid AI + stock visual generation

When visual_strategy == "stock_only", these tasks are NOT called;
the pipeline uses the original fetch_visuals_task instead.
"""

from __future__ import annotations

import asyncio
import traceback
from dataclasses import asdict
from pathlib import Path

from celery import Task
from loguru import logger

from app.core.celery_app import celery_app
from app.core.dlq import DeadLetterQueue
from app.models.video import VideoProject, VideoStatus
from app.services.ai_video_service import (
    Scene,
    generate_all_visuals,
    split_script_to_scenes,
)
from app.workers.db import get_sync_db
from app.workers.events import emit_status_update
from app.workers.resume_helper import PipelineResume


def _run_async(coro):
    """Run async coroutine from sync Celery task."""
    return asyncio.run(coro)


def _mark_project_failed(project_id: str, error_message: str) -> None:
    """Commit FAILED status in an independent session (survives outer rollback)."""
    with get_sync_db() as db:
        project = db.get(VideoProject, project_id)
        if project:
            project.status = VideoStatus.FAILED
            project.error_message = error_message


# ── Scene Splitting Task ─────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.workers.scene_tasks.split_scenes_task",
    queue="scripts",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
    time_limit=120,
    soft_time_limit=90,
)
def split_scenes_task(
    self: Task,
    pipeline_data: dict,
) -> dict:
    """
    Split a script into visual scenes using LLM.

    Inserted into the pipeline between generate_script_task and
    the parallel media chord (audio + visuals).

    Expects pipeline_data from generate_script_task:
        project_id, script_data, video_format

    Returns:
        Updated pipeline_data with scene_plan added.
    """
    project_id = pipeline_data["project_id"]
    script_data = pipeline_data["script_data"]
    video_format = pipeline_data["video_format"]
    audio_duration = pipeline_data.get("audio_duration")

    logger.info(
        "Task start: split_scenes — project={} script_len={} audio_duration={}",
        project_id,
        len(script_data.get("script", "")),
        f"{audio_duration:.1f}s" if audio_duration else "N/A",
    )

    with get_sync_db() as db:
        project = None
        try:
            project = db.get(VideoProject, project_id)
            if project is None:
                raise ValueError(f"VideoProject {project_id} not found")

            # Validate and update status
            project.validate_status_transition(VideoStatus.SCENE_SPLITTING)
            project.status = VideoStatus.SCENE_SPLITTING
            db.flush()

            emit_status_update(
                project_id=str(project.id),
                status="SCENE_SPLITTING",
                telegram_user_id=project.telegram_user_id,
                telegram_chat_id=project.telegram_chat_id,
                telegram_message_id=project.telegram_message_id,
            )

            # Extract visual direction hints from script scenes
            visual_hints = [
                s.get("visual_hint", s.get("narration", ""))
                for s in script_data.get("scenes", [])
            ]

            # Call LLM for scene splitting (with audio_duration for exact sync)
            scenes: list[Scene] = _run_async(
                split_script_to_scenes(
                    script=script_data["script"],
                    video_format=video_format,
                    provider=project.provider,
                    visual_strategy=project.visual_strategy,
                    audio_duration=audio_duration,
                    visual_hints=visual_hints or None,
                )
            )

            # Validate total scene duration
            total_scene_dur = sum(s.duration_seconds for s in scenes)
            if audio_duration and audio_duration > 0:
                drift = abs(total_scene_dur - audio_duration) / audio_duration
                logger.info(
                    "Scene duration check — scenes={:.1f}s audio={:.1f}s "
                    "(drift={:.0%}) project={}",
                    total_scene_dur,
                    audio_duration,
                    drift,
                    project_id,
                )
            else:
                word_count = len(script_data["script"].split())
                estimated_read_time = (word_count / 150) * 60
                if estimated_read_time > 0:
                    drift = abs(total_scene_dur - estimated_read_time) / estimated_read_time
                    logger.info(
                        "Scene duration check — scenes={:.1f}s reading={:.1f}s "
                        "({} words, drift={:.0%}) project={}",
                        total_scene_dur,
                        estimated_read_time,
                        word_count,
                        drift,
                        project_id,
                    )

            # Persist scene plan to DB
            scene_dicts = [asdict(s) for s in scenes]
            project.scene_plan = {"scenes": scene_dicts}
            # Commit happens automatically on context exit

            logger.info(
                "Scenes split — project={} total={} ai={} stock={} duration={:.1f}s",
                project_id,
                len(scenes),
                sum(1 for s in scenes if s.visual_type == "ai_generated"),
                sum(1 for s in scenes if s.visual_type == "stock_footage"),
                total_scene_dur,
            )

            return {
                **pipeline_data,
                "scene_plan": scene_dicts,
            }

        except Exception as exc:
            logger.error("Scene splitting failed for project={}: {}", project_id, exc)

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
                    f"Scene splitting failed after {self.max_retries + 1} attempts: {exc}",
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
                    status="SCENE_SPLITTING",
                    telegram_user_id=project.telegram_user_id,
                    telegram_chat_id=project.telegram_chat_id,
                    telegram_message_id=project.telegram_message_id,
                    extra={"retry": self.request.retries + 1},
                )
            raise self.retry(exc=exc)


# ── Hybrid Visual Generation Task ────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.workers.scene_tasks.generate_visuals_task",
    queue="media",
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
    time_limit=900,  # 15 min hard limit (AI generation can be slow)
    soft_time_limit=840,  # 14 min soft limit
)
def generate_visuals_task(
    self: Task,
    pipeline_data: dict,
) -> dict:
    """
    Generate visuals for all scenes using the AI + stock hybrid approach.

    This task replaces fetch_visuals_task when visual_strategy != "stock_only".
    Each scene is routed to either an AI provider or Pexels based on the
    scene plan from split_scenes_task.

    Returns the same dict shape as fetch_visuals_task so that
    assemble_video_task needs NO changes:
        {..., "clip_paths": [str, str, ...]}
    """
    project_id = pipeline_data["project_id"]
    scene_dicts = pipeline_data.get("scene_plan", [])
    video_format = pipeline_data["video_format"]

    logger.info(
        "Task start: generate_visuals — project={} scenes={}",
        project_id,
        len(scene_dicts),
    )

    if not scene_dicts:
        raise ValueError(f"No scene_plan found for project {project_id}")

    with get_sync_db() as db:
        project = None
        try:
            project = db.get(VideoProject, project_id)
            if project is None:
                raise ValueError(f"VideoProject {project_id} not found")

            # Validate and update status
            project.validate_status_transition(VideoStatus.VIDEO_GENERATING)
            project.status = VideoStatus.VIDEO_GENERATING
            db.flush()

            emit_status_update(
                project_id=str(project.id),
                status="VIDEO_GENERATING",
                telegram_user_id=project.telegram_user_id,
                telegram_chat_id=project.telegram_chat_id,
                telegram_message_id=project.telegram_message_id,
            )

            # Reconstruct Scene objects from dicts
            scenes = [Scene(**sd) for sd in scene_dicts]

            # Generate all visuals (AI + stock with fallback)
            clip_paths: list[Path] = _run_async(
                generate_all_visuals(
                    scenes=scenes,
                    video_format=video_format,
                    project_id=project_id,
                )
            )

            # Calculate total cost
            total_cost = sum(s.generation_cost for s in scenes)
            project.ai_video_cost = total_cost

            clip_paths_str = [str(p) for p in clip_paths]
            if clip_paths_str:
                project.video_path = clip_paths_str[0]

            # Update scene plan with generation results (paths, costs, providers)
            project.scene_plan = {"scenes": [asdict(s) for s in scenes]}

            # Mark step completed for resume tracking
            PipelineResume.mark_step_completed(project, "video")
            # Commit happens automatically on context exit

            logger.info(
                "Visuals generated — project={} clips={} ai_cost=${:.2f}",
                project_id,
                len(clip_paths_str),
                total_cost,
            )

            return {
                **pipeline_data,
                "clip_paths": clip_paths_str,
            }

        except Exception as exc:
            logger.error("Visual generation failed for project={}: {}", project_id, exc)

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
                    f"Visual generation failed after {self.max_retries + 1} attempts: {exc}",
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
