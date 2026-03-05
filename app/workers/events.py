"""Event emission for status updates via Redis pub/sub."""

import json
from redis import Redis
from loguru import logger

from app.core.config import get_settings

settings = get_settings()
redis_client = Redis.from_url(settings.redis_url)


def emit_status_update(
    project_id: str,
    status: str,
    telegram_user_id: int | None = None,
    telegram_chat_id: int | None = None,
    telegram_message_id: int | None = None,
    extra: dict | None = None,
) -> None:
    """Emit project status update to Redis pub/sub for Telegram notifications."""
    if telegram_message_id is None:
        return  # No Telegram notification needed

    event = {
        "project_id": project_id,
        "status": status,
        "telegram_user_id": telegram_user_id,
        "telegram_chat_id": telegram_chat_id,
        "telegram_message_id": telegram_message_id,
        "extra": extra or {},
    }

    try:
        redis_client.publish("project:status:updates", json.dumps(event))
        logger.debug("Event emitted — project={} status={}", project_id, status)
    except Exception as exc:
        logger.error("Failed to emit event: {}", exc)
        # Don't raise — worker should not fail due to notification issues
