"""
Analytics Routes — endpoints for the self-improvement feedback loop system.

Provides access to analytics data, trends, patterns, and prompt versions.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.analytics import (
    PerformancePattern,
    PromptVersion,
    TrendingTopic,
    VideoAnalytics,
)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


# ── Schemas ──────────────────────────────────────────────────


class MessageResponse(BaseModel):
    message: str


class PerformanceSummaryResponse(BaseModel):
    total_views: int = 0
    avg_views: float = 0.0
    avg_retention: float = 0.0
    avg_ctr: float = 0.0
    snapshot_count: int = 0
    best_video: dict | None = None
    worst_video: dict | None = None
    days: int = 30


class VideoAnalyticsResponse(BaseModel):
    project_id: str
    youtube_video_id: str
    snapshot_date: str
    views: int
    likes: int
    comments: int
    shares: int
    watch_time_minutes: float
    average_view_duration_seconds: float
    click_through_rate: float | None
    average_view_percentage: float | None
    collected_at: datetime


class TrendResponse(BaseModel):
    id: str
    topic: str
    category: str | None
    trend_score: float
    source: str
    region: str
    fetched_at: datetime
    expires_at: datetime


class PatternResponse(BaseModel):
    id: str
    pattern_type: str
    description: str
    confidence_score: float
    sample_size: int
    avg_views: float
    is_active: bool
    discovered_at: datetime


class PromptVersionResponse(BaseModel):
    id: str
    version_label: str
    template: str
    is_active: bool
    is_baseline: bool
    usage_count: int
    avg_views: float | None
    avg_retention: float | None
    avg_ctr: float | None
    created_at: datetime
    updated_at: datetime


class CreatePromptVersionRequest(BaseModel):
    template: str = Field(..., min_length=10, description="Prompt template with {topic} placeholder")
    label: str = Field(..., min_length=1, max_length=100, description="Version label")


# ── Analytics Endpoints ──────────────────────────────────────


@router.get(
    "/summary",
    response_model=PerformanceSummaryResponse,
    summary="Get performance summary",
    description="Returns aggregated analytics for the last N days.",
)
async def get_performance_summary(
    days: int = Query(default=30, ge=1, le=365),
):
    from app.services.analytics_service import AnalyticsService

    service = AnalyticsService()
    summary = await service.get_performance_summary(days=days)
    return PerformanceSummaryResponse(**summary)


@router.get(
    "/videos",
    response_model=list[VideoAnalyticsResponse],
    summary="List video analytics",
    description="Returns analytics for individual videos, sorted by views.",
)
async def list_video_analytics(
    limit: int = Query(default=20, ge=1, le=100),
    sort: str = Query(default="views", description="Sort field"),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(VideoAnalytics)
        .order_by(VideoAnalytics.views.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    records = result.scalars().all()

    return [
        VideoAnalyticsResponse(
            project_id=r.project_id,
            youtube_video_id=r.youtube_video_id,
            snapshot_date=r.snapshot_date.isoformat(),
            views=r.views,
            likes=r.likes,
            comments=r.comments,
            shares=r.shares,
            watch_time_minutes=r.watch_time_minutes,
            average_view_duration_seconds=r.average_view_duration_seconds,
            click_through_rate=r.click_through_rate,
            average_view_percentage=r.average_view_percentage,
            collected_at=r.collected_at,
        )
        for r in records
    ]


@router.post(
    "/collect",
    response_model=MessageResponse,
    summary="Trigger analytics collection",
    description="Manually trigger YouTube analytics collection.",
)
async def trigger_analytics_collection():
    from app.workers.analytics_tasks import collect_analytics_task

    result = collect_analytics_task.delay()
    logger.info("Analytics collection triggered manually — task_id={}", result.id)
    return MessageResponse(message=f"Analytics collection started (task: {result.id})")


# ── Trends Endpoints ─────────────────────────────────────────


trends_router = APIRouter(prefix="/api/v1/trends", tags=["trends"])


@trends_router.get(
    "/current",
    response_model=list[TrendResponse],
    summary="Get current trends",
    description="Returns currently trending topics.",
)
async def get_current_trends(
    category: str | None = Query(default=None, description="Filter by category"),
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    query = (
        select(TrendingTopic)
        .where(TrendingTopic.expires_at > now)
        .order_by(TrendingTopic.trend_score.desc())
        .limit(limit)
    )
    if category:
        query = query.where(TrendingTopic.category == category)

    result = await db.execute(query)
    topics = result.scalars().all()

    return [
        TrendResponse(
            id=str(t.id),
            topic=t.topic,
            category=t.category,
            trend_score=t.trend_score,
            source=t.source,
            region=t.region,
            fetched_at=t.fetched_at,
            expires_at=t.expires_at,
        )
        for t in topics
    ]


@trends_router.post(
    "/collect",
    response_model=MessageResponse,
    summary="Trigger trend collection",
    description="Manually trigger trend data collection.",
)
async def trigger_trend_collection():
    from app.workers.trend_tasks import collect_trends_task

    result = collect_trends_task.delay()
    logger.info("Trend collection triggered manually — task_id={}", result.id)
    return MessageResponse(message=f"Trend collection started (task: {result.id})")


# ── Patterns Endpoints ───────────────────────────────────────


patterns_router = APIRouter(prefix="/api/v1/patterns", tags=["patterns"])


@patterns_router.get(
    "",
    response_model=list[PatternResponse],
    summary="Get performance patterns",
    description="Returns all active performance patterns.",
)
async def get_patterns(
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(PerformancePattern)
        .where(PerformancePattern.is_active.is_(True))
        .order_by(PerformancePattern.confidence_score.desc())
    )
    result = await db.execute(query)
    patterns = result.scalars().all()

    return [
        PatternResponse(
            id=str(p.id),
            pattern_type=p.pattern_type,
            description=p.description,
            confidence_score=p.confidence_score,
            sample_size=p.sample_size,
            avg_views=p.avg_views,
            is_active=p.is_active,
            discovered_at=p.discovered_at,
        )
        for p in patterns
    ]


@patterns_router.post(
    "/analyze",
    response_model=MessageResponse,
    summary="Trigger pattern analysis",
    description="Manually trigger performance pattern analysis.",
)
async def trigger_pattern_analysis():
    from app.workers.pattern_tasks import analyze_patterns_task

    result = analyze_patterns_task.delay()
    logger.info("Pattern analysis triggered manually — task_id={}", result.id)
    return MessageResponse(message=f"Pattern analysis started (task: {result.id})")


# ── Prompt Versions Endpoints ────────────────────────────────


prompts_router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


@prompts_router.get(
    "/versions",
    response_model=list[PromptVersionResponse],
    summary="List prompt versions",
    description="Returns all prompt versions with their performance stats.",
)
async def list_prompt_versions(
    db: AsyncSession = Depends(get_db),
):
    query = select(PromptVersion).order_by(PromptVersion.created_at.desc())
    result = await db.execute(query)
    versions = result.scalars().all()

    return [
        PromptVersionResponse(
            id=str(v.id),
            version_label=v.version_label,
            template=v.template,
            is_active=v.is_active,
            is_baseline=v.is_baseline,
            usage_count=v.usage_count,
            avg_views=v.avg_views,
            avg_retention=v.avg_retention,
            avg_ctr=v.avg_ctr,
            created_at=v.created_at,
            updated_at=v.updated_at,
        )
        for v in versions
    ]


@prompts_router.post(
    "/versions",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create prompt version",
    description="Create a new prompt version (inactive by default).",
)
async def create_prompt_version(
    request: CreatePromptVersionRequest,
):
    from app.services.prompt_builder_service import DynamicPromptBuilder

    builder = DynamicPromptBuilder()
    version_id = await builder.create_new_version(
        template=request.template, label=request.label
    )
    return MessageResponse(message=f"Prompt version created: {version_id}")


@prompts_router.post(
    "/versions/{version_id}/promote",
    response_model=MessageResponse,
    summary="Promote prompt version",
    description="Set a prompt version as the active one.",
)
async def promote_prompt_version(version_id: str):
    from app.services.prompt_builder_service import DynamicPromptBuilder

    builder = DynamicPromptBuilder()
    try:
        promoted = await builder.promote_version(version_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if not promoted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Version not eligible for promotion (needs 5+ uses and better performance than baseline).",
        )

    return MessageResponse(message=f"Prompt version {version_id} promoted to active")
