"""
Analytics Collection Tasks — Celery tasks for YouTube analytics data.

Scheduled via Celery Beat to run daily at configured hour.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from app.core.celery_app import celery_app
from app.core.config import get_settings


def _run_async(coro):
    """Run async coroutine from sync Celery task."""
    return asyncio.run(coro)


@celery_app.task(
    bind=True,
    name="app.workers.analytics_tasks.collect_analytics_task",
    queue="default",
    max_retries=3,
    default_retry_delay=300,
    acks_late=True,
    time_limit=1800,
    soft_time_limit=1700,
)
def collect_analytics_task(self):
    """
    Celery Beat scheduled task to collect YouTube analytics.

    Runs daily. Fetches stats for all recent videos and stores snapshots.
    """
    settings = get_settings()

    if not settings.youtube_analytics_enabled:
        logger.debug("YouTube analytics collection disabled — skipping")
        return {"status": "disabled"}

    logger.info("Starting YouTube analytics collection task")

    try:
        from app.services.analytics_service import AnalyticsService

        service = AnalyticsService()
        results = _run_async(
            service.collect_all_recent_videos(
                lookback_days=settings.youtube_analytics_lookback_days
            )
        )

        logger.info("Analytics collection complete — {} videos processed", len(results))

        # Update prompt performance after collecting new stats
        if settings.self_improvement_enabled and results:
            try:
                from app.services.prompt_builder_service import DynamicPromptBuilder

                builder = DynamicPromptBuilder()
                _run_async(builder.update_all_prompt_performance())
                logger.info("Prompt performance metrics updated")
            except Exception as exc:
                logger.warning("Failed to update prompt performance: {}", exc)

        return {"status": "success", "videos_collected": len(results)}

    except Exception as exc:
        logger.error("Analytics collection failed: {}", exc)

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        logger.error(
            "Analytics collection permanently failed after {} attempts",
            self.max_retries + 1,
        )
        raise
