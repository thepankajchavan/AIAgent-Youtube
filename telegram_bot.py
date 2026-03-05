"""Telegram bot entry point - run with: python telegram_bot.py"""

import asyncio
from loguru import logger

from app.telegram.bot import build_bot_application
from app.core.logging import setup_logging


async def main():
    """Run the Telegram bot in polling mode."""
    setup_logging()
    logger.info("🤖 Starting Telegram bot...")

    app = build_bot_application()

    # Initialize and start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    logger.info("✅ Bot is running. Press Ctrl+C to stop.")

    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("🛑 Stopping bot...")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("✅ Bot stopped cleanly")


if __name__ == "__main__":
    asyncio.run(main())
