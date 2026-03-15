"""
Auto-Schedule Tasks — Celery tasks for fixed-time video scheduling.

Scheduled via Celery Beat at times from AUTO_SCHEDULE_TIMES (e.g. "10:00,18:00"):
- scheduled_video_task: all-in-one fetch → pick → dispatch → notify

IMPORTANT: Each Celery task must call _run_async() at most ONCE.
asyncio.run() creates/destroys event loops; SQLAlchemy's async_session_factory()
caches asyncpg connections to the first loop. Multiple _run_async() calls cause
"Future attached to a different loop" crashes.
"""

from __future__ import annotations

import asyncio
import random

from celery import Task
from loguru import logger

from app.core.celery_app import celery_app
from app.core.config import get_settings

# Curated fallback topics when all trend sources fail
_FALLBACK_TOPICS: list[dict] = [
    {"topic": "5 Psychology Tricks That Control Your Daily Decisions", "niche": "psychology", "quality_score": 70.0, "velocity": "rising", "source": "curated"},
    {"topic": "What Happens to Your Body in Space Without a Suit", "niche": "space", "quality_score": 70.0, "velocity": "rising", "source": "curated"},
    {"topic": "The Most Expensive Mistakes in Engineering History", "niche": "technology", "quality_score": 70.0, "velocity": "rising", "source": "curated"},
    {"topic": "Ancient Inventions That Were Way Ahead of Their Time", "niche": "history", "quality_score": 70.0, "velocity": "rising", "source": "curated"},
    {"topic": "Why Your Brain Sabotages Your Goals Every Morning", "niche": "motivation", "quality_score": 70.0, "velocity": "rising", "source": "curated"},
    {"topic": "3 Science Experiments That Almost Destroyed the World", "niche": "science", "quality_score": 70.0, "velocity": "rising", "source": "curated"},
    {"topic": "Hidden Features in Your Phone You Never Knew Existed", "niche": "technology", "quality_score": 70.0, "velocity": "rising", "source": "curated"},
    {"topic": "The Darkest Secrets of the Deep Ocean", "niche": "science", "quality_score": 70.0, "velocity": "rising", "source": "curated"},
    {"topic": "How One Decision Changed the Entire Course of History", "niche": "history", "quality_score": 70.0, "velocity": "rising", "source": "curated"},
    {"topic": "The Real Reason You Can't Focus Anymore", "niche": "psychology", "quality_score": 70.0, "velocity": "rising", "source": "curated"},
]


def _run_async(coro):
    """Run async coroutine from sync Celery task."""
    return asyncio.run(coro)


# ── Async helpers (called once via _run_async to share one event loop) ────


async def _fetch_trends_and_select_topic() -> tuple[dict | None, int]:
    """Fetch trends + pick best topic in a single event loop.

    Returns (topic_dict_or_None, trend_count).
    """
    from app.services.auto_schedule_service import SchedulingBrain
    from app.services.trend_health_service import TrendHealthMonitor
    from app.services.trend_service import TrendAggregator

    aggregator = TrendAggregator()
    brain = SchedulingBrain()
    trend_count = 0

    # 1. Fetch fresh trends
    try:
        trend_count = await aggregator.collect_and_store_trends()
        # Record health so check_trend_health_task sees "healthy"
        await TrendHealthMonitor().record_successful_fetch()
        logger.info("Fetched {} fresh trends", trend_count)
    except Exception as exc:
        logger.warning("Trend fetching failed, will try existing trends: {}", exc)

    # 2. Pick best topic
    topic = await brain.select_topic(niche_rotation=True)
    return topic, trend_count


async def _log_decision(action: str, topic: str, reason: str, details: dict | None = None) -> None:
    """Log a scheduling decision via SchedulingBrain."""
    from app.services.auto_schedule_service import SchedulingBrain

    brain = SchedulingBrain()
    await brain.log_decision(action=action, topic=topic, reason=reason, details=details)


