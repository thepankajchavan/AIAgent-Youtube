import sys

from loguru import logger

from app.core.config import get_settings


def setup_logging() -> None:
    """Configure loguru as the application-wide logger."""
    settings = get_settings()

    logger.remove()  # remove default stderr sink

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stderr,
        format=log_format,
        level=settings.log_level,
        colorize=True,
    )

    logger.add(
        "logs/app_{time:YYYY-MM-DD}.log",
        format=log_format,
        level="DEBUG",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        enqueue=True,  # thread-safe writes
    )

    logger.info("Logging initialised — level={}", settings.log_level)
