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
    elevenlabs_voice_id: str = "pNInz6obpgDQGcFmaJgB"  # Adam (deep male)
    elevenlabs_model: str = "eleven_multilingual_v2"
    elevenlabs_output_format: str = "mp3_44100_192"
    elevenlabs_stability: float = 0.45
    elevenlabs_similarity_boost: float = 0.80
    elevenlabs_style: float = 0.50
    elevenlabs_monthly_char_limit: int = 100_000

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
    runway_model: str = "gen4.5"
    stability_api_key: str = ""
    kling_access_key: str = ""
    kling_secret_key: str = ""
    ai_video_max_cost_per_video: float = Field(
        default=5.00,
        description="Maximum USD cost per video for AI generation (3 scenes × 10s × $0.12)",
    )
    ai_video_max_daily_spend: float = Field(
        default=10.00,
        description="Maximum daily USD spend on AI video generation (2 shorts/day + buffer)",
    )
    ai_video_timeout: int = Field(
        default=300,
        description="Timeout in seconds for a single AI video generation",
    )

    # ── AI Video Quality Enhancements ──────────────────────
    visual_continuity_enabled: bool = Field(
        default=True,
        description="Apply visual style anchor across scenes for color/lighting consistency",
    )
    prompt_rewriting_enabled: bool = Field(
        default=False,
        description="Use LLM to rewrite scene prompts per AI video provider (adds ~$0.01/video)",
    )
    stock_query_expansion_enabled: bool = Field(
        default=True,
        description="Expand stock footage queries with synonyms and narration context",
    )
    color_normalization_enabled: bool = Field(
        default=False,
        description="Apply FFmpeg color grading normalization to unify visual style",
    )
    color_normalization_profile: str = Field(
        default="auto",
        description="Color profile: auto (from mood), neutral, cinematic, warm, cool",
    )

    # ── AI Image Generation (DALL-E / GPT-image-1) ────────
    ai_images_enabled: bool = Field(
        default=False,
        description="Enable AI image generation for scene-accurate visuals",
    )
    ai_images_model: str = Field(
        default="dall-e-3",
        description="Image model: dall-e-3 or gpt-image-1",
    )
    ai_images_size: str = Field(
        default="1024x1792",
        description="Image size (must be valid for the chosen model)",
    )
    ai_images_quality: str = Field(
        default="standard",
        description="Image quality: standard or hd",
    )
    ai_images_max_cost_per_video: float = Field(
        default=1.00,
        description="Maximum USD cost for AI image generation per video",
    )

    # ── Voice Profiles ─────────────────────────────────────────
    voice_profile_enabled: bool = Field(
        default=True,
        description="Map LLM mood tag to tuned TTS voice parameters",
    )

    # ── Hook Scoring ───────────────────────────────────────────
    hook_min_score: float = Field(
        default=0.3,
        description="Minimum hook engagement score (0.0-1.0) before retry",
    )

    # ── Content Quality ────────────────────────────────────────
    niche_templates_enabled: bool = Field(
        default=True,
        description="Use niche-specific tone templates in LLM prompt",
    )
    mood_creative_glue_enabled: bool = Field(
        default=False,
        description="Let mood drive caption and transition style automatically",
    )
    per_beat_tts_enabled: bool = Field(
        default=False,
        description="Generate TTS with per-beat expressiveness variation",
    )

    # ── Web Search (Tavily) ─────────────────────────────────
    tavily_api_key: str = ""
    web_search_enabled: bool = Field(
        default=True,
        description="Enable web search for real-time context before script generation",
    )
    web_search_max_results: int = Field(
        default=5,
        description="Number of search results to fetch for context",
    )
    search_multi_query_enabled: bool = Field(
        default=True,
        description="Expand topic into multiple search queries for broader coverage",
    )
    search_credibility_enabled: bool = Field(
        default=True,
        description="Rank search results by domain authority",
    )

    # ── Captions (Word-level via Whisper) ────────────────────
    captions_enabled: bool = True
    captions_font: str = "Arial"
    captions_font_size: int = 28
    captions_max_words_per_chunk: int = 3
    captions_uppercase: bool = True
    captions_style: str = Field(
        default="classic",
        description="Caption animation style: classic, karaoke, bounce, typewriter",
    )
    captions_position: str = Field(
        default="bottom",
        description="Caption position: bottom, center, top",
    )
    captions_primary_color: str = Field(
        default="FFFFFF",
        description="Primary caption color (BGR hex)",
    )
    captions_accent_color: str = Field(
        default="00FFFF",
        description="Accent/highlight color for karaoke (BGR hex)",
    )
    captions_outline_color: str = Field(
        default="000000",
        description="Caption outline color (BGR hex)",
    )
    captions_shadow_color: str = Field(
        default="80000000",
        description="Caption shadow color (ABGR hex)",
    )

    # ── Video Transitions ──────────────────────────────────────
    transitions_enabled: bool = Field(
        default=True,
        description="Enable enhanced video transitions between scenes",
    )
    transition_style: str = Field(
        default="auto",
        description="Transition style: auto, uniform, fade, dissolve, wipeleft, etc.",
    )
    transition_duration: float = Field(
        default=0.3,
        description="Base transition duration in seconds",
    )
    transition_duration_min: float = Field(
        default=0.2,
        description="Minimum transition duration in seconds",
    )
    transition_duration_max: float = Field(
        default=0.8,
        description="Maximum transition duration in seconds",
    )

    # ── Background Music ───────────────────────────────────────
    bgm_enabled: bool = Field(
        default=False,
        description="Enable background music via Pixabay Music API",
    )
    pixabay_api_key: str = ""
    bgm_volume_db: float = Field(
        default=-18.0,
        description="Background music volume in dB",
    )
    tts_volume_db: float = Field(
        default=-3.0,
        description="TTS narration volume in dB",
    )
    bgm_fade_in_duration: float = Field(
        default=1.0,
        description="BGM fade-in duration at video start (seconds)",
    )
    bgm_fade_out_duration: float = Field(
        default=2.0,
        description="BGM fade-out duration at video end (seconds)",
    )
    bgm_ducking_enabled: bool = Field(
        default=True,
        description="Enable sidechain ducking of BGM during narration",
    )
    bgm_ducking_amount_db: float = Field(
        default=-6.0,
        description="Extra BGM reduction during speech (dB)",
    )
    bgm_default_mood: str = Field(
        default="uplifting",
        description="Fallback mood for BGM when LLM doesn't specify",
    )

    # ── Scene Director ─────────────────────────────────────────
    scene_director_enabled: bool = Field(
        default=False,
        description="Enable scene-aware creative direction",
    )
    scene_director_provider: str = Field(
        default="openai",
        description="LLM provider for scene direction",
    )
    creative_preset: str = Field(
        default="auto",
        description="Creative preset: auto, minimal, cinematic, energetic",
    )

    # ── YouTube ──────────────────────────────────────────────
    youtube_api_key: str = ""
    youtube_client_secrets_file: str = "client_secrets.json"
    youtube_token_file: str = "youtube_token.json"
    youtube_default_privacy: str = "public"
    youtube_default_category: str = "education"

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

    # ── YouTube Analytics ──────────────────────────────────────
    youtube_analytics_enabled: bool = False
    youtube_analytics_collection_hour: int = 3
    youtube_analytics_lookback_days: int = 7

    # ── Trend Fetching (Multi-Source) ──────────────────────────
    trends_enabled: bool = False
    trends_categories: str = "technology,entertainment,education"
    trends_region: str = "US"
    trends_fetch_interval_hours: int = Field(
        default=4,
        description="Hours between trend fetches (Celery Beat interval)",
    )
    trends_reddit_enabled: bool = Field(
        default=False,
        description="Enable Reddit as trend source",
    )
    trends_reddit_subreddits: str = Field(
        default="technology,science,worldnews,futurology",
        description="Comma-separated subreddits to monitor",
    )
    trends_twitter_enabled: bool = Field(
        default=False,
        description="Enable Twitter/X as trend source (best-effort)",
    )
    trends_min_quality_score: float = Field(
        default=40.0,
        description="Minimum quality score to consider for scheduling (0-100)",
    )
    trends_expiry_hours: int = Field(
        default=24,
        description="Hours before a trend expires",
    )

    # ── Self-Improvement ──────────────────────────────────────
    self_improvement_enabled: bool = False
    pattern_analysis_min_videos: int = 10
    pattern_analysis_schedule: str = "weekly"
    prompt_ab_testing_enabled: bool = False

    # ── Auto-Scheduling (Smart) ────────────────────────────────
    auto_schedule_enabled: bool = Field(
        default=False,
        description="Enable automatic video creation from trending topics",
    )
    auto_schedule_max_daily: int = Field(
        default=3,
        description="Maximum auto-scheduled videos per day",
    )
    auto_schedule_niche: str = Field(
        default="",
        description="Filter trends by niche (empty = any)",
    )
    auto_schedule_visual_strategy: str = Field(
        default="stock_only",
        description="Visual strategy for auto-scheduled videos",
    )
    auto_schedule_skip_upload: bool = Field(
        default=False,
        description="Skip YouTube upload for auto-scheduled videos",
    )
    auto_schedule_cooldown_hours: int = Field(
        default=4,
        description="Minimum hours between auto-scheduled videos",
    )
    auto_schedule_times: str = Field(
        default="10:00,18:00",
        description="Fixed daily schedule times in HH:MM UTC, comma-separated",
    )
    auto_schedule_admin_chat_id: int = Field(
        default=0,
        description="Telegram chat ID for auto-schedule admin notifications",
    )
    auto_schedule_quality_threshold: float = Field(
        default=40.0,
        description="Minimum topic quality score for auto-scheduling (0-100)",
    )
    auto_schedule_diversity_window: int = Field(
        default=3,
        description="Last N videos to check for category diversity",
    )
    auto_schedule_performance_feedback: bool = Field(
        default=True,
        description="Boost topics similar to past top-performing videos",
    )

    # ── AI Thumbnails ─────────────────────────────────────────
    ai_thumbnail_enabled: bool = Field(
        default=False,
        description="Generate AI thumbnails via DALL-E instead of frame extraction",
    )
    ai_thumbnail_text_overlay: bool = Field(
        default=True,
        description="Add title text overlay on AI thumbnails",
    )

    # ── Multi-Voice ───────────────────────────────────────────
    multi_voice_enabled: bool = Field(
        default=False,
        description="Use different ElevenLabs voices per niche/mood",
    )
    voice_map_science: str = ""
    voice_map_history: str = ""
    voice_map_technology: str = ""
    voice_map_motivation: str = ""
    voice_map_entertainment: str = ""
    voice_map_default: str = ""

    # ── Multi-Language ────────────────────────────────────────
    multi_language_enabled: bool = Field(
        default=False,
        description="Enable multi-language video generation via LLM translation",
    )
    default_language: str = Field(
        default="en",
        description="Default language code for video generation",
    )
    translation_provider: str = Field(
        default="openai",
        description="LLM provider for translation: openai or anthropic",
    )

    # ── Video Pacing ──────────────────────────────────────────
    pacing_enabled: bool = Field(
        default=False,
        description="Enable dynamic video speed per scene",
    )
    pacing_style: str = Field(
        default="auto",
        description="Pacing style: auto, uniform, dramatic, energetic",
    )
    pacing_base_speed: float = Field(
        default=1.0,
        description="Base speed multiplier for all scenes",
    )
    pacing_min_speed: float = Field(
        default=0.75,
        description="Minimum speed multiplier (slow-mo limit)",
    )
    pacing_max_speed: float = Field(
        default=1.25,
        description="Maximum speed multiplier (speed-up limit)",
    )

    # ── Media Paths ──────────────────────────────────────────
    media_dir: str = "media"
    outro_video_path: str = Field(
        default="media/assets/outro.mp4",
        description="Pre-made outro clip appended to every short (like/subscribe CTA)",
    )

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

    @property
    def ai_images_dir(self) -> Path:
        return self.media_path / "ai_images"

    @property
    def captions_dir(self) -> Path:
        return self.media_path / "captions"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton of the application settings."""
    return Settings()
