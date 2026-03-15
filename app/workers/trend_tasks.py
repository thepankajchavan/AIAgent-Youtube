"""
Trend Tasks — Celery tasks for multi-source trend collection, cleanup, and health.

Scheduled via Celery Beat:
- collect_all_trends_task: every N hours (default 4)
- cleanup_expired_trends_task: daily at 3:30 AM
- check_trend_health_task: every 30 minutes
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from app.core.celery_app import celery_app
from app.core.config import get_settings


def _run_async(coro):
    """Run async coroutine from sync Celery task."""
    return asyncio.run(coro)


@celery_app.task(
    bind=True,
    name="app.workers.trend_tasks.collect_all_trends_task",
    queue="default",
    max_retries=2,
    default_retry_delay=600,
    acks_late=True,
    time_limit=600,
    soft_time_limit=540,
)
def collect_all_trends_task(self):
    """Fetch trends from all enabled sources, score, and store.

    Runs every N hours (default 4). Non-critical — graceful degradation.
    Records health timestamp on success.
    """
    settings = get_settings()

    if not settings.trends_enabled:
        logger.debug("Trend collection disabled — skipping")
        return {"status": "disabled"}

    logger.info("Starting multi-source trend collection")

    try:
        from app.services.trend_service import TrendAggregator

        aggregator = TrendAggregator()
        count = _run_async(aggregator.collect_and_store_trends())

        # Record health timestamp
        from app.services.trend_health_service import TrendHealthMonitor

        monitor = TrendHealthMonitor()
        _run_async(monitor.record_successful_fetch())

        logger.info("Trend collection complete — {} unique trends stored", count)
        return {"status": "success", "trends_collected": count}

    except Exception as exc:
        logger.error("Trend collection failed: {}", exc)

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        logger.warning(
            "Trend collection permanently failed after {} attempts — non-critical",
            self.max_retries + 1,
        )
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    name="app.workers.trend_tasks.cleanup_expired_trends_task",
    queue="default",
    max_retries=0,
    time_limit=120,
    soft_time_limit=100,
)
def cleanup_expired_trends_task(self):
    """Delete expired trends older than 48 hours. Runs daily."""
    settings = get_settings()

    if not settings.trends_enabled:
        return {"status": "disabled"}

    from sqlalchemy import delete

    from app.models.analytics import TrendingTopic
    from app.workers.db import get_sync_db

    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)

    try:
        with get_sync_db() as session:
            result = session.execute(
                delete(TrendingTopic).where(TrendingTopic.expires_at < cutoff)
            )
            deleted = result.rowcount

        logger.info("Cleaned up {} expired trends", deleted)
        return {"status": "success", "deleted": deleted}

    except Exception as exc:
        logger.error("Trend cleanup failed: {}", exc)
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    name="app.workers.trend_tasks.check_trend_health_task",
    queue="default",
    max_retries=0,
    time_limit=30,
    soft_time_limit=25,
)
def check_trend_health_task(self):
    """Check if trend fetching is healthy. Alert via Telegram if stale.

    Runs every 30 minutes.
    """
    settings = get_settings()

    if not settings.trends_enabled:
        return {"status": "disabled"}

    from app.services.trend_health_service import TrendHealthMonitor

    monitor = TrendHealthMonitor()
    health = _run_async(monitor.check_health())

    if health.get("healthy"):
        return {"status": "healthy", **health}

    # Alert if stale
    logger.warning("Trend fetching is stale: {}", health)

    admin_chat_id = getattr(settings, "auto_schedule_admin_chat_id", 0)
    if admin_chat_id:
        try:
            _send_telegram_alert(
                admin_chat_id,
                f"Trend fetching is {health.get('status', 'unhealthy')}. "
                f"Last fetch: {health.get('last_fetch_ago_hours', 'never')}h ago.",
            )
        except Exception as exc:
            logger.warning("Failed to send health alert: {}", exc)

    return {"status": "alert_sent", **health}


def _send_telegram_alert(chat_id: int, message: str) -> None:
    """Send a Telegram alert message to admin."""
    import httpx

    settings = get_settings()
    if not settings.telegram_bot_token:
        return

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    httpx.post(url, json={"chat_id": chat_id, "text": f"[AutoPilot Alert] {message}"}, timeout=10)


# Backward compatibility: keep old task name as alias
collect_trends_task = collect_all_trends_task
