from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # ── AI Video Generation ──────────────────────────────────
    ai_video_enabled: bool = Field(
        default=False,
        description="Enable AI video generation (Runway/Stability/Kling)",
    )
    ai_video_strategy: str = Field(
        default="stock_only",
        description="Default visual strategy: stock_only, ai_only, hybrid",
    )
    ai_video_primary_provider: str = Field(
        default="runway",
        description="Primary AI video provider: runway, stability, kling",
    )
    ai_video_secondary_provider: str = Field(
        default="stability",
        description="Fallback AI video provider",
    )
    runway_api_key: str = ""
    runway_model: str = "gen3a_turbo"
    stability_api_key: str = ""
    kling_access_key: str = ""
    kling_secret_key: str = ""
    ai_video_max_cost_per_video: float = Field(
        default=5.0,
        description="Maximum USD cost per video for AI generation",
    )
    ai_video_max_daily_spend: float = Field(
        default=50.0,
        description="Maximum daily USD spend on AI video generation",
    )
    ai_video_timeout: int = Field(
        default=300,
        description="Timeout in seconds for a single AI video generation",
    )

    # ── YouTube ──────────────────────────────────────────────
    youtube_client_secrets_file: str = "client_secrets.json"
    youtube_token_file: str = "youtube_token.json"

    # ── Telegram Bot ─────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_mode: str = "polling"  # "polling" or "webhook"
    telegram_webhook_url: str = ""
    telegram_webhook_secret: str = ""
    api_base_url: str = "http://localhost:8000"

    # Comma-separated list of allowed Telegram user IDs
    telegram_allowed_users: str = ""

    @property
    def telegram_allowed_user_ids(self) -> set[int]:
        """Parse comma-separated user IDs into a set."""
        if not self.telegram_allowed_users:
            return set()
        return {int(uid.strip()) for uid in self.telegram_allowed_users.split(",") if uid.strip()}

    # ── API Authentication ───────────────────────────────────
    api_auth_enabled: bool = Field(
        default=True,
        description="Enable API key authentication for all endpoints (except public paths)",
    )

    # ── Security & Encryption ────────────────────────────────
    encryption_key: str = Field(
        default="",
        description="Fernet encryption key for sensitive data (generate with Fernet.generate_key())",
    )

    # ── CORS Configuration ───────────────────────────────────
    cors_allowed_origins: str = Field(
        default="*",
        description="Comma-separated list of allowed CORS origins (use '*' for development only)",
    )

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

    @property
    def ai_video_dir(self) -> Path:
        return self.media_path / "ai_video"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()
