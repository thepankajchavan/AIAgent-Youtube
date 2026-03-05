"""
Project Routes — list, detail, and delete video projects.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.models.video import VideoProject, VideoStatus
from app.api.schemas import (
    MessageResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectSummary,
    VideoStatusEnum,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List all video projects",
    description="Returns a paginated list of projects, optionally filtered by status.",
)
async def list_projects(
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status_filter: VideoStatusEnum | None = Query(
        default=None,
        alias="status",
        description="Filter by pipeline status",
    ),
    db: AsyncSession = Depends(get_db),
) -> ProjectListResponse:
    # Base query
    base = select(VideoProject).order_by(VideoProject.created_at.desc())
    count_q = select(func.count(VideoProject.id))

    if status_filter is not None:
        db_status = VideoStatus(status_filter.value)
        base = base.where(VideoProject.status == db_status)
        count_q = count_q.where(VideoProject.status == db_status)

    # Total count
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    # Paginated fetch
    offset = (page - 1) * per_page
    query = base.offset(offset).limit(per_page)
    result = await db.execute(query)
    projects = result.scalars().all()

    return ProjectListResponse(
        total=total,
        page=page,
        per_page=per_page,
        projects=[ProjectSummary.model_validate(p) for p in projects],
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get project details",
    description="Returns the full detail of a single video project including artefact paths.",
)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    project = await db.get(VideoProject, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )
    return ProjectResponse.model_validate(project)


@router.delete(
    "/{project_id}",
    response_model=MessageResponse,
    summary="Delete a project",
    description="Permanently deletes a project record. Does NOT revoke Celery tasks or remove media files.",
)
async def delete_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    project = await db.get(VideoProject, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )

    await db.delete(project)
    logger.info("Project deleted — {}", project_id)
    return MessageResponse(message=f"Project {project_id} deleted.")


@router.post(
    "/{project_id}/retry",
    response_model=ProjectResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a failed project",
    description="Resets a FAILED project to PENDING and re-dispatches the pipeline.",
)
async def retry_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    project = await db.get(VideoProject, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found.",
        )

    if project.status != VideoStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only FAILED projects can be retried. Current status: {project.status.value}",
        )

    # Reset state
    project.status = VideoStatus.PENDING
    project.error_message = None
    db.add(project)
    await db.flush()

    # Re-dispatch pipeline
    from app.workers.pipeline import run_pipeline_task

    try:
        celery_result = run_pipeline_task.delay(
            project_id=str(project.id),
            topic=project.topic,
            video_format=project.format.value,
            provider=project.provider,  # USE STORED PROVIDER
            skip_upload=False,  # Default for retry
        )

        project.celery_task_id = celery_result.id
        db.add(project)

        # Explicit commit
        await db.commit()

        logger.info("Project retried — {} new_task={}", project_id, celery_result.id)
        return ProjectResponse.model_validate(project)

    except Exception as exc:
        # Mark as FAILED and commit
        project.status = VideoStatus.FAILED
        project.error_message = f"Retry dispatch failed: {exc}"
        db.add(project)
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to dispatch retry: {exc}",
        )
