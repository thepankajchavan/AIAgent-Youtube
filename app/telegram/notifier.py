"""Telegram notification service - subscribes to Redis pub/sub for status updates.

Features:
  - Edit-in-place: intermediate statuses update the SAME message
  - Video preview: COMPLETED sends the video file to the chat
  - Caption failure: shows warning when captions fail
  - Upload progress: shows percentage in uploading status
"""

import asyncio
import json
from pathlib import Path

import redis.asyncio as aioredis
from loguru import logger
from telegram import Bot
from telegram.error import RetryAfter, TelegramError
from telegram.helpers import escape_markdown

from app.core.config import get_settings

settings = get_settings()

# Max video file size Telegram accepts (50 MB)
_MAX_VIDEO_SIZE = 50 * 1024 * 1024


# ── Redis message-ID tracking ──────────────────────────────────


async def _get_status_message_id(
    redis_client: aioredis.Redis, project_id: str
) -> int | None:
    """Get the Telegram message ID for a project's status message."""
    key = f"project:{project_id}:status_msg_id"
    value = await redis_client.get(key)
    return int(value) if value else None


async def _set_status_message_id(
    redis_client: aioredis.Redis, project_id: str, message_id: int
) -> None:
    """Store the Telegram message ID for a project's status message."""
    key = f"project:{project_id}:status_msg_id"
    await redis_client.set(key, message_id, ex=3600)  # 1-hour TTL


# ── Main notifier loop ────────────────────────────────────────


async def run_notifier():
    """Subscribe to async Redis pub/sub and send Telegram notifications."""
    bot = Bot(token=settings.telegram_bot_token)
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("project:status:updates")

    logger.info("Telegram notifier started - listening for events")

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                event = json.loads(message["data"])
                await handle_status_update(bot, event, redis_client)
            except Exception as exc:
                logger.error("Failed to handle event: {}", exc)
                # Continue processing other events
    except asyncio.CancelledError:
        logger.info("Notifier cancelled")
    except KeyboardInterrupt:
        logger.info("Notifier stopping...")
    finally:
        await pubsub.close()
        await redis_client.close()


# ── Status update handler ─────────────────────────────────────


async def handle_status_update(
    bot: Bot, event: dict, redis_client: aioredis.Redis
):
    """Handle a pipeline status update — edit existing message or send new one."""
    project_id = event["project_id"]
    status = event["status"]
    chat_id = event["telegram_chat_id"]
    extra = event.get("extra", {})

    text = format_status_message(status, project_id, extra)

    # Show YouTube link preview only for COMPLETED status
    disable_preview = status != "COMPLETED"

    try:
        existing_msg_id = await _get_status_message_id(redis_client, project_id)

        if status == "COMPLETED":
            # Edit status message to "Done!" then send video as new message
            if existing_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=existing_msg_id,
                        text=text,
                        parse_mode="Markdown",
                        disable_web_page_preview=disable_preview,
                    )
                except TelegramError:
                    # Edit failed, send new message
                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="Markdown",
                        disable_web_page_preview=disable_preview,
                    )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown",
                    disable_web_page_preview=disable_preview,
                )

            # Send video file preview if available
            await _send_video_preview(bot, chat_id, extra)

        elif status == "FAILED":
            # Edit status message with error or send new
            if existing_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=existing_msg_id,
                        text=text,
                        parse_mode="Markdown",
                    )
                except TelegramError:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="Markdown",
                    )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown",
                )

        elif existing_msg_id:
            # Intermediate status — edit existing message
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=existing_msg_id,
                    text=text,
                    parse_mode="Markdown",
                )
            except TelegramError:
                # If edit fails, send new and track the new ID
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown",
                )
                await _set_status_message_id(redis_client, project_id, msg.message_id)

        else:
            # First status event — send new message and store ID
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
            )
            await _set_status_message_id(redis_client, project_id, msg.message_id)

        logger.debug("Notification sent — project={} status={}", project_id, status)

    except RetryAfter as e:
        logger.warning("Rate limited — retry after {} seconds", e.retry_after)
        await asyncio.sleep(e.retry_after)
        # Retry once
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                disable_web_page_preview=disable_preview,
            )
        except TelegramError as retry_exc:
            logger.error("Retry failed: {}", retry_exc)

    except TelegramError as exc:
        logger.warning("Telegram send failed: {}", exc)


# ── Video preview helper ──────────────────────────────────────


async def _send_video_preview(bot: Bot, chat_id: int | str, extra: dict):
    """Send the final video file as a Telegram video message."""
    output_path_str = extra.get("output_path")
    if not output_path_str:
        return

    video_path = Path(output_path_str)
    if not video_path.exists():
        logger.debug("Video file not found for preview: {}", video_path)
        return

    if video_path.stat().st_size > _MAX_VIDEO_SIZE:
        logger.info(
            "Video too large for Telegram preview ({:.1f}MB > 50MB)",
            video_path.stat().st_size / (1024 * 1024),
        )
        return

    try:
        youtube_url = extra.get("youtube_url", "")
        caption = f"\U0001f3ac Your video is ready!"
        if youtube_url:
            caption += f"\n\U0001f517 {youtube_url}"

        with open(video_path, "rb") as video_file:
            await bot.send_video(
                chat_id=chat_id,
                video=video_file,
                caption=caption,
                supports_streaming=True,
            )
        logger.info("Video preview sent to chat {}", chat_id)
    except TelegramError as exc:
        logger.warning("Failed to send video preview: {}", exc)


# ── Message formatter ─────────────────────────────────────────


def format_status_message(status: str, project_id: str, extra: dict) -> str:
    """Format status message with emoji and details."""
    status_map = {
        "SCRIPT_GENERATING": ("\u270d\ufe0f", "Generating script..."),
        "SCENE_SPLITTING": ("\U0001f3ac", "Planning visual scenes..."),
        "AUDIO_GENERATING": ("\U0001f399\ufe0f", "Generating voiceover..."),
        "VIDEO_GENERATING": ("\U0001f3a5", "Generating video clips..."),
        "ASSEMBLING": ("\U0001f527", "Assembling final video..."),
        "UPLOADING": ("\U0001f4e4", "Uploading to YouTube..."),
        "COMPLETED": ("\u2705", "Done!"),
        "FAILED": ("\u274c", "Failed"),
    }

    emoji, message = status_map.get(status, ("\U0001f504", status))

    # Upload progress
    progress = extra.get("progress")
    if status == "UPLOADING" and progress:
        message = f"Uploading to YouTube... ({progress}%)"

    # Retry indicator
    retry_num = extra.get("retry")
    if retry_num:
        message = f"{message.rstrip('...')} (retry {retry_num})..."

    text = f"{emoji} *{message}*\n\n\U0001f194 Project: `{project_id}`"

    if status == "COMPLETED" and extra.get("youtube_url"):
        text += f"\n\n\U0001f517 [Watch on YouTube]({extra['youtube_url']})"

    if status == "FAILED" and extra.get("error"):
        safe_error = escape_markdown(str(extra['error']), version=1)
        text += f"\n\n\u274c Error: {safe_error}"

    # Caption failure warning
    if extra.get("captions") == "failed":
        text += "\n\n\u26a0\ufe0f Captions unavailable (Whisper API error)"

    return text
