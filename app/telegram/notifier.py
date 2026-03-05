"""Telegram notification service - subscribes to Redis pub/sub for status updates."""

import asyncio
import json

import redis.asyncio as aioredis
from loguru import logger
from telegram import Bot
from telegram.error import RetryAfter, TelegramError

from app.core.config import get_settings

settings = get_settings()


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
                await handle_status_update(bot, event)
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


async def handle_status_update(bot: Bot, event: dict):
    """Edit Telegram message with new status."""
    project_id = event["project_id"]
    status = event["status"]
    chat_id = event["telegram_chat_id"]
    message_id = event["telegram_message_id"]
    extra = event.get("extra", {})

    text = format_status_message(status, project_id, extra)

    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=text, parse_mode="Markdown"
        )
        logger.debug("Notification sent — project={} status={}", project_id, status)

    except RetryAfter as e:
        logger.warning("Rate limited — retry after {} seconds", e.retry_after)
        await asyncio.sleep(e.retry_after)
        # Retry once
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, parse_mode="Markdown"
            )
        except TelegramError as retry_exc:
            logger.error("Retry failed: {}", retry_exc)

    except TelegramError as exc:
        logger.warning("Telegram error (will retry on next update): {}", exc)
        # Don't raise - next status update will try again


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

    text = f"{emoji} *{message}*\n\n\U0001f194 Project: `{project_id}`"

    if status == "COMPLETED" and extra.get("youtube_url"):
        text += f"\n\n\U0001f517 [Watch on YouTube]({extra['youtube_url']})"

    if status == "FAILED" and extra.get("error"):
        text += f"\n\n\u274c Error: {extra['error']}"

    return text
