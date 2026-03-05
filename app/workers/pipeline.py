"""
Pipeline Orchestrator — chains the full video creation workflow using Celery canvas.

Pipeline flow (stock_only — default, unchanged):
    1. generate_script_task            (scripts queue)
    2. [generate_audio_task,           (media queue — parallel via chord)
        fetch_visuals_task]
    3. assemble_video_task             (media queue — chord callback)
    4. upload_to_youtube_task          (upload queue)

Pipeline flow (hybrid / ai_only — new):
    1. generate_script_task            (scripts queue)
    2. split_scenes_task               (scripts queue — LLM scene planning)
    3. [generate_audio_task,           (media queue — parallel via chord)
        generate_visuals_task]         (media queue — hybrid AI + stock)
    4. assemble_video_task             (media queue — chord callback)
    5. upload_to_youtube_task          (upload queue)

The orchestrator uses Celery primitives:
    chain → sequential steps
    chord → parallel step (audio + visuals) with a callback (assembly)
"""

from __future__ import annotations

from celery import chain, chord, group
from loguru import logger

from app.core.celery_app import celery_app
from app.workers.assembly_tasks import assemble_video_task
from app.workers.media_tasks import fetch_visuals_task, generate_audio_task
from app.workers.script_tasks import generate_script_task
from app.workers.upload_tasks import upload_to_youtube_task


def build_pipeline(
    project_id: str,
    topic: str,
    video_format: str = "short",
    provider: str = "openai",
    skip_upload: bool = False,
    visual_strategy: str = "stock_only",
    ai_video_provider: str | None = None,
) -> chain:
    """
    Build the full Celery pipeline for a video project.

    Args:
        project_id: UUID of the VideoProject row.
        topic: Topic string for script generation.
        video_format: "short" or "long".
        provider: "openai" or "anthropic".
        skip_upload: If True, stop after assembly (useful for testing).
        visual_strategy: "stock_only", "ai_only", or "hybrid".
        ai_video_provider: Override for AI provider (uses config default if None).

    Returns:
        A Celery chain that can be .apply_async()'d.
    """
    logger.info(
        "Building pipeline — project={} topic='{}' format={} provider={} "
        "skip_upload={} visual_strategy={}",
        project_id,
        topic,
        video_format,
        provider,
        skip_upload,
        visual_strategy,
    )

    # Step 1: Script generation (always first)
    step_script = generate_script_task.s(
        project_id=project_id,
        topic=topic,
        video_format=video_format,
        provider=provider,
    )

    if visual_strategy == "stock_only":
        # ── ORIGINAL PATH — no scene splitting ──────────────
        parallel_media = chord(
            group(
                generate_audio_task.s(),
                fetch_visuals_task.s(),
            ),
            assemble_video_task.s(),
        )
        steps = [step_script, parallel_media]
    else:
        # ── AI VIDEO PATH — scene splitting + hybrid visuals ─
        from app.workers.scene_tasks import (
            generate_visuals_task,
            split_scenes_task,
        )

        step_scene_split = split_scenes_task.s()
        parallel_media = chord(
            group(
                generate_audio_task.s(),
                generate_visuals_task.s(),
            ),
            assemble_video_task.s(),
        )
        steps = [step_script, step_scene_split, parallel_media]

    if not skip_upload:
        step_upload = upload_to_youtube_task.s()
        steps.append(step_upload)

    return chain(*steps)


@celery_app.task(
    name="app.workers.pipeline.run_pipeline_task",
    queue="default",
)
def run_pipeline_task(
    project_id: str,
    topic: str,
    video_format: str = "short",
    provider: str = "openai",
    skip_upload: bool = False,
    visual_strategy: str = "stock_only",
    ai_video_provider: str | None = None,
) -> str:
    """
    Entry-point task that builds and dispatches the full pipeline.

    This is the task you call from the FastAPI endpoint.
    It returns immediately after dispatching the chain.
    """
    pipeline = build_pipeline(
        project_id=project_id,
        topic=topic,
        video_format=video_format,
        provider=provider,
        skip_upload=skip_upload,
        visual_strategy=visual_strategy,
        ai_video_provider=ai_video_provider,
    )

    result = pipeline.apply_async()
    logger.info("Pipeline dispatched — project={} chain_id={}", project_id, result.id)
    return result.id
