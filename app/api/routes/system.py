"""
System Routes — health checks and Celery task introspection.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from redis import Redis
from sqlalchemy import text

from app.api.schemas import HealthResponse, TaskStatusResponse
from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.database import async_session_factory

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


@router.get(
    "/circuit-breakers",
    summary="Get circuit breaker states",
    description="Returns the current state of all external API circuit breakers.",
)
async def get_circuit_breaker_states() -> dict:
    """Get current state of all circuit breakers."""
    from app.core.circuit_breaker import get_circuit_breaker_states

    return get_circuit_breaker_states()


@router.post(
    "/circuit-breakers/{service}/reset",
    summary="Reset circuit breaker",
    description="Manually reset a circuit breaker for a specific service.",
)
async def reset_circuit_breaker(service: str) -> dict:
    """Reset a circuit breaker."""
    from app.core.circuit_breaker import reset_circuit_breaker

    success = reset_circuit_breaker(service)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Circuit breaker for service '{service}' not found.",
        )

    return {
        "service": service,
        "status": "reset",
        "message": f"Circuit breaker for {service} has been reset",
    }


@router.get(
    "/queue-depth",
    summary="Get queue depth",
    description="Returns the current depth of Celery task queues and backpressure status.",
)
async def get_queue_depth() -> dict:
    """Get current queue depth and backpressure status."""
    from app.core.circuit_breaker import QueueBackpressure

    can_accept, current_depth = await QueueBackpressure.can_accept_new_pipeline()

    return {
        "current_depth": current_depth,
        "max_depth": QueueBackpressure.MAX_QUEUE_DEPTH,
        "can_accept_new": can_accept,
        "backpressure_active": not can_accept,
        "utilization_percent": round((current_depth / QueueBackpressure.MAX_QUEUE_DEPTH) * 100, 2),
    }


@router.get(
    "/cache/stats",
    summary="Get cache statistics",
    description="Returns cache usage statistics including memory usage and key counts.",
)
async def get_cache_stats() -> dict:
    """Get cache statistics."""
    from app.services.cache_helpers import get_cache_statistics

    return await get_cache_statistics()


@router.post(
    "/cache/invalidate",
    summary="Invalidate all caches",
    description="Clear all application caches. Use with caution in production.",
)
async def invalidate_caches() -> dict:
    """Invalidate all caches."""
    from app.services.cache_helpers import invalidate_all_caches

    results = await invalidate_all_caches()
    return {"status": "success", "message": "All caches invalidated", "keys_deleted": results}


@router.get(
    "/optimization/media",
    summary="Get media optimization info",
    description="Returns information about media pipeline optimizations (GPU acceleration, parallel processing).",
)
async def get_media_optimization_info() -> dict:
    """Get media optimization information."""
    from app.services.media_optimization import get_optimization_stats

    return get_optimization_stats()
