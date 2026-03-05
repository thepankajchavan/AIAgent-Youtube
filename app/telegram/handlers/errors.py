"""Global error handler for unhandled exceptions."""

from telegram import Update
from telegram.ext import ContextTypes
from loguru import logger


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors in bot commands."""
    logger.error("Update {} caused error: {}", update, context.error)

    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ An error occurred.\n\n"
            "Please try again or use `/help` for usage instructions."
        )
