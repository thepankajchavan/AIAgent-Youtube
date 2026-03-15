"""Telegram bot initialization and configuration."""

from loguru import logger
from telegram import Update
from telegram.ext import Application, CommandHandler, TypeHandler

from app.core.config import get_settings
from app.telegram.handlers.admin import cancel_handler, retry_handler
from app.telegram.handlers.analytics import (
    analytics_handler,
    patterns_handler,
    trends_handler,
)
from app.telegram.handlers.errors import error_handler
from app.telegram.handlers.start import help_handler, start_handler
from app.telegram.handlers.status import list_handler, status_handler
from app.telegram.handlers.video import autopilot_handler, video_handler, video_long_handler
from app.telegram.middleware import auth_middleware, rate_limit_middleware

settings = get_settings()


def build_bot_application() -> Application:
    """Build and configure the Telegram bot application."""
    app = Application.builder().token(settings.telegram_bot_token).build()

    # Middleware: auth check runs first (group -2), rate limit second (group -1)
    app.add_handler(TypeHandler(type=Update, callback=auth_middleware), group=-2)
    app.add_handler(TypeHandler(type=Update, callback=rate_limit_middleware), group=-1)

    # Register command handlers (default group 0)
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("video", video_handler))
    app.add_handler(CommandHandler("video_long", video_long_handler))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("list", list_handler))
    app.add_handler(CommandHandler("cancel", cancel_handler))
    app.add_handler(CommandHandler("retry", retry_handler))
    app.add_handler(CommandHandler("trends", trends_handler))
    app.add_handler(CommandHandler("analytics", analytics_handler))
    app.add_handler(CommandHandler("patterns", patterns_handler))
    app.add_handler(CommandHandler("autopilot", autopilot_handler))

    # Global error handler
    app.add_error_handler(error_handler)

    logger.info("Bot application configured successfully")
    return app
