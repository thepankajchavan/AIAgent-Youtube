"""Middleware for authentication and rate limiting."""

from datetime import UTC, datetime, timedelta

from loguru import logger
from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.models.telegram_user import TelegramUser
from app.workers.db import get_sync_db


async def auth_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Basic authentication check (allowlist).

    Runs in handler group -2 (before all other handlers).
    Raises ApplicationHandlerStop to cleanly block unauthorized users.
    """
    if not update.effective_user:
        return

    user_id = update.effective_user.id

    # Get or create user
    with get_sync_db() as db:
        user = db.get(TelegramUser, user_id)

        if user is None:
            # First time user - create record
            user = TelegramUser(
                user_id=user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name,
                is_allowed=False,  # Default: not allowed
            )
            db.add(user)
            # commit happens on context exit

        # Check allowlist (allow /start and /help without authorization)
        if update.message and update.message.text:
            command = update.message.text.split()[0].lower()
            if command in ("/start", "/help"):
                return

        if not user.is_allowed and not user.is_admin:
            if update.effective_message:
                await update.effective_message.reply_text(
                    "Access Denied\n\n"
                    "You are not authorized to use this bot.\n"
                    "Contact the administrator for access.",
                )
            logger.warning("Unauthorized user: {} ({})", user_id, user.username)
            raise ApplicationHandlerStop()


async def rate_limit_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rate limiting for video commands (5 per hour).

    Runs in handler group -1 (after auth, before command handlers).
    Raises ApplicationHandlerStop to cleanly block rate-limited users.
    """
    if not update.effective_user or not update.message:
        return

    # Only rate limit video generation commands
    if not update.message.text or not update.message.text.startswith(("/video",)):
        return

    user_id = update.effective_user.id

    with get_sync_db() as db:
        user = db.get(TelegramUser, user_id)

        if user is None or user.is_admin:
            return  # Admins bypass rate limits

        # Check if rate limit window expired
        now = datetime.now(UTC)
        if now >= user.rate_limit_reset_at:
            # Reset counter
            user.videos_this_hour = 0
            user.rate_limit_reset_at = now + timedelta(hours=1)

        # Check limit
        if user.videos_this_hour >= 5:
            time_left = user.rate_limit_reset_at - now
            minutes = max(1, int(time_left.total_seconds() / 60))

            await update.message.reply_text(
                f"Rate Limit Reached\n\n"
                f"You've used all 5 videos this hour.\n"
                f"Try again in {minutes} minutes.",
            )
            raise ApplicationHandlerStop()

        # Increment counter
        user.videos_this_hour += 1
        user.total_videos_requested += 1
        user.last_command_at = now
        # commit happens on context exit
