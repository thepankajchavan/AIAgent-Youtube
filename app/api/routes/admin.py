"""
Admin Routes — API key management endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.api_key import APIKey
from app.models.video import VideoProject, VideoStatus

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# ── Schemas ──────────────────────────────────────────────────


class CreateAPIKeyRequest(BaseModel):
    """Request to create a new API key."""

    name: str = Field(..., min_length=1, max_length=255, description="Descriptive name for the key")
    rate_limit: int = Field(default=100, ge=1, le=10000, description="Requests per hour limit")


class CreateAPIKeyResponse(BaseModel):
    """Response after creating an API key."""

    id: uuid.UUID
    key: str = Field(..., description="API key - save this, it won't be shown again!")
    name: str
    rate_limit: int
    is_active: bool
    created_at: datetime


class APIKeyResponse(BaseModel):
    """API key details (without the actual key value)."""

    id: uuid.UUID
    name: str
    is_active: bool
    rate_limit: int
    requests_this_hour: int
    rate_limit_reset_at: datetime
    total_requests: int
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class APIKeyListResponse(BaseModel):
    """Paginated list of API keys."""

    keys: list[APIKeyResponse]
    total: int
    page: int
    per_page: int
    pages: int


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


# ── Endpoints ────────────────────────────────────────────────


@router.post(
    "/keys",
    response_model=CreateAPIKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new API key",
    description="Generate a new API key with specified rate limit. Returns the key value - save it securely!",
)
async def create_api_key(
    request: CreateAPIKeyRequest,
    db: AsyncSession = Depends(get_db),
) -> CreateAPIKeyResponse:
    """Create a new API key."""

    # Generate unique API key
    key_value = APIKey.generate_key()

    # Create database record
    api_key = APIKey(
        key=key_value,
        name=request.name,
        rate_limit=request.rate_limit,
        is_active=True,
    )

    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info(f"Created new API key: {api_key.name} (ID: {api_key.id})")

    return CreateAPIKeyResponse(
        id=api_key.id,
        key=key_value,  # Only time we expose the actual key
        name=api_key.name,
        rate_limit=api_key.rate_limit,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
    )


@router.get(
    "/keys",
    response_model=APIKeyListResponse,
    summary="List all API keys",
    description="Returns a paginated list of API keys (without key values).",
)
async def list_api_keys(
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
    active_only: bool = Query(default=False, description="Only show active keys"),
    db: AsyncSession = Depends(get_db),
) -> APIKeyListResponse:
    """List all API keys."""

    # Base query
    base = select(APIKey).order_by(APIKey.created_at.desc())
    count_q = select(func.count(APIKey.id))

    if active_only:
        base = base.where(APIKey.is_active)
        count_q = count_q.where(APIKey.is_active)

    # Get total count
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    # Paginate
    offset = (page - 1) * per_page
    query = base.limit(per_page).offset(offset)

    result = await db.execute(query)
    keys = result.scalars().all()

    return APIKeyListResponse(
        keys=[
            APIKeyResponse(
                id=key.id,
                name=key.name,
                is_active=key.is_active,
                rate_limit=key.rate_limit,
                requests_this_hour=key.requests_this_hour,
                rate_limit_reset_at=key.rate_limit_reset_at,
                total_requests=key.total_requests,
                last_used_at=key.last_used_at,
                created_at=key.created_at,
                updated_at=key.updated_at,
            )
            for key in keys
        ],
        total=total,
        page=page,
        per_page=per_page,
        pages=(total + per_page - 1) // per_page if total > 0 else 0,
    )


@router.get(
    "/keys/{key_id}",
    response_model=APIKeyResponse,
    summary="Get API key details",
    description="Returns detailed information about a specific API key (without key value).",
)
async def get_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIKeyResponse:
    """Get details of a specific API key."""

    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"API key with ID {key_id} not found."
        )

    return APIKeyResponse(
        id=api_key.id,
        name=api_key.name,
        is_active=api_key.is_active,
        rate_limit=api_key.rate_limit,
        requests_this_hour=api_key.requests_this_hour,
        rate_limit_reset_at=api_key.rate_limit_reset_at,
        total_requests=api_key.total_requests,
        last_used_at=api_key.last_used_at,
        created_at=api_key.created_at,
        updated_at=api_key.updated_at,
    )


@router.patch(
    "/keys/{key_id}/revoke",
    response_model=MessageResponse,
    summary="Revoke an API key",
    description="Deactivate an API key. It can be reactivated later if needed.",
)
async def revoke_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Revoke (deactivate) an API key."""

    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"API key with ID {key_id} not found."
        )

    if not api_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="API key is already inactive."
        )

    api_key.is_active = False
    await db.commit()

    logger.info(f"Revoked API key: {api_key.name} (ID: {api_key.id})")

    return MessageResponse(message=f"API key '{api_key.name}' has been revoked.")