async def _evaluate_and_select() -> tuple[dict | None, dict | None]:
    """Legacy: dispatch queued OR select new topic. Single event loop.

    Returns (dispatch_result_or_None, topic_or_None).
    """
    from app.services.auto_schedule_service import SchedulingBrain

    brain = SchedulingBrain()

    # Try dispatching queued items first
    dispatch_result = await brain.dispatch_queued()
    if dispatch_result:
        return dispatch_result, None

    # Pick a new topic
    topic = await brain.select_topic(niche_rotation=True)
    return None, topic


async def _enqueue_and_log(topic: dict) -> tuple[str, str]:
    """Legacy: enqueue topic + log decision. Single event loop.

    Returns (queue_id, scheduled_for_iso).
    """
    from app.services.auto_schedule_service import SchedulingBrain

    brain = SchedulingBrain()
    next_time = await brain.get_next_posting_time()
    queue_id = await brain.enqueue_topic(topic, scheduled_for=next_time)
    await brain.log_decision(
        action="topic_enqueued",
        topic=topic["topic"],
        reason=f"Selected with quality={topic.get('quality_score', 0):.1f}, "
               f"scheduled for {next_time.isoformat()}",
        details={"queue_id": queue_id, "topic": topic, "scheduled_for": next_time.isoformat()},
    )
    return queue_id, next_time.isoformat(), next_time


# ── Main task ─────────────────────────────────────────────────


