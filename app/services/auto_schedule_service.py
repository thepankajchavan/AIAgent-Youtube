"""
Scheduling Brain — smart auto-scheduling with optimal timing, diversity, and performance feedback.

Replaces the old AutoScheduleService with Redis runtime toggles, queue-based scheduling,
optimal posting window detection, topic diversity enforcement, and audit logging.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import redis.asyncio as aioredis
from loguru import logger

from app.core.config import get_settings

REDIS_TOGGLE_KEY = "autopilot:enabled"
REDIS_HEALTH_KEY = "autopilot:last_trend_fetch"


class SchedulingBrain:
    """Smart scheduling engine with optimal timing, diversity, and feedback."""

    def __init__(self) -> None:
        self._settings = get_settings()

    # ── Redis Runtime Toggle ──────────────────────────────────

    async def is_enabled(self) -> bool:
        """Check Redis first (runtime toggle), fall back to settings."""
        try:
            r = aioredis.from_url(self._settings.redis_url, decode_responses=True)
            try:
                val = await r.get(REDIS_TOGGLE_KEY)
                if val is not None:
                    return val == "1"
            finally:
                await r.aclose()
        except Exception as exc:
            logger.debug("Redis toggle check failed, using settings: {}", exc)

        return self._settings.auto_schedule_enabled

    async def set_enabled(self, enabled: bool) -> None:
        """Write toggle to Redis. Takes effect immediately across all workers."""
        try:
            r = aioredis.from_url(self._settings.redis_url, decode_responses=True)
            try:
                await r.set(REDIS_TOGGLE_KEY, "1" if enabled else "0")
                logger.info("Autopilot toggled to {} via Redis", enabled)
            finally:
                await r.aclose()
        except Exception as exc:
            logger.error("Failed to set Redis toggle: {}", exc)
            raise

    def is_enabled_sync(self) -> bool:
        """Synchronous check for Celery tasks — checks Redis, falls back to settings."""
        try:
            import redis as sync_redis

            r = sync_redis.from_url(self._settings.redis_url, decode_responses=True)
            val = r.get(REDIS_TOGGLE_KEY)
            r.close()
            if val is not None:
                return val == "1"
        except Exception:
            pass
        return self._settings.auto_schedule_enabled

    # ── Gate Checks (synchronous, for Celery) ─────────────────

    def should_schedule_now(self) -> bool:
        """Check if we should auto-schedule a video right now.

        Checks: Redis/env toggle + daily limit + cooldown.
        """
        if not self.is_enabled_sync():
            return False

        today_count = self._get_today_count()
        if today_count >= self._settings.auto_schedule_max_daily:
            logger.info(
                "Auto-schedule daily limit reached: {}/{}",
                today_count,
                self._settings.auto_schedule_max_daily,
            )
            return False

        if not self._cooldown_elapsed():
            logger.debug("Auto-schedule cooldown not elapsed")
            return False

        return True

    def _get_today_count(self) -> int:
        """Count auto-scheduled videos created today."""
        from sqlalchemy import func, select

        from app.models.video import VideoProject
        from app.workers.db import get_sync_db

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        with get_sync_db() as session:
            q = (
                select(func.count())
                .select_from(VideoProject)
                .where(VideoProject.is_auto_scheduled.is_(True))
                .where(VideoProject.created_at >= today_start)
            )
            result = session.execute(q)
            return result.scalar() or 0

    def _cooldown_elapsed(self) -> bool:
        """Check if enough time has passed since the last auto-scheduled video."""
        from sqlalchemy import select

        from app.models.video import VideoProject
        from app.workers.db import get_sync_db

        cooldown_hours = self._settings.auto_schedule_cooldown_hours

        with get_sync_db() as session:
            q = (
                select(VideoProject.created_at)
                .where(VideoProject.is_auto_scheduled.is_(True))
                .order_by(VideoProject.created_at.desc())
                .limit(1)
            )
            result = session.execute(q)
            last_created = result.scalar_one_or_none()

        if last_created is None:
            return True

        elapsed = datetime.now(timezone.utc) - last_created
        return elapsed >= timedelta(hours=cooldown_hours)

    # ── Optimal Posting Time ──────────────────────────────────

    async def get_optimal_posting_windows(self) -> list[dict]:
        """Analyze video_analytics to find best hours/days for posting.

        Groups completed videos by hour-of-day and day-of-week.
        Returns top 5 windows ranked by average views.
        Falls back to even spacing if insufficient data.
        """
        from sqlalchemy import String, cast, extract, func, select

        from app.core.database import async_session_factory
        from app.models.analytics import VideoAnalytics
        from app.models.video import VideoProject

        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        try:
            async with async_session_factory() as session:
                # Group by hour and day-of-week
                q = (
                    select(
                        extract("dow", VideoProject.created_at).label("dow"),
                        extract("hour", VideoProject.created_at).label("hour"),
                        func.avg(VideoAnalytics.views).label("avg_views"),
                        func.count().label("sample_count"),
                    )
                    .join(
                        VideoAnalytics,
                        VideoAnalytics.project_id == cast(VideoProject.id, String),
                    )
                    .where(VideoProject.youtube_video_id.isnot(None))
                    .group_by("dow", "hour")
                    .having(func.count() >= 2)
                    .order_by(func.avg(VideoAnalytics.views).desc())
                    .limit(5)
                )
                result = await session.execute(q)
                rows = result.all()

            if not rows:
                return self._default_posting_windows()

            return [
                {
                    "day": day_names[int(row.dow)] if int(row.dow) < 7 else "Unknown",
                    "hour": int(row.hour),
                    "avg_views": round(float(row.avg_views), 1),
                    "sample_count": int(row.sample_count),
                }
                for row in rows
            ]
        except Exception as exc:
            logger.warning("Failed to compute posting windows: {}", exc)
            return self._default_posting_windows()

    def _default_posting_windows(self) -> list[dict]:
        """Default posting windows when insufficient analytics data."""
        return [
            {"day": "Monday", "hour": 12, "avg_views": 0, "sample_count": 0},
            {"day": "Wednesday", "hour": 17, "avg_views": 0, "sample_count": 0},
            {"day": "Friday", "hour": 14, "avg_views": 0, "sample_count": 0},
            {"day": "Saturday", "hour": 10, "avg_views": 0, "sample_count": 0},
            {"day": "Sunday", "hour": 11, "avg_views": 0, "sample_count": 0},
        ]

    async def get_next_posting_time(self) -> datetime:
        """Find the next upcoming optimal posting window.

        Falls back to cooldown_hours from now.
        """
        windows = await self.get_optimal_posting_windows()
        now = datetime.now(timezone.utc)
        day_map = {
            "Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
            "Friday": 4, "Saturday": 5, "Sunday": 6,
        }

        candidates: list[datetime] = []
        for w in windows:
            day_name = w.get("day", "")
            target_dow = day_map.get(day_name)
            target_hour = w.get("hour", 12)

            if target_dow is None:
                continue

            # Find next occurrence of this day/hour
            current_dow = now.weekday()
            days_ahead = (target_dow - current_dow) % 7

            candidate = now.replace(
                hour=target_hour, minute=0, second=0, microsecond=0
            ) + timedelta(days=days_ahead)

            # If it's today but already passed, push to next week
            if candidate <= now:
                candidate += timedelta(weeks=1)

            candidates.append(candidate)

        if candidates:
            return min(candidates)

        # Fallback: cooldown hours from now
        return now + timedelta(hours=self._settings.auto_schedule_cooldown_hours)

    # ── Smart Topic Selection ─────────────────────────────────

    async def select_topic(self, niche_rotation: bool = True) -> dict | None:
        """Smart topic selection with diversity, freshness, and performance feedback.

        Selection signals:
        1. Quality threshold
        2. Category diversity (no same-category back-to-back)
        3. Performance feedback (boost topics similar to top performers)
        4. Blacklist/whitelist filtering (handled by get_best_topics)
        """
        from app.services.trend_service import TrendAggregator

        aggregator = TrendAggregator()
        niche = self._settings.auto_schedule_niche or None

        # Get candidate topics (already filtered by quality, blacklist, recently used)
        candidates = await aggregator.get_best_topics_for_scheduling(
            niche=niche, limit=10, exclude_used_days=3,
        )

        if not candidates:
            return None

        # Apply diversity filter
        if niche_rotation:
            candidates = self._apply_diversity_filter(candidates)

        # Apply performance feedback if enabled
        if getattr(self._settings, "auto_schedule_performance_feedback", True):
            candidates = await self._apply_performance_feedback(candidates)

        # Sort by adjusted quality score
        candidates.sort(key=lambda t: t.get("quality_score", 0), reverse=True)

        if candidates:
            selected = candidates[0]
            logger.info(
                "Topic selected: '{}' (quality={}, niche={}, velocity={})",
                selected["topic"],
                selected.get("quality_score"),
                selected.get("niche"),
                selected.get("velocity"),
            )
            return selected

        return None

    def _apply_diversity_filter(self, candidates: list[dict]) -> list[dict]:
        """Deprioritize topics from recently-used categories."""
        diversity_window = getattr(self._settings, "auto_schedule_diversity_window", 3)
        recent_categories = self._get_last_n_categories(diversity_window)

        if not recent_categories:
            return candidates

        for candidate in candidates:
            niche = candidate.get("niche") or candidate.get("category")
            if niche and niche in recent_categories:
                candidate["quality_score"] = candidate.get("quality_score", 0) * 0.5

        return candidates

    def _get_last_n_categories(self, n: int = 3) -> list[str]:
        """Query last N auto-scheduled VideoProjects for their niche/category."""
        from sqlalchemy import select

        from app.models.video import VideoProject
        from app.workers.db import get_sync_db

        try:
            with get_sync_db() as session:
                q = (
                    select(VideoProject.trend_topic_used)
                    .where(VideoProject.is_auto_scheduled.is_(True))
                    .where(VideoProject.trend_topic_used.isnot(None))
                    .order_by(VideoProject.created_at.desc())
                    .limit(n)
                )
                result = session.execute(q)
                return [row[0] for row in result.all() if row[0]]
        except Exception:
            return []

    async def _apply_performance_feedback(self, candidates: list[dict]) -> list[dict]:
        """Boost topics similar to high-performing past videos."""
        try:
            from app.services.analytics_service import AnalyticsService

            analytics = AnalyticsService()
            top_videos = await analytics.get_top_performing_videos(limit=10, lookback_days=90)

            if not top_videos:
                return candidates

            top_topics = [v.get("topic", "") for v in top_videos if v.get("topic")]

            for candidate in candidates:
                for top_topic in top_topics:
                    similarity = SequenceMatcher(
                        None,
                        candidate["topic"].lower(),
                        top_topic.lower(),
                    ).ratio()
                    if similarity >= 0.5:
                        candidate["quality_score"] = min(
                            candidate.get("quality_score", 0) * 1.2, 100.0
                        )
                        break  # Only boost once

        except Exception as exc:
            logger.debug("Performance feedback unavailable: {}", exc)

        return candidates

    # ── Queue Management ──────────────────────────────────────

    async def enqueue_topic(self, topic: dict, scheduled_for: datetime) -> str:
        """Add topic to schedule_queue. Returns queue entry ID."""
        from app.core.database import async_session_factory
        from app.models.analytics import ScheduleQueue

        queue_id = uuid.uuid4()
        async with async_session_factory() as session:
            entry = ScheduleQueue(
                id=queue_id,
                topic=topic["topic"][:512],
                trend_id=topic.get("id"),
                niche=topic.get("niche"),
                scheduled_for=scheduled_for,
                quality_score=topic.get("quality_score", 0.0),
                status="pending",
                visual_strategy=self._settings.auto_schedule_visual_strategy,
            )
            session.add(entry)
            await session.commit()

        logger.info("Enqueued topic '{}' for {}", topic["topic"][:50], scheduled_for.isoformat())
        return str(queue_id)

    async def dispatch_queued(self) -> dict | None:
        """Find and dispatch the oldest pending queue entry where scheduled_for <= now.

        Creates VideoProject, calls build_pipeline, updates queue entry.
        Returns dispatch info dict or None if nothing due.
        """
        from sqlalchemy import select, update

        from app.core.database import async_session_factory
        from app.models.analytics import ScheduleQueue

        now = datetime.now(timezone.utc)

        async with async_session_factory() as session:
            q = (
                select(ScheduleQueue)
                .where(ScheduleQueue.status == "pending")
                .where(ScheduleQueue.scheduled_for <= now)
                .order_by(ScheduleQueue.scheduled_for.asc())
                .limit(1)
            )
            result = await session.execute(q)
            entry = result.scalar_one_or_none()

            if not entry:
                return None

            entry_id = str(entry.id)
            entry_topic = entry.topic
            entry_niche = entry.niche
            entry_quality = entry.quality_score
            entry_visual_strategy = entry.visual_strategy
            entry_trend_id = entry.trend_id

        # Create VideoProject and dispatch pipeline (synchronous, for Celery compatibility)
        project_id, pipeline_result = self._create_and_dispatch(
            topic=entry_topic,
            visual_strategy=entry_visual_strategy,
            queue_id=entry_id,
        )

        # Update queue entry
        async with async_session_factory() as session:
            await session.execute(
                update(ScheduleQueue)
                .where(ScheduleQueue.id == uuid.UUID(entry_id))
                .values(
                    status="dispatched",
                    project_id=project_id,
                    dispatched_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

        dispatch_info = {
            "queue_id": entry_id,
            "project_id": project_id,
            "topic": entry_topic,
            "niche": entry_niche,
            "quality_score": entry_quality,
        }

        await self.log_decision(
            action="schedule_dispatched",
            topic=entry_topic,
            reason=f"Queue entry {entry_id} dispatched at scheduled time",
            details=dispatch_info,
        )

        return dispatch_info

    def _create_and_dispatch(
        self, topic: str, visual_strategy: str, queue_id: str
    ) -> tuple[str, object]:
        """Create VideoProject in DB and dispatch Celery pipeline."""
        from app.models.video import VideoProject, VideoStatus
        from app.workers.db import get_sync_db
        from app.workers.pipeline import build_pipeline

        project_id = str(uuid.uuid4())

        with get_sync_db() as session:
            admin_chat_id = self._settings.auto_schedule_admin_chat_id
            project = VideoProject(
                id=uuid.UUID(project_id),
                topic=topic[:512],
                status=VideoStatus.PENDING,
                visual_strategy=visual_strategy,
                is_auto_scheduled=True,
                trend_topic_used=topic[:512],
                schedule_queue_id=queue_id,
                telegram_chat_id=admin_chat_id if admin_chat_id else None,
            )
            session.add(project)

        pipeline = build_pipeline(
            project_id=project_id,
            topic=topic,
            video_format="short",
            provider="openai",
            skip_upload=self._settings.auto_schedule_skip_upload,
            visual_strategy=visual_strategy,
        )
        pipeline.apply_async()

        logger.info(
            "Auto-scheduled pipeline dispatched — project={} topic='{}'",
            project_id, topic[:50],
        )
        return project_id, pipeline

    async def cancel_queued(self, queue_id: str) -> bool:
        """Cancel a pending queue entry. Returns True if cancelled."""
        from sqlalchemy import update

        from app.core.database import async_session_factory
        from app.models.analytics import ScheduleQueue

        async with async_session_factory() as session:
            result = await session.execute(
                update(ScheduleQueue)
                .where(ScheduleQueue.id == uuid.UUID(queue_id))
                .where(ScheduleQueue.status == "pending")
                .values(status="cancelled")
            )
            await session.commit()
            cancelled = result.rowcount > 0

        if cancelled:
            await self.log_decision(
                action="schedule_cancelled",
                topic=None,
                reason=f"Queue entry {queue_id} cancelled by user",
            )

        return cancelled

    # ── Audit Logging ─────────────────────────────────────────

    async def log_decision(
        self,
        action: str,
        topic: str | None,
        reason: str,
        details: dict | None = None,
    ) -> None:
        """Insert into schedule_audit_log."""
        from app.core.database import async_session_factory
        from app.models.analytics import ScheduleAuditLog

        try:
            async with async_session_factory() as session:
                entry = ScheduleAuditLog(
                    id=uuid.uuid4(),
                    action=action,
                    topic=topic[:512] if topic else None,
                    reason=reason,
                    details=json.dumps(details) if details else None,
                )
                session.add(entry)
                await session.commit()
        except Exception as exc:
            logger.warning("Failed to write audit log: {}", exc)

    # ── Stats & Queries ───────────────────────────────────────

    async def get_stats(self) -> dict:
        """Enhanced stats with queue depth, health, and next scheduled."""
        from sqlalchemy import func, select

        from app.core.database import async_session_factory
        from app.models.analytics import ScheduleQueue

        enabled = await self.is_enabled()
        today_count = self._get_today_count()
        max_daily = self._settings.auto_schedule_max_daily

        # Queue depth
        queue_depth = 0
        next_scheduled = None
        try:
            async with async_session_factory() as session:
                q = select(func.count()).select_from(ScheduleQueue).where(
                    ScheduleQueue.status == "pending"
                )
                result = await session.execute(q)
                queue_depth = result.scalar() or 0

                # Next scheduled time
                q2 = (
                    select(ScheduleQueue.scheduled_for)
                    .where(ScheduleQueue.status == "pending")
                    .order_by(ScheduleQueue.scheduled_for.asc())
                    .limit(1)
                )
                r2 = await session.execute(q2)
                next_time = r2.scalar_one_or_none()
                if next_time:
                    next_scheduled = next_time.isoformat()
        except Exception:
            pass

        # Health status
        health = await self._check_trend_health()

        return {
            "enabled": enabled,
            "today_count": today_count,
            "max_daily": max_daily,
            "remaining_today": max(0, max_daily - today_count),
            "cooldown_hours": self._settings.auto_schedule_cooldown_hours,
            "niche": self._settings.auto_schedule_niche or "any",
            "visual_strategy": self._settings.auto_schedule_visual_strategy,
            "queue_depth": queue_depth,
            "next_scheduled": next_scheduled,
            "health_status": health,
        }

    async def get_queue(self, limit: int = 20) -> list[dict]:
        """Return pending queue entries ordered by scheduled_for."""
        from sqlalchemy import select

        from app.core.database import async_session_factory
        from app.models.analytics import ScheduleQueue

        async with async_session_factory() as session:
            q = (
                select(ScheduleQueue)
                .where(ScheduleQueue.status == "pending")
                .order_by(ScheduleQueue.scheduled_for.asc())
                .limit(limit)
            )
            result = await session.execute(q)
            entries = result.scalars().all()

        return [
            {
                "id": str(e.id),
                "topic": e.topic,
                "niche": e.niche,
                "scheduled_for": e.scheduled_for.isoformat() if e.scheduled_for else None,
                "quality_score": e.quality_score,
                "visual_strategy": e.visual_strategy,
            }
            for e in entries
        ]

    async def get_history(self, limit: int = 50) -> list[dict]:
        """Return dispatched/completed queue entries."""
        from sqlalchemy import select

        from app.core.database import async_session_factory
        from app.models.analytics import ScheduleQueue

        async with async_session_factory() as session:
            q = (
                select(ScheduleQueue)
                .where(ScheduleQueue.status.in_(["dispatched", "completed", "failed"]))
                .order_by(ScheduleQueue.dispatched_at.desc())
                .limit(limit)
            )
            result = await session.execute(q)
            entries = result.scalars().all()

        return [
            {
                "id": str(e.id),
                "topic": e.topic,
                "niche": e.niche,
                "status": e.status,
                "project_id": e.project_id,
                "quality_score": e.quality_score,
                "scheduled_for": e.scheduled_for.isoformat() if e.scheduled_for else None,
                "dispatched_at": e.dispatched_at.isoformat() if e.dispatched_at else None,
            }
            for e in entries
        ]

    async def _check_trend_health(self) -> str:
        """Quick health check on trend fetching."""
        try:
            r = aioredis.from_url(self._settings.redis_url, decode_responses=True)
            try:
                val = await r.get(REDIS_HEALTH_KEY)
                if val:
                    last_fetch = datetime.fromisoformat(val)
                    hours_ago = (datetime.now(timezone.utc) - last_fetch).total_seconds() / 3600
                    if hours_ago < 12:
                        return "healthy"
                    return f"stale ({hours_ago:.1f}h ago)"
            finally:
                await r.aclose()
        except Exception:
            pass
        return "unknown"

    # ── Backward Compatibility ────────────────────────────────

    def should_auto_schedule(self) -> bool:
        """Backward-compatible alias for should_schedule_now."""
        return self.should_schedule_now()

    def pick_best_trend(self, niche: str | None = None) -> dict | None:
        """Backward-compatible sync wrapper."""
        import asyncio

        from app.services.trend_service import TrendAggregator

        aggregator = TrendAggregator()
        try:
            trend = asyncio.run(aggregator.get_trend_for_video(niche or None))
            if trend:
                logger.info(
                    "Auto-schedule picked trend: '{}' (score={})",
                    trend["topic"],
                    trend.get("quality_score", trend.get("trend_score")),
                )
            return trend
        except Exception as exc:
            logger.error("Failed to pick trend for auto-schedule: {}", exc)
            return None

    def get_auto_schedule_stats(self) -> dict:
        """Backward-compatible sync stats (no queue/health info)."""
        today_count = self._get_today_count()
        return {
            "enabled": self._settings.auto_schedule_enabled,
            "today_count": today_count,
            "max_daily": self._settings.auto_schedule_max_daily,
            "remaining_today": max(0, self._settings.auto_schedule_max_daily - today_count),
            "cooldown_hours": self._settings.auto_schedule_cooldown_hours,
            "niche": self._settings.auto_schedule_niche or "any",
            "visual_strategy": self._settings.auto_schedule_visual_strategy,
        }


# Backward compatibility alias
AutoScheduleService = SchedulingBrain
