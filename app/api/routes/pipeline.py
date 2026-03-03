"""
Pipeline Routes — trigger new video creation pipelines.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.models.video import VideoProject, VideoStatus, VideoFormat
from app.api.schemas import PipelineRequest, PipelineResponse, VideoStatusEnum
from app.workers.pipeline import run_pipeline_task

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


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
    # 1. Create the project row
    project = VideoProject(
        topic=request.topic,
        status=VideoStatus.PENDING,
        format=VideoFormat(request.video_format.value),
    )
    db.add(project)
    await db.flush()  # get the generated UUID before commit

    project_id = str(project.id)

    logger.info(
        "Pipeline triggered — project={} topic='{}' format={} provider={}",
        project_id,
        request.topic,
        request.video_format.value,
        request.provider.value,
    )

    # 2. Dispatch the Celery pipeline
    try:
        celery_result = run_pipeline_task.delay(
            project_id=project_id,
            topic=request.topic,
            video_format=request.video_format.value,
            provider=request.provider.value,
            skip_upload=request.skip_upload,
        )
    except Exception as exc:
        logger.error("Failed to dispatch pipeline: {}", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to dispatch background task. Is Redis running? Error: {exc}",
        )

    # 3. Store the Celery task ID on the project
    project.celery_task_id = celery_result.id
    db.add(project)

    return PipelineResponse(
        project_id=project.id,
        celery_task_id=celery_result.id,
        status=VideoStatusEnum.PENDING,
        message="Pipeline dispatched successfully. Poll /api/v1/projects/{id} for status.",
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
        project = VideoProject(
            topic=req.topic,
            status=VideoStatus.PENDING,
            format=VideoFormat(req.video_format.value),
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
            )
        except Exception as exc:
            logger.error("Batch dispatch failed for '{}': {}", req.topic, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to dispatch task for topic '{req.topic}': {exc}",
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

    logger.info("Batch pipeline triggered — {} projects created", len(responses))
    return responses
