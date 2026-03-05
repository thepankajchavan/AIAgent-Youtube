"""Admin command handlers - cancel and retry."""

import httpx
from telegram import Update
from telegram.ext import ContextTypes

from app.core.config import get_settings

settings = get_settings()


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel <project_id> command."""
    if not update.message or not context.args:
        await update.message.reply_text(
            "Usage: `/cancel <project_id>`",
            parse_mode="Markdown"
        )
        return

    project_id = context.args[0]

    try:
        async with httpx.AsyncClient() as client:
            # Get project to find celery_task_id
            response = await client.get(
                f"{settings.api_base_url}/api/v1/projects/{project_id}",
                timeout=5.0
            )
            response.raise_for_status()
            project = response.json()

            celery_task_id = project.get("celery_task_id")
            if not celery_task_id:
                await update.message.reply_text("❌ Project has no active task.")
                return

            # Revoke task
            response = await client.post(
                f"{settings.api_base_url}/api/v1/system/tasks/{celery_task_id}/revoke",
                params={"terminate": True},
                timeout=5.0
            )
            response.raise_for_status()

            await update.message.reply_text(
                f"✅ Task cancelled for project `{project_id}`",
                parse_mode="Markdown"
            )

    except Exception as exc:
        await update.message.reply_text(f"❌ Failed to cancel: {exc}")


async def retry_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /retry <project_id> command."""
    if not update.message or not context.args:
        await update.message.reply_text(
            "Usage: `/retry <project_id>`",
            parse_mode="Markdown"
        )
        return

    project_id = context.args[0]

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.api_base_url}/api/v1/projects/{project_id}/retry",
                timeout=10.0
            )
            response.raise_for_status()

            await update.message.reply_text(
                f"✅ Retry initiated for project `{project_id}`\n\n"
                "Watch your status message for updates.",
                parse_mode="Markdown"
            )

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            await update.message.reply_text("❌ Only FAILED projects can be retried.")
        elif exc.response.status_code == 404:
            await update.message.reply_text("❌ Project not found.")
        else:
            await update.message.reply_text(f"❌ Error: {exc.response.text}")
    except Exception as exc:
        await update.message.reply_text(f"❌ Error: {exc}")
