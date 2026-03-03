from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """
    Central configuration loaded from environment variables / .env file.
    Every external key, URL, and tunable knob lives here — never hard-coded.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────
    app_name: str = "content-engine"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "DEBUG"

    # ── Database ─────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/content_engine",
        description="Async DB URL (asyncpg driver).",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/content_engine",
        description="Sync DB URL used by Alembic migrations and Celery workers.",
    )

    # ── Redis / Celery ───────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── OpenAI ───────────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # ── Anthropic ────────────────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5-20250929"

    # ── ElevenLabs ───────────────────────────────────────────
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    # ── Pexels ───────────────────────────────────────────────
    pexels_api_key: str = ""

    # ── YouTube ──────────────────────────────────────────────
    youtube_client_secrets_file: str = "client_secrets.json"
    youtube_token_file: str = "youtube_token.json"

    # ── Media Paths ──────────────────────────────────────────
    media_dir: str = "media"

    @property
    def media_path(self) -> Path:
        return Path(self.media_dir).resolve()

    @property
    def audio_dir(self) -> Path:
        return self.media_path / "audio"

    @property
    def video_dir(self) -> Path:
        return self.media_path / "video"

    @property
    def output_dir(self) -> Path:
        return self.media_path / "output"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()
