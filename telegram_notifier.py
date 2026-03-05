"""Telegram notifier service entry point - run with: python telegram_notifier.py"""

import asyncio
from loguru import logger

from app.telegram.notifier import run_notifier
from app.core.logging import setup_logging


async def main():
    """Run the Telegram notification service."""
    setup_logging()
    logger.info("🔔 Starting Telegram notifier service...")

    try:
        await run_notifier()
    except KeyboardInterrupt:
        logger.info("🛑 Notifier stopped by user")
    except Exception as exc:
        logger.error("Notifier crashed: {}", exc)
        raise


if __name__ == "__main__":
    asyncio.run(main())