@router.patch(
    "/keys/{key_id}/activate",
    response_model=MessageResponse,
    summary="Activate an API key",
    description="Reactivate a previously revoked API key.",
)
async def activate_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Activate a previously revoked API key."""

    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"API key with ID {key_id} not found."
        )

    if api_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="API key is already active."
        )

    api_key.is_active = True
    await db.commit()

    logger.info(f"Activated API key: {api_key.name} (ID: {api_key.id})")

    return MessageResponse(message=f"API key '{api_key.name}' has been activated.")


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete an API key",
    description="Permanently delete an API key. This action cannot be undone.",
)
async def delete_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete an API key."""

    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"API key with ID {key_id} not found."
        )

    logger.warning(f"Deleting API key: {api_key.name} (ID: {api_key.id})")

    await db.delete(api_key)
    await db.commit()


# ── Dead Letter Queue (DLQ) Endpoints ────────────────────────


class DLQTaskResponse(BaseModel):
    """DLQ task details."""

    task_id: str
    task_name: str
    project_id: str | None
    exception_type: str
    exception_message: str
    failed_at: str
    retry_count: int
    status: str


class DLQListResponse(BaseModel):
    """List of DLQ tasks."""

    tasks: list[DLQTaskResponse]
    total: int


class DLQStatsResponse(BaseModel):
    """DLQ statistics."""

    total_tasks: int
    failed_tasks: int
    retried_tasks: int
    exception_types: dict[str, int]
    oldest_task: str | None
    newest_task: str | None


@router.get(
    "/dlq/tasks",
    response_model=DLQListResponse,
    summary="List all DLQ tasks",
    description="Returns all permanently failed tasks in the Dead Letter Queue.",
)
async def list_dlq_tasks(
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum tasks to retrieve"),
) -> DLQListResponse:
    """List all tasks in the DLQ."""
    from app.core.dlq import DeadLetterQueue

    tasks = await DeadLetterQueue.get_all_tasks(limit=limit)

    return DLQListResponse(
        tasks=[
            DLQTaskResponse(
                task_id=task["task_id"],
                task_name=task["task_name"],
                project_id=(
                    task["project_id"]
                    if task.get("project_id") and task["project_id"] != "None"
                    else None
                ),
                exception_type=task["exception_type"],
                exception_message=task["exception_message"],
                failed_at=task["failed_at"],
                retry_count=int(task.get("retry_count", 0)),
                status=task["status"],
            )
            for task in tasks
        ],
        total=len(tasks),
    )


@router.get(
    "/dlq/tasks/{task_id}",
    response_model=dict,
    summary="Get DLQ task details",
    description="Returns detailed information about a specific task in the DLQ, including full traceback.",
)
async def get_dlq_task(task_id: str) -> dict:
    """Get details of a specific DLQ task."""
    from app.core.dlq import DeadLetterQueue

    task = await DeadLetterQueue.get_task(task_id)

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Task {task_id} not found in DLQ."
        )

    return task


@router.get(
    "/dlq/stats",
    response_model=DLQStatsResponse,
    summary="Get DLQ statistics",
    description="Returns statistics about the Dead Letter Queue.",
)
async def get_dlq_stats() -> DLQStatsResponse:
    """Get DLQ statistics."""
    from app.core.dlq import DeadLetterQueue

    stats = await DeadLetterQueue.get_dlq_stats()

    return DLQStatsResponse(**stats)


@router.post(
    "/dlq/tasks/{task_id}/retry",
    response_model=MessageResponse,
    summary="Retry a DLQ task",
    description="Retry a failed task from the DLQ by triggering the pipeline again.",
)
async def retry_dlq_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Retry a task from the DLQ."""
    from app.core.dlq import DeadLetterQueue

    # Get task from DLQ
    task = await DeadLetterQueue.get_task(task_id)

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Task {task_id} not found in DLQ."
        )

    project_id = task.get("project_id")
    if not project_id or project_id == "None":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task does not have an associated project ID. Cannot retry.",
        )

    # Get project from database
    result = await db.execute(select(VideoProject).where(VideoProject.id == project_id))
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Project {project_id} not found."
        )

    # Reset project to PENDING
    project.status = VideoStatus.PENDING
    project.error_message = None
    await db.commit()

    # Mark task as retried in DLQ
    await DeadLetterQueue.mark_retried(task_id)

    # Trigger new pipeline
    from app.workers.pipeline_tasks import run_pipeline

    run_pipeline.delay(project_id=project_id)

    logger.info(f"Retrying DLQ task {task_id} for project {project_id}")

    return MessageResponse(
        message=f"Task {task_id} retried. New pipeline started for project {project_id}."
    )


@router.delete(
    "/dlq/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Remove a DLQ task",
    description="Remove a task from the DLQ after manual resolution.",
)
async def remove_dlq_task(task_id: str) -> None:
    """Remove a task from the DLQ."""
    from app.core.dlq import DeadLetterQueue

    removed = await DeadLetterQueue.remove_task(task_id)

    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Task {task_id} not found in DLQ."
        )

    logger.info(f"Removed task {task_id} from DLQ")
