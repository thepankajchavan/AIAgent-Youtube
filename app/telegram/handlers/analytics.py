"""Telegram handlers for self-improvement feedback loop commands."""

from __future__ import annotations

from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes


async def trends_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /trends command — shows current trending topics."""
    if not update.message:
        return

    try:
        from app.services.trend_service import TrendService

        service = TrendService()
        trends = await service.get_current_trends(limit=10)

        if not trends:
            await update.message.reply_text(
                "No trending topics available right now.\n\n"
                "Trends are collected periodically. "
                "An admin can trigger collection with /collect_trends."
            )
            return

        lines = []
        for i, trend in enumerate(trends, 1):
            category_str = f" [{trend['category']}]" if trend.get("category") else ""
            lines.append(
                f"{i}. {trend['topic']} (score: {trend['trend_score']:.0f})"
                f" — {trend['source']}{category_str}"
            )

        fetched_at = trends[0].get("fetched_at", "unknown")
        text = (
            "Current Trending Topics:\n\n"
            + "\n".join(lines)
            + f"\n\nLast updated: {fetched_at}"
        )

        await update.message.reply_text(text)

    except Exception as exc:
        logger.error("Error in /trends handler: {}", exc)
        await update.message.reply_text("Failed to fetch trends. Please try again later.")


async def analytics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /analytics command — shows channel performance summary."""
    if not update.message:
        return

    try:
        from app.services.analytics_service import AnalyticsService

        service = AnalyticsService()
        summary = await service.get_performance_summary(days=30)

        best = summary.get("best_video")
        best_str = (
            f'"{best["topic"]}" — {best["views"]:,} views'
            if best
            else "N/A"
        )

        text = (
            "Performance Summary (Last 30 days):\n\n"
            f"Total Views: {summary['total_views']:,}\n"
            f"Avg Views/Video: {summary['avg_views']:,.1f}\n"
            f"Avg Retention: {summary['avg_retention']:.1f}%\n"
            f"Avg CTR: {summary['avg_ctr']:.2f}%\n"
            f"Best Video: {best_str}\n"
            f"Snapshots: {summary['snapshot_count']}"
        )

        await update.message.reply_text(text)

    except Exception as exc:
        logger.error("Error in /analytics handler: {}", exc)
        await update.message.reply_text(
            "Failed to fetch analytics. Please try again later."
        )


async def patterns_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /patterns command — shows discovered performance patterns."""
    if not update.message:
        return

    try:
        from app.services.pattern_service import PatternService

        service = PatternService()
        patterns = await service.get_active_patterns(min_confidence=0.5)

        if not patterns:
            await update.message.reply_text(
                "No performance patterns discovered yet.\n\n"
                "Patterns are analyzed weekly once enough video data is collected."
            )
            return

        lines = []
        for i, pattern in enumerate(patterns, 1):
            lines.append(
                f"{i}. [{pattern['pattern_type']}] {pattern['description']} "
                f"(confidence: {pattern['confidence_score']:.0%})"
            )

        text = "Learned Patterns:\n\n" + "\n".join(lines)
        await update.message.reply_text(text)

    except Exception as exc:
        logger.error("Error in /patterns handler: {}", exc)
        await update.message.reply_text(
            "Failed to fetch patterns. Please try again later."
        )
