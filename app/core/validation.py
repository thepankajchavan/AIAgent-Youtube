"""
Configuration Validation Module — startup checks for all dependencies.

Validates API keys, external binaries (FFmpeg), database connectivity,
Redis connectivity, and media directory permissions before the application starts.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import redis
from loguru import logger
from sqlalchemy import create_engine, text

from app.core.config import get_settings


class ConfigValidationError(Exception):
    """Raised when a critical configuration check fails."""

    pass


async def validate_api_keys() -> None:
    """Check that required API keys are configured."""
    settings = get_settings()
    warnings: list[str] = []
    errors: list[str] = []

    # OpenAI (optional - only if using openai provider)
    if not settings.openai_api_key:
        warnings.append("OpenAI API key not configured (OPENAI_API_KEY)")

    # Anthropic (optional - only if using anthropic provider)
    if not settings.anthropic_api_key:
        warnings.append("Anthropic API key not configured (ANTHROPIC_API_KEY)")

    # ElevenLabs (critical for TTS)
    if not settings.elevenlabs_api_key:
        errors.append("ElevenLabs API key not configured (ELEVENLABS_API_KEY)")

    # Pexels (critical for stock videos)
    if not settings.pexels_api_key:
        errors.append("Pexels API key not configured (PEXELS_API_KEY)")

    # YouTube credentials (critical for upload)
    client_secrets = Path(settings.youtube_client_secrets_file)
    if not client_secrets.exists():
        errors.append(
            f"YouTube client secrets file not found: {settings.youtube_client_secrets_file}"
        )

    # AI Video provider keys (only validated when AI video is enabled)
    if settings.ai_video_enabled:
        provider = settings.ai_video_primary_provider
        if provider == "runway" and not settings.runway_api_key:
            warnings.append(
                "Runway API key not configured (RUNWAY_API_KEY) — "
                "AI video generation will fall back to stock footage"
            )
        elif provider == "stability" and not settings.stability_api_key:
            warnings.append(
                "Stability API key not configured (STABILITY_API_KEY) — "
                "AI video generation will fall back to stock footage"
            )
        elif provider == "kling" and not settings.kling_access_key:
            warnings.append(
                "Kling access key not configured (KLING_ACCESS_KEY) — "
                "AI video generation will fall back to stock footage"
            )

    # Log warnings
    for warning in warnings:
        logger.warning("⚠️  {}", warning)

    # Raise on errors
    if errors:
        error_msg = "Missing critical API keys:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ConfigValidationError(error_msg)

    logger.info("✅ API keys validated")


async def validate_ffmpeg() -> None:
    """Check that FFmpeg and FFprobe are in PATH."""
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")

    errors: list[str] = []

    if not ffmpeg_path:
        errors.append("ffmpeg not found in PATH")

    if not ffprobe_path:
        errors.append("ffprobe not found in PATH")

    if errors:
        error_msg = "Missing FFmpeg binaries:\n" + "\n".join(f"  - {e}" for e in errors)
        logger.warning("⚠️ FFmpeg not found - video generation will not work: {}", error_msg)
        logger.warning("⚠️ Install FFmpeg to enable video processing")
        return  # Don't block startup, just warn

    logger.info("✅ FFmpeg validated (ffmpeg={}, ffprobe={})", ffmpeg_path, ffprobe_path)


async def validate_database() -> None:
    """Test database connectivity with a simple query."""
    settings = get_settings()

    try:
        # Use sync engine for validation
        engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            result.fetchone()
        engine.dispose()

        logger.info("✅ Database connection validated")

    except Exception as exc:
        raise ConfigValidationError(f"Database connection failed: {exc}")


async def validate_redis() -> None:
    """Test Redis connectivity with a ping."""
    settings = get_settings()

    try:
        # Parse Redis URL and connect
        r = redis.from_url(settings.redis_url)
        r.ping()
        r.close()

        logger.info("✅ Redis connection validated")

    except Exception as exc:
        raise ConfigValidationError(f"Redis connection failed: {exc}")


async def validate_media_directories() -> None:
    """Ensure media directories exist and are writable."""
    settings = get_settings()
    errors: list[str] = []

    directories = [
        settings.audio_dir,
        settings.video_dir,
        settings.output_dir,
        settings.ai_video_dir,
    ]

    for directory in directories:
        try:
            # Create if doesn't exist
            directory.mkdir(parents=True, exist_ok=True)

            # Test write permission
            test_file = directory / ".write_test"
            test_file.write_text("test")
            test_file.unlink()

        except Exception as exc:
            errors.append(f"{directory}: {exc}")

    if errors:
        error_msg = "Media directory issues:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ConfigValidationError(error_msg)

    logger.info(
        "✅ Media directories validated (audio={}, video={}, output={})",
        settings.audio_dir,
        settings.video_dir,
        settings.output_dir,
    )


async def validate_all() -> None:
    """
    Run all validation checks.

    Raises:
        ConfigValidationError: If any critical check fails.
    """
    logger.info("🔍 Starting configuration validation...")

    await validate_ffmpeg()
    await validate_database()
    await validate_redis()
    await validate_media_directories()
    await validate_api_keys()

    logger.info("✅ All configuration checks passed")
