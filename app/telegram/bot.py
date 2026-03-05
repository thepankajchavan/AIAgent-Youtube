"""Telegram bot initialization and configuration."""

from telegram import Update
from telegram.ext import Application, CommandHandler, TypeHandler
from loguru import logger

from app.core.config import get_settings
from app.telegram.middleware import auth_middleware, rate_limit_middleware
from app.telegram.handlers.start import start_handler, help_handler
from app.telegram.handlers.video import video_handler, video_long_handler
from app.telegram.handlers.status import status_handler, list_handler
from app.telegram.handlers.admin import cancel_handler, retry_handler
from app.telegram.handlers.errors import error_handler

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

    # Global error handler
    app.add_error_handler(error_handler)

    logger.info("Bot application configured successfully")
    return app
