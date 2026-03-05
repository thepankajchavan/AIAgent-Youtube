"""Start and help command handlers."""

from telegram import Update
from telegram.ext import ContextTypes


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "👋 *Welcome to YouTube Shorts Automation Bot!*\n\n"
        "I can generate YouTube Shorts videos automatically from any topic.\n\n"
        "*Available Commands:*\n"
        "• `/video <topic>` - Generate a short video (9:16)\n"
        "• `/video_long <topic>` - Generate long video (16:9)\n"
        "• `/status <id>` - Check project status\n"
        "• `/list` - Your recent projects\n"
        "• `/cancel <id>` - Cancel running project\n"
        "• `/retry <id>` - Retry failed project\n"
        "• `/help` - Show this message\n\n"
        "*Example:*\n"
        "`/video 5 amazing facts about black holes`",
        parse_mode="Markdown"
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    await start_handler(update, context)
