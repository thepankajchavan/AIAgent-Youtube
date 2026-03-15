"""
Pipeline Routes — trigger new video creation pipelines.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    PipelineRequest,
    PipelineResponse,
    VideoStatusEnum,
    VisualStrategyEnum,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.models.video import VideoFormat, VideoProject, VideoStatus
from app.workers.pipeline import run_pipeline_task

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


def _resolve_visual_strategy(request: PipelineRequest) -> str:
    """Resolve visual strategy, enforcing AI_VIDEO_ENABLED / AI_IMAGES_ENABLED gate."""
    settings = get_settings()
    strategy = request.visual_strategy.value

    if strategy == VisualStrategyEnum.AI_IMAGES.value:
        if not settings.ai_images_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="AI image generation is not enabled. Set AI_IMAGES_ENABLED=true to use visual_strategy='ai_images'.",
            )
    elif strategy != VisualStrategyEnum.STOCK_ONLY.value and not settings.ai_video_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"AI video generation is not enabled. "
                f"Set AI_VIDEO_ENABLED=true to use visual_strategy='{strategy}'."
            ),
        )
    return strategy


@router.post(
    "",
    response_model=PipelineResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a new video pipeline",
    description=(
        "Creates a new VideoProject and dispatches the full Celery pipeline: "
        "script generation → TTS + visuals (parallel) → assembly → upload."
    ),
)
async def trigger_pipeline(
    request: PipelineRequest,
    db: AsyncSession = Depends(get_db),
) -> PipelineResponse:
    # Check queue backpressure
    from app.core.circuit_breaker import QueueBackpressure

    can_accept, current_depth = await QueueBackpressure.can_accept_new_pipeline()

    if not can_accept:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"System is currently overloaded. Queue depth: {current_depth} "
                f"(max: {QueueBackpressure.MAX_QUEUE_DEPTH}). Please try again later."
            ),
        )

    # Validate AI video settings
    visual_strategy = _resolve_visual_strategy(request)

    # 1. Create the project row
    project = VideoProject(
        topic=request.topic,
        status=VideoStatus.PENDING,
        format=VideoFormat(request.video_format.value),
        provider=request.provider.value,
        visual_strategy=visual_strategy,
        ai_video_provider=request.ai_video_provider,
        target_duration=request.target_duration,
    )
    db.add(project)
    await db.flush()  # get the generated UUID before commit

    project_id = str(project.id)

    logger.info(
        "Pipeline triggered — project={} topic='{}' format={} provider={} visual_strategy={}",
        project_id,
        request.topic,
        request.video_format.value,
        request.provider.value,
        visual_strategy,
    )

    # 2. Dispatch the Celery pipeline
    try:
        celery_result = run_pipeline_task.delay(
            project_id=project_id,
            topic=request.topic,
            video_format=request.video_format.value,
            provider=request.provider.value,
            skip_upload=request.skip_upload,
            visual_strategy=visual_strategy,
            ai_video_provider=request.ai_video_provider,
            target_duration=request.target_duration,
            language=request.language,
            voice_id=request.voice_id,
        )

        # 3. Store the Celery task ID on the project
        project.celery_task_id = celery_result.id
        db.add(project)

        # EXPLICIT COMMIT before returning
        await db.commit()

        return PipelineResponse(
            project_id=project.id,
            celery_task_id=celery_result.id,
            status=VideoStatusEnum.PENDING,
            message="Pipeline dispatched successfully. Poll /api/v1/projects/{id} for status.",
        )

    except Exception as exc:
        logger.error("Failed to dispatch pipeline: {}", exc)

        # Mark as FAILED and commit (don't lose the record)
        project.status = VideoStatus.FAILED
        project.error_message = f"Celery dispatch failed: {exc}"
        db.add(project)
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to dispatch background task. Is Redis running? Error: {exc}",
        )


@router.post(
    "/batch",
    response_model=list[PipelineResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger multiple pipelines at once",
    description="Accepts a list of pipeline requests and dispatches each one.",
)
async def trigger_batch_pipeline(
    requests: list[PipelineRequest],
    db: AsyncSession = Depends(get_db),
) -> list[PipelineResponse]:
    if len(requests) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch limit is 10 pipelines per request.",
        )

    responses: list[PipelineResponse] = []

    for req in requests:
        # Use nested transaction for partial success
        async with db.begin_nested():
            # Validate AI video settings
            visual_strategy = _resolve_visual_strategy(req)

            project = VideoProject(
                topic=req.topic,
                status=VideoStatus.PENDING,
                format=VideoFormat(req.video_format.value),
                provider=req.provider.value,
                visual_strategy=visual_strategy,
                ai_video_provider=req.ai_video_provider,
                target_duration=req.target_duration,
            )
            db.add(project)
            await db.flush()

            project_id = str(project.id)

            try:
                celery_result = run_pipeline_task.delay(
                    project_id=project_id,
                    topic=req.topic,
                    video_format=req.video_format.value,
                    provider=req.provider.value,
                    skip_upload=req.skip_upload,
                    visual_strategy=visual_strategy,
                    ai_video_provider=req.ai_video_provider,
                    target_duration=req.target_duration,
                    language=req.language,
                    voice_id=req.voice_id,
                )

                project.celery_task_id = celery_result.id
                db.add(project)

                responses.append(
                    PipelineResponse(
                        project_id=project.id,
                        celery_task_id=celery_result.id,
                        status=VideoStatusEnum.PENDING,
                        message="Pipeline dispatched.",
                    )
                )

            except Exception as exc:
                logger.error("Batch dispatch failed for '{}': {}", req.topic, exc)
                # Mark as FAILED but continue with other requests
                project.status = VideoStatus.FAILED
                project.error_message = f"Celery dispatch failed: {exc}"
                db.add(project)

                responses.append(
                    PipelineResponse(
                        project_id=project.id,
                        celery_task_id=None,
                        status=VideoStatusEnum.FAILED,
                        message=f"Failed to dispatch: {exc}",
                    )
                )

    # Commit all changes
    await db.commit()

    logger.info("Batch pipeline triggered — {} projects created", len(responses))
    return responses
