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


VALID_CREATIVE_PRESETS = {"minimal", "cinematic", "energetic", "auto"}
VALID_PACING_STYLES = {"auto", "uniform", "dramatic", "energetic"}
VALID_THUMB_STYLES = {"auto", "ai", "frame"}


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


def _parse_flag(raw_args: str, flag_name: str, valid_values: set) -> tuple[str | None, str]:
    """Generic flag parser for --flag value patterns."""
    match = re.search(rf"--{flag_name}\s+(\w+)", raw_args, re.IGNORECASE)
    if match:
        value = match.group(1).lower()
        topic = raw_args[:match.start()].strip() + " " + raw_args[match.end():].strip()
        topic = topic.strip()
        if value in valid_values:
            return value, topic
    return None, raw_args


def _parse_style_flag(raw_args: str) -> tuple[str | None, str]:
    """Parse optional --style flag from user input."""
    return _parse_flag(raw_args, "style", VALID_CREATIVE_PRESETS)


def _parse_lang_flag(raw_args: str) -> tuple[str | None, str]:
    """Parse optional --lang flag (e.g. --lang es)."""
    from app.services.translation_service import SUPPORTED_LANGUAGES, LANGUAGE_ALIASES
    valid = set(SUPPORTED_LANGUAGES.keys()) | set(LANGUAGE_ALIASES.keys())
    code, topic = _parse_flag(raw_args, "lang", valid)
    if code:
        from app.services.translation_service import resolve_language_code
        code = resolve_language_code(code)
    return code, topic


def _parse_voice_flag(raw_args: str) -> tuple[str | None, str]:
    """Parse optional --voice flag (accepts voice name or ID)."""
    match = re.search(r"--voice\s+(\S+)", raw_args, re.IGNORECASE)
    if match:
        voice = match.group(1)
        topic = raw_args[:match.start()].strip() + " " + raw_args[match.end():].strip()
        return voice, topic.strip()
    return None, raw_args


def _parse_pace_flag(raw_args: str) -> tuple[str | None, str]:
    """Parse optional --pace flag."""
    return _parse_flag(raw_args, "pace", VALID_PACING_STYLES)


def _parse_thumb_flag(raw_args: str) -> tuple[str | None, str]:
    """Parse optional --thumb flag."""
    return _parse_flag(raw_args, "thumb", VALID_THUMB_STYLES)


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

    # Parse optional flags
    creative_preset, raw_args = _parse_style_flag(raw_args)
    language, raw_args = _parse_lang_flag(raw_args)
    voice_id, raw_args = _parse_voice_flag(raw_args)
    pacing_style, raw_args = _parse_pace_flag(raw_args)
    thumb_style, raw_args = _parse_thumb_flag(raw_args)

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
    style_text = f"🎬 Style: {creative_preset}\n" if creative_preset else ""
    lang_text = f"🌍 Language: {language}\n" if language and language != "en" else ""

    safe_topic = escape_markdown(topic, version=1)

    # Send acknowledgment message first (before API call to avoid race condition)
    ack_msg = await update.message.reply_text(
        f"{format_emoji} *Video generation started!*\n\n"
        f"📝 Topic: {safe_topic}\n"
        f"📐 Format: {format_text}\n"
        f"{duration_text}"
        f"{style_text}"
        f"{lang_text}\n"
        f"_Progress updates will follow below..._",
        parse_mode="Markdown",
    )

    # Resolve visual strategy from settings
    strategy = settings.ai_video_strategy
    if strategy == "ai_images":
        visual_strategy = strategy if settings.ai_images_enabled else "stock_only"
    else:
        visual_strategy = strategy if settings.ai_video_enabled else "stock_only"

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
            if creative_preset is not None:
                body["creative_preset"] = creative_preset
            if language is not None:
                body["language"] = language
            if voice_id is not None:
                body["voice_id"] = voice_id
            if pacing_style is not None:
                body["pacing_style"] = pacing_style
            if thumb_style is not None:
                body["thumbnail_style"] = thumb_style

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


async def autopilot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /autopilot on|off|status|queue command."""
    if not update.message:
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage:\n"
            "`/autopilot on` — Enable auto-scheduling\n"
            "`/autopilot off` — Disable auto-scheduling\n"
            "`/autopilot status` — Show stats\n"
            "`/autopilot queue` — Show upcoming queue",
            parse_mode="Markdown",
        )
        return

    action = args[0].lower()

    if action == "status":
        from app.services.auto_schedule_service import SchedulingBrain

        from app.core.config import get_settings as _get_settings
        _cfg = _get_settings()
        schedule_times = getattr(_cfg, "auto_schedule_times", "10:00,18:00")
        times_display = ", ".join(t.strip() + " UTC" for t in schedule_times.split(","))

        brain = SchedulingBrain()
        stats = await brain.get_stats()
        health = stats.get("health_status", "unknown")

        await update.message.reply_text(
            f"*Auto-Pilot Status*\n\n"
            f"Enabled: {'Yes' if stats['enabled'] else 'No'}\n"
            f"Schedule: {times_display}\n"
            f"Today: {stats['today_count']}/{stats['max_daily']} videos\n"
            f"Remaining: {stats['remaining_today']}\n"
            f"Health: {health}\n"
            f"Niche: {stats['niche']}\n"
            f"Strategy: {stats['visual_strategy']}",
            parse_mode="Markdown",
        )

    elif action in ("on", "off"):
        from app.services.auto_schedule_service import SchedulingBrain

        brain = SchedulingBrain()
        enabled = action == "on"
        try:
            await brain.set_enabled(enabled)
            await brain.log_decision(
                action="toggle_changed",
                topic=None,
                reason=f"Autopilot {'enabled' if enabled else 'disabled'} via Telegram by user {update.effective_user.id}",
            )
            await update.message.reply_text(
                f"Auto-pilot {'enabled' if enabled else 'disabled'} (takes effect immediately).",
                parse_mode="Markdown",
            )
        except Exception as exc:
            await update.message.reply_text(
                f"Failed to toggle autopilot: {exc}",
                parse_mode="Markdown",
            )

    elif action == "queue":
        from app.services.auto_schedule_service import SchedulingBrain

        brain = SchedulingBrain()
        queue = await brain.get_queue(limit=5)
        if not queue:
            await update.message.reply_text("No topics in queue.", parse_mode="Markdown")
            return

        lines = ["*Upcoming Queue*\n"]
        for i, item in enumerate(queue, 1):
            lines.append(
                f"{i}. {item['topic'][:40]}\n"
                f"   Score: {item['quality_score']:.0f} | "
                f"Time: {item['scheduled_for']}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    else:
        await update.message.reply_text(
            "Unknown action. Use: `/autopilot on|off|status|queue`",
            parse_mode="Markdown",
        )
