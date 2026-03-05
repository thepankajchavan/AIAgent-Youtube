"""Video generation command handlers."""

import httpx
from telegram import Update
from telegram.ext import ContextTypes
from loguru import logger

from app.core.config import get_settings
from app.workers.db import get_sync_db
from app.models.video import VideoProject

settings = get_settings()


async def video_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /video <topic> command - generates 9:16 short."""
    await _generate_video(update, context, video_format="short")


async def video_long_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /video_long <topic> command - generates 16:9 long video."""
    await _generate_video(update, context, video_format="long")


async def _generate_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    video_format: str
):
    """Common logic for video generation."""
    if not update.message or not context.args:
        await update.message.reply_text(
            f"Usage: `/video{'_long' if video_format == 'long' else ''} <topic>`\n\n"
            "Example: `/video 5 facts about Mars`",
            parse_mode="Markdown"
        )
        return

    topic = " ".join(context.args)

    # Validate input
    if len(topic) < 3:
        await update.message.reply_text("❌ Topic must be at least 3 characters.")
        return

    if len(topic) > 512:
        await update.message.reply_text("❌ Topic too long (max 512 characters).")
        return

    # Send initial status message
    format_emoji = "📱" if video_format == "short" else "🖥️"
    format_text = "9:16 Short" if video_format == "short" else "16:9 Long"

    status_msg = await update.message.reply_text(
        f"{format_emoji} *Generating video...*\n\n"
        f"📝 Topic: {topic}\n"
        f"📐 Format: {format_text}\n"
        f"⏳ Status: Initializing...",
        parse_mode="Markdown"
    )

    # Resolve visual strategy from settings
    visual_strategy = settings.ai_video_strategy if settings.ai_video_enabled else "stock_only"

    # Call FastAPI pipeline endpoint
    try:
        headers = {}
        if settings.api_auth_enabled and hasattr(settings, "telegram_internal_api_key") and settings.telegram_internal_api_key:
            headers["X-API-Key"] = settings.telegram_internal_api_key

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.api_base_url}/api/v1/pipeline",
                json={
                    "topic": topic,
                    "video_format": video_format,
                    "provider": "openai",
                    "skip_upload": False,
                    "visual_strategy": visual_strategy,
                },
                headers=headers,
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()

        project_id = data["project_id"]

        # Update database with Telegram tracking info
        with get_sync_db() as db:
            project = db.get(VideoProject, project_id)
            if project:
                project.telegram_user_id = update.effective_user.id
                project.telegram_chat_id = update.effective_chat.id
                project.telegram_message_id = status_msg.message_id
                # commit happens on context exit

        # Update message with project ID
        await status_msg.edit_text(
            f"{format_emoji} *Generating video...*\n\n"
            f"📝 Topic: {topic}\n"
            f"📐 Format: {format_text}\n"
            f"🆔 Project: `{project_id}`\n"
            f"✍️ Status: Generating script...",
            parse_mode="Markdown"
        )

        logger.info(
            "Video requested — user={} chat={} project={}",
            update.effective_user.id,
            update.effective_chat.id,
            project_id
        )

    except httpx.HTTPStatusError as exc:
        logger.error("API error: {}", exc)
        await status_msg.edit_text(
            f"❌ *Failed to start pipeline*\n\n"
            f"Error: {exc.response.text}",
            parse_mode="Markdown"
        )
    except Exception as exc:
        logger.error("Unexpected error: {}", exc)
        await status_msg.edit_text(
            "❌ *Unexpected error*\n\n"
            "Please try again later.",
            parse_mode="Markdown"
        )
