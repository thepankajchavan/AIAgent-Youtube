"""Status checking command handlers."""

import httpx
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from app.core.config import get_settings
from app.workers.db import get_sync_db
from app.models.video import VideoProject

settings = get_settings()


async def status_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status <project_id> command."""
    if not update.message or not context.args:
        await update.message.reply_text(
            "Usage: `/status <project_id>`\n\n"
            "Example: `/status 123e4567-e89b-12d3-a456-426614174000`",
            parse_mode="Markdown"
        )
        return

    project_id = context.args[0]

    # Fetch from API
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.api_base_url}/api/v1/projects/{project_id}",
                timeout=5.0
            )
            response.raise_for_status()
            project = response.json()

        # Format response
        status_emoji = {
            "completed": "✅",
            "failed": "❌",
            "pending": "⏳",
            "script_generating": "✍️",
            "audio_generating": "🎙️",
            "video_generating": "🎥",
            "assembling": "🔧",
            "uploading": "📤",
        }.get(project["status"], "🔄")

        text = (
            f"{status_emoji} *Project Status*\n\n"
            f"🆔 ID: `{project['id']}`\n"
            f"📝 Topic: {project['topic']}\n"
            f"📊 Status: {project['status']}\n"
            f"📅 Created: {project['created_at'][:10]}\n"
        )

        if project.get("youtube_url"):
            text += f"\n🔗 [Watch on YouTube]({project['youtube_url']})"

        if project.get("error_message"):
            text += f"\n\n❌ Error: {project['error_message']}"

        await update.message.reply_text(text, parse_mode="Markdown")

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            await update.message.reply_text("❌ Project not found.")
        else:
            await update.message.reply_text(f"❌ Error: {exc.response.text}")
    except Exception as exc:
        await update.message.reply_text(f"❌ Error: {exc}")


async def list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /list command - show user's recent projects."""
    user_id = update.effective_user.id

    # Query from database
    with get_sync_db() as db:
        stmt = (
            select(VideoProject)
            .where(VideoProject.telegram_user_id == user_id)
            .order_by(VideoProject.created_at.desc())
            .limit(10)
        )
        projects = db.execute(stmt).scalars().all()

    if not projects:
        await update.message.reply_text("You have no projects yet.\n\nUse `/video <topic>` to create one!", parse_mode="Markdown")
        return

    # Format list
    lines = ["*Your Recent Projects:*\n"]
    for p in projects:
        status_emoji = {
            "completed": "✅",
            "failed": "❌",
            "pending": "⏳",
        }.get(p.status.value, "🔄")

        topic_preview = p.topic[:40] + "..." if len(p.topic) > 40 else p.topic

        lines.append(
            f"{status_emoji} `{p.id}`\n"
            f"   {topic_preview}\n"
            f"   {p.status.value} • {p.created_at.strftime('%m/%d %H:%M')}\n"
        )

    lines.append(f"\nUse `/status <id>` to see details.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
