"""
Pipeline Orchestrator — chains the full video creation workflow using Celery canvas.

Pipeline flow:
    1. generate_script_task            (scripts queue)
    2. [generate_audio_task,           (media queue — parallel via chord)
        fetch_visuals_task]
    3. assemble_video_task             (media queue — chord callback)
    4. upload_to_youtube_task          (upload queue)

The orchestrator uses Celery primitives:
    chain → sequential steps
    chord → parallel step (audio + visuals) with a callback (assembly)
"""

from __future__ import annotations

from celery import chain, chord, group, signature
from loguru import logger

from app.core.celery_app import celery_app
from app.workers.script_tasks import generate_script_task
from app.workers.media_tasks import generate_audio_task, fetch_visuals_task
from app.workers.assembly_tasks import assemble_video_task
from app.workers.upload_tasks import upload_to_youtube_task


def build_pipeline(
    project_id: str,
    topic: str,
    video_format: str = "short",
    provider: str = "openai",
    skip_upload: bool = False,
) -> chain:
    """
    Build the full Celery pipeline for a video project.

    Args:
        project_id: UUID of the VideoProject row.
        topic: Topic string for script generation.
        video_format: "short" or "long".
        provider: "openai" or "anthropic".
        skip_upload: If True, stop after assembly (useful for testing).

    Returns:
        A Celery chain that can be .apply_async()'d.
    """
    logger.info(
        "Building pipeline — project={} topic='{}' format={} provider={} skip_upload={}",
        project_id,
        topic,
        video_format,
        provider,
        skip_upload,
    )

    # Step 1: Script generation
    step_script = generate_script_task.s(
        project_id=project_id,
        topic=topic,
        video_format=video_format,
        provider=provider,
    )

    # Step 2: Parallel audio + visual generation (chord)
    # The chord takes the result of step 1 and fans it out to both tasks,
    # then collects both results into the callback (step 3).
    parallel_media = chord(
        group(
            generate_audio_task.s(),
            fetch_visuals_task.s(),
        ),
        assemble_video_task.s(),  # Step 3: Assembly (chord callback)
    )

    if skip_upload:
        return chain(step_script, parallel_media)

    # Step 4: YouTube upload
    step_upload = upload_to_youtube_task.s()

    return chain(step_script, parallel_media, step_upload)


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
    )

    result = pipeline.apply_async()
    logger.info("Pipeline dispatched — project={} chain_id={}", project_id, result.id)
    return result.id
