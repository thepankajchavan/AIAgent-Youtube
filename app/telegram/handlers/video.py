"""Video generation command handlers."""

import re

import httpx
from loguru import logger
from telegram import Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from app.core.config import get_settings
from app.models.video import VideoProject
from app.workers.db import get_sync_db

settings = get_settings()


def _parse_duration_and_topic(raw_args: str) -> tuple[int | None, str]:
    """Parse optional duration prefix from user input.

    Examples:
        "30s Iran war update"  → (30, "Iran war update")
        "60sec black holes"    → (60, "black holes")
        "Mars facts"           → (None, "Mars facts")
    """
    match = re.match(r"^(\d{1,3})\s*s(?:ec)?\s+(.+)", raw_args, re.IGNORECASE)
    if match:
        duration = int(match.group(1))
        topic = match.group(2)
        # Clamp to reasonable range: 15-120 seconds
        duration = max(15, min(120, duration))
        return duration, topic
    return None, raw_args


async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /video <topic> command - generates 9:16 short."""
    await _generate_video(update, context, video_format="short")


async def video_long_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /video_long <topic> command - generates 16:9 long video."""
    await _generate_video(update, context, video_format="long")


async def _generate_video(update: Update, context: ContextTypes.DEFAULT_TYPE, video_format: str):
    """Common logic for video generation."""
    if not update.message or not context.args:
        await update.message.reply_text(
            f"Usage: `/video{'_long' if video_format == 'long' else ''} <topic>`\n\n"
            "Example: `/video 5 facts about Mars`",
            parse_mode="Markdown",
        )
        return

    raw_args = " ".join(context.args)

    # Parse optional duration prefix (e.g. "30s topic" or "60sec topic")
    target_duration, topic = _parse_duration_and_topic(raw_args)

    # Validate input
    if len(topic) < 3:
        await update.message.reply_text("❌ Topic must be at least 3 characters.")
        return

    if len(topic) > 512:
        await update.message.reply_text("❌ Topic too long (max 512 characters).")
        return

    format_emoji = "📱" if video_format == "short" else "🖥️"
    format_text = "9:16 Short" if video_format == "short" else "16:9 Long"
    duration_text = f"⏱️ Target: {target_duration}s\n" if target_duration else ""

    safe_topic = escape_markdown(topic, version=1)

    # Send acknowledgment message first (before API call to avoid race condition)
    ack_msg = await update.message.reply_text(
        f"{format_emoji} *Video generation started!*\n\n"
        f"📝 Topic: {safe_topic}\n"
        f"📐 Format: {format_text}\n"
        f"{duration_text}\n"
        f"_Progress updates will follow below..._",
        parse_mode="Markdown",
    )

    # Resolve visual strategy from settings
    visual_strategy = settings.ai_video_strategy if settings.ai_video_enabled else "stock_only"

    # Call FastAPI pipeline endpoint
    try:
        headers = {}
        if (
            settings.api_auth_enabled
            and hasattr(settings, "telegram_internal_api_key")
            and settings.telegram_internal_api_key
        ):
            headers["X-API-Key"] = settings.telegram_internal_api_key

        async with httpx.AsyncClient() as client:
            body = {
                "topic": topic,
                "video_format": video_format,
                "provider": "openai",
                "skip_upload": False,
                "visual_strategy": visual_strategy,
            }
            if target_duration is not None:
                body["target_duration"] = target_duration

            response = await client.post(
                f"{settings.api_base_url}/api/v1/pipeline",
                json=body,
                headers=headers,
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

        project_id = data["project_id"]

        # Store Telegram tracking info so workers can emit notifications
        with get_sync_db() as db:
            project = db.get(VideoProject, project_id)
            if project:
                project.telegram_user_id = update.effective_user.id
                project.telegram_chat_id = update.effective_chat.id
                project.telegram_message_id = ack_msg.message_id
                # commit happens on context exit

        logger.info(
            "Video requested — user={} chat={} project={}",
            update.effective_user.id,
            update.effective_chat.id,
            project_id,
        )

    except httpx.HTTPStatusError as exc:
        logger.error("API error: {}", exc)
        safe_error = escape_markdown(str(exc.response.text), version=1)
        await ack_msg.edit_text(
            f"❌ *Failed to start pipeline*\n\nError: {safe_error}",
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.error("Unexpected error: {}", exc)
        await ack_msg.edit_text(
            "❌ *Unexpected error*\n\nPlease try again later.", parse_mode="Markdown"
        )