@celery_app.task(
    bind=True,
    name="app.workers.auto_schedule_tasks.scheduled_video_task",
    queue="default",
    max_retries=1,
    default_retry_delay=300,
    time_limit=300,
    soft_time_limit=280,
)
def scheduled_video_task(self: Task) -> dict:
    """Fixed-time auto-schedule: fetch trends → pick best → dispatch pipeline.

    Triggered by Celery Beat at each time in AUTO_SCHEDULE_TIMES.
    The pipeline will auto-upload to YouTube and send the link to Telegram
    via the notifier (using telegram_chat_id = admin_chat_id on the project).
    """
    settings = get_settings()
    from app.services.auto_schedule_service import SchedulingBrain

    brain = SchedulingBrain()

    # 1. Check toggle (Redis first, then settings) — sync, no event loop needed
    if not brain.is_enabled_sync():
        logger.info("Auto-schedule disabled, skipping")
        return {"status": "disabled"}

    # 2. Check daily limit + cooldown — sync, no event loop needed
    if not brain.should_schedule_now():
        logger.info("Auto-schedule daily limit or cooldown, skipping")
        return {"status": "skipped", "reason": "daily limit or cooldown"}

    # 3+4. Fetch trends + pick topic (ONE _run_async call — shares single event loop)
    topic, trend_count = _run_async(_fetch_trends_and_select_topic())

    if not topic:
        # Fallback: pick a random curated topic instead of skipping
        topic = random.choice(_FALLBACK_TOPICS)
        logger.info("No trends available — using curated fallback: '{}'", topic["topic"])
        _notify_admin(f"No trends found — using curated topic: '{topic['topic'][:50]}'")
        _run_async(_log_decision(
            action="fallback_topic",
            topic=topic["topic"],
            reason="All trend sources failed, using curated fallback",
        ))

    # 5. Dispatch immediately — sync, uses get_sync_db()
    try:
        project_id, _ = brain._create_and_dispatch(
            topic=topic["topic"],
            visual_strategy=settings.auto_schedule_visual_strategy,
            queue_id="",
        )
    except Exception as exc:
        logger.error("Failed to dispatch pipeline: {}", exc)
        _notify_admin(f"Failed to start video: {exc}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        return {"status": "failed", "error": str(exc)}

    # 6. Log and notify admin
    _run_async(_log_decision(
        action="video_dispatched",
        topic=topic["topic"],
        reason=f"Fixed-time dispatch, quality={topic.get('quality_score', 0):.1f}",
        details={"project_id": project_id, "topic": topic},
    ))

    _notify_admin(
        f"Video started: '{topic['topic'][:50]}'\n"
        f"Quality: {topic.get('quality_score', 0):.0f}\n"
        f"Project: {project_id}\n"
        f"YouTube link will be sent when upload completes."
    )

    return {
        "status": "dispatched",
        "project_id": project_id,
        "topic": topic["topic"],
        "quality_score": topic.get("quality_score"),
    }


# ── Legacy tasks (backward compatibility) ──────────────────────


@celery_app.task(
    bind=True,
    name="app.workers.auto_schedule_tasks.schedule_evaluation_task",
    queue="default",
    max_retries=1,
    default_retry_delay=300,
    time_limit=120,
    soft_time_limit=100,
)
def schedule_evaluation_task(self: Task) -> dict:
    """Legacy hourly evaluation task — now delegates to scheduled_video_task."""
    settings = get_settings()
    from app.services.auto_schedule_service import SchedulingBrain

    brain = SchedulingBrain()

    if not brain.is_enabled_sync():
        return {"status": "disabled"}

    if not brain.should_schedule_now():
        return {"status": "skipped", "reason": "daily limit or cooldown"}

    # Dispatch queued OR select topic (ONE _run_async call)
    dispatch_result, topic = _run_async(_evaluate_and_select())

    if dispatch_result:
        _notify_admin(
            f"Auto-scheduled video dispatched: '{dispatch_result['topic']}' "
            f"(project: {dispatch_result['project_id']})"
        )
        return {"status": "dispatched", **dispatch_result}

    if not topic:
        _run_async(_log_decision(
            action="no_topics",
            topic=None,
            reason="No suitable topics found after filtering",
        ))
        return {"status": "skipped", "reason": "no topics available"}

    # Enqueue + log (ONE _run_async call)
    queue_id, scheduled_for_iso, next_time = _run_async(_enqueue_and_log(topic))

    _notify_admin(
        f"Topic queued: '{topic['topic'][:50]}' "
        f"(quality: {topic.get('quality_score', 0):.0f}, "
        f"scheduled: {next_time.strftime('%Y-%m-%d %H:%M UTC')})"
    )

    return {
        "status": "enqueued",
        "queue_id": queue_id,
        "topic": topic["topic"],
        "quality_score": topic.get("quality_score"),
        "scheduled_for": scheduled_for_iso,
    }


@celery_app.task(
    bind=True,
    name="app.workers.auto_schedule_tasks.dispatch_scheduled_task",
    queue="default",
    max_retries=2,
    default_retry_delay=60,
    time_limit=60,
    soft_time_limit=50,
)
def dispatch_scheduled_task(self: Task, queue_id: str) -> dict:
    """Dispatch a specific queue entry: create VideoProject + trigger pipeline."""
    from app.services.auto_schedule_service import SchedulingBrain

    brain = SchedulingBrain()

    try:
        result = _run_async(brain.dispatch_queued())
        if result:
            logger.info(
                "Dispatched scheduled video — project={} topic='{}'",
                result["project_id"],
                result["topic"],
            )
            return {"status": "dispatched", **result}
        return {"status": "nothing_due"}

    except Exception as exc:
        logger.error("Failed to dispatch scheduled video: {}", exc)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        return {"status": "failed", "error": str(exc)}


def _notify_admin(message: str) -> None:
    """Send a Telegram notification to admin chat if configured."""
    try:
        settings = get_settings()
        admin_chat_id = getattr(settings, "auto_schedule_admin_chat_id", 0)
        if not admin_chat_id or not settings.telegram_bot_token:
            return

        import httpx

        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        httpx.post(
            url,
            json={"chat_id": admin_chat_id, "text": f"[AutoPilot] {message}"},
            timeout=10,
        )
    except Exception as exc:
        logger.debug("Admin notification failed: {}", exc)


# Backward compatibility aliases
auto_schedule_video_task = schedule_evaluation_task
