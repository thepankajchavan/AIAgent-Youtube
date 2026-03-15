"""
Schedule API Routes — dashboard, queue management, toggle, audit, and blacklist.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel

from app.services.auto_schedule_service import SchedulingBrain

router = APIRouter(prefix="/api/v1/schedule", tags=["schedule"])


class ToggleRequest(BaseModel):
    enabled: bool


class BlacklistRequest(BaseModel):
    keyword: str
    list_type: str = "blacklist"


@router.get("/stats")
async def get_schedule_stats():
    """Dashboard summary: enabled, counts, queue depth, health."""
    brain = SchedulingBrain()
    stats = await brain.get_stats()
    return stats


@router.get("/queue")
async def get_schedule_queue(limit: int = Query(20, ge=1, le=100)):
    """Pending queue entries with scheduled times."""
    brain = SchedulingBrain()
    return await brain.get_queue(limit=limit)


@router.post("/queue/{queue_id}/cancel")
async def cancel_schedule_queue_entry(queue_id: str):
    """Cancel a pending queue entry."""
    brain = SchedulingBrain()
    cancelled = await brain.cancel_queued(queue_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Queue entry not found or not pending")
    return {"status": "cancelled", "queue_id": queue_id}


@router.get("/history")
async def get_schedule_history(limit: int = Query(50, ge=1, le=200)):
    """Past dispatched/completed queue entries."""
    brain = SchedulingBrain()
    return await brain.get_history(limit=limit)


@router.post("/toggle")
async def toggle_autopilot(body: ToggleRequest):
    """Toggle autopilot on/off via Redis. Takes effect immediately."""
    brain = SchedulingBrain()
    await brain.set_enabled(body.enabled)
    await brain.log_decision(
        action="toggle_changed",
        topic=None,
        reason=f"Autopilot {'enabled' if body.enabled else 'disabled'} via API",
    )
    return {"enabled": body.enabled}


@router.get("/audit")
async def get_audit_log(limit: int = Query(100, ge=1, le=500)):
    """Scheduling audit log entries."""
    import json

    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.models.analytics import ScheduleAuditLog

    async with async_session_factory() as session:
        q = (
            select(ScheduleAuditLog)
            .order_by(ScheduleAuditLog.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(q)
        entries = result.scalars().all()

    return [
        {
            "id": str(e.id),
            "action": e.action,
            "topic": e.topic,
            "reason": e.reason,
            "details": json.loads(e.details) if e.details else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


@router.get("/blacklist")
async def get_blacklist():
    """List all blacklisted/whitelisted keywords."""
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.models.analytics import TopicBlacklist

    async with async_session_factory() as session:
        q = select(TopicBlacklist).order_by(TopicBlacklist.created_at.desc())
        result = await session.execute(q)
        entries = result.scalars().all()

    return [
        {
            "id": str(e.id),
            "keyword": e.keyword,
            "list_type": e.list_type,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


@router.post("/blacklist")
async def add_to_blacklist(body: BlacklistRequest):
    """Add a keyword to blacklist or whitelist."""
    import uuid

    from sqlalchemy.exc import IntegrityError

    from app.core.database import async_session_factory
    from app.models.analytics import TopicBlacklist

    if body.list_type not in ("blacklist", "whitelist"):
        raise HTTPException(status_code=400, detail="list_type must be 'blacklist' or 'whitelist'")

    try:
        async with async_session_factory() as session:
            entry = TopicBlacklist(
                id=uuid.uuid4(),
                keyword=body.keyword.strip().lower(),
                list_type=body.list_type,
            )
            session.add(entry)
            await session.commit()

        return {"status": "added", "keyword": body.keyword, "list_type": body.list_type}

    except IntegrityError:
        raise HTTPException(status_code=409, detail=f"Keyword '{body.keyword}' already exists")


@router.delete("/blacklist/{keyword}")
async def remove_from_blacklist(keyword: str):
    """Remove a keyword from blacklist/whitelist."""
    from sqlalchemy import delete

    from app.core.database import async_session_factory
    from app.models.analytics import TopicBlacklist

    async with async_session_factory() as session:
        result = await session.execute(
            delete(TopicBlacklist).where(TopicBlacklist.keyword == keyword.strip().lower())
        )
        await session.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Keyword not found")

    return {"status": "removed", "keyword": keyword}
