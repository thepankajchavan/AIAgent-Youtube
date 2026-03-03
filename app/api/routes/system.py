"""
System Routes — health checks and Celery task introspection.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from redis import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.celery_app import celery_app
from app.core.database import async_session_factory
from app.api.schemas import HealthResponse, TaskStatusResponse

router = APIRouter(prefix="/api/v1/system", tags=["system"])
settings = get_settings()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Deep health check",
    description="Checks connectivity to PostgreSQL and Redis, returns status of each.",
)
async def health_check() -> HealthResponse:
    db_status = "healthy"
    redis_status = "healthy"

    # Check database
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("Health check — database unreachable: {}", exc)
        db_status = f"unhealthy: {exc}"

    # Check Redis
    try:
        r = Redis.from_url(settings.redis_url, socket_connect_timeout=3)
        r.ping()
        r.close()
    except Exception as exc:
        logger.error("Health check — Redis unreachable: {}", exc)
        redis_status = f"unhealthy: {exc}"

    overall = "healthy" if db_status == "healthy" and redis_status == "healthy" else "degraded"

    return HealthResponse(
        status=overall,
        app=settings.app_name,
        database=db_status,
        redis=redis_status,
    )


@router.get(
    "/tasks/{task_id}",
    response_model=TaskStatusResponse,
    summary="Get Celery task status",
    description=(
        "Query the status of a Celery task by its ID. "
        "Returns PENDING, STARTED, SUCCESS, FAILURE, or RETRY."
    ),
)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    result = celery_app.AsyncResult(task_id)

    response = TaskStatusResponse(
        task_id=task_id,
        status=result.status,
        result=None,
    )

    if result.ready():
        try:
            response.result = result.result
        except Exception:
            response.result = str(result.result)
    elif result.status == "FAILURE":
        response.result = str(result.info)

    return response


@router.post(
    "/tasks/{task_id}/revoke",
    status_code=status.HTTP_200_OK,
    summary="Revoke a Celery task",
    description="Attempt to cancel a pending or running Celery task.",
)
async def revoke_task(task_id: str, terminate: bool = False) -> dict:
    try:
        celery_app.control.revoke(task_id, terminate=terminate)
    except Exception as exc:
        logger.error("Failed to revoke task {}: {}", task_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revoke task: {exc}",
        )

    action = "terminated" if terminate else "revoked"
    logger.info("Task {} — {}", task_id, action)
    return {"task_id": task_id, "action": action}
