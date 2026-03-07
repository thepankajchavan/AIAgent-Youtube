"""Telegram bot entry point - run with: python telegram_bot.py"""

import asyncio
from loguru import logger

from app.telegram.bot import build_bot_application
from app.telegram.notifier import run_notifier
from app.core.logging import setup_logging


async def main():
    """Run the Telegram bot and notifier together."""
    setup_logging()
    logger.info("Starting Telegram bot + notifier...")

    app = build_bot_application()

    # Initialize and start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # Start the notifier as a background task (listens for Redis pub/sub events)
    notifier_task = asyncio.create_task(run_notifier())
    logger.info("Bot + notifier running. Press Ctrl+C to stop.")

    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Stopping bot...")
    finally:
        notifier_task.cancel()
        try:
            await notifier_task
        except asyncio.CancelledError:
            pass
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("Bot stopped cleanly")


if __name__ == "__main__":
    asyncio.run(main())
