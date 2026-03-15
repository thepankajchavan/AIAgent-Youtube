"""
Pattern Analysis Tasks — Celery tasks for discovering performance patterns.

Scheduled via Celery Beat to run weekly.
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
    name="app.workers.pattern_tasks.analyze_patterns_task",
    queue="default",
    max_retries=1,
    default_retry_delay=600,
    acks_late=True,
    time_limit=1800,
    soft_time_limit=1700,
)
def analyze_patterns_task(self):
    """
    Celery Beat scheduled task to analyze performance patterns.

    Runs weekly (or triggered manually). Uses LLM to discover patterns
    from top/bottom performing videos.
    """
    settings = get_settings()

    if not settings.self_improvement_enabled:
        logger.debug("Self-improvement disabled — skipping pattern analysis")
        return {"status": "disabled"}

    logger.info("Starting pattern analysis task")

    try:
        from app.services.pattern_service import PatternService

        service = PatternService()

        # Check if we have enough data
        should_run = _run_async(service.should_run_analysis())
        if not should_run:
            logger.info("Not enough data for pattern analysis — skipping")
            return {"status": "skipped", "reason": "insufficient_data"}

        # Run analysis
        patterns = _run_async(service.analyze_patterns())

        logger.info("Pattern analysis complete — {} patterns discovered", len(patterns))

        # Optionally create a new prompt version if significant patterns found
        if patterns and len(patterns) >= 3:
            try:
                from app.services.prompt_builder_service import DynamicPromptBuilder

                builder = DynamicPromptBuilder()
                _run_async(builder.maybe_create_improved_version(patterns))
            except Exception as exc:
                logger.warning("Failed to create improved prompt version: {}", exc)

        return {"status": "success", "patterns_discovered": len(patterns)}

    except Exception as exc:
        logger.error("Pattern analysis failed: {}", exc)

        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

        logger.error(
            "Pattern analysis permanently failed after {} attempts",
            self.max_retries + 1,
        )
        raise
