import enum

from sqlalchemy import JSON, BigInteger, Boolean, Enum, Float, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class VideoStatus(enum.StrEnum):
    """Lifecycle states of a video project."""

    PENDING = "pending"
    SCRIPT_GENERATING = "script_generating"
    SCENE_SPLITTING = "scene_splitting"
    AUDIO_GENERATING = "audio_generating"
    VIDEO_GENERATING = "video_generating"
    ASSEMBLING = "assembling"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoFormat(enum.StrEnum):
    SHORT = "short"  # 9:16 vertical
    LONG = "long"  # 16:9 horizontal


class VisualStrategy(enum.StrEnum):
    STOCK_ONLY = "stock_only"
    AI_ONLY = "ai_only"
    HYBRID = "hybrid"
    AI_IMAGES = "ai_images"


class VideoProject(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Represents a single video from topic → upload.
    Each row tracks the pipeline state and stores artefact paths.
    """

    __tablename__ = "video_projects"

    # ── Content ──────────────────────────────────────────────
    topic: Mapped[str] = mapped_column(String(512), nullable=False)
    script: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Pipeline state ───────────────────────────────────────
    status: Mapped[VideoStatus] = mapped_column(
        Enum(VideoStatus, name="video_status", create_constraint=True),
        default=VideoStatus.PENDING,
        nullable=False,
    )
    format: Mapped[VideoFormat] = mapped_column(
        Enum(VideoFormat, name="video_format", create_constraint=True),
        default=VideoFormat.SHORT,
        nullable=False,
    )

    # ── LLM Provider tracking ────────────────────────────────
    provider: Mapped[str] = mapped_column(
        String(20),
        default="openai",
        nullable=False,
        comment="LLM provider used: openai or anthropic",
    )

    # ── Celery tracking ──────────────────────────────────────
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Resume from Failure support ──────────────────────────
    last_completed_step: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Last successfully completed pipeline step (for resuming)",
    )
    artifacts_available: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
        comment="JSON object tracking which intermediate artifacts exist",
    )

    # ── AI Video Generation ───────────────────────────────────
    visual_strategy: Mapped[str] = mapped_column(
        String(20),
        default="stock_only",
        nullable=False,
        comment="Visual strategy: stock_only, ai_only, hybrid",
    )
    ai_video_provider: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="AI video provider used: runway, stability, kling",
    )
    scene_plan: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
        comment="LLM-generated scene plan with per-scene visual decisions",
    )
    ai_video_cost: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=0.0,
        comment="Total AI video generation cost in USD",
    )

    # ── Background Music ────────────────────────────────────
    bgm_mood: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Mood tag used for BGM selection",
    )
    bgm_track_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Pixabay track ID used for BGM",
    )
    bgm_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="Path to downloaded BGM audio file",
    )

    # ── Duration control ────────────────────────────────────
    target_duration: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
        comment="User-requested target duration in seconds",
    )

    # ── Artefact paths ───────────────────────────────────────
    audio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="Path to video thumbnail (JPEG extracted from middle frame)",
    )

    # ── YouTube ──────────────────────────────────────────────
    youtube_video_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ── YouTube Metadata (for analytics) ─────────────────────
    youtube_title: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="Video title used on YouTube"
    )
    youtube_description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="SEO description used on YouTube"
    )
    youtube_tags: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Tags list used on YouTube"
    )
    youtube_hashtags: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="Hashtags list used on YouTube"
    )
    youtube_category: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="YouTube category used"
    )

    # ── Telegram integration ─────────────────────────────────
    telegram_user_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True, comment="Telegram user ID who requested this video"
    )
    telegram_chat_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="Telegram chat ID where video was requested"
    )
    telegram_message_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Telegram message ID to edit with status updates"
    )

    # ── Self-Improvement tracking ──────────────────────────────
    prompt_version_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        comment="FK to prompt_versions.id — which prompt version generated this script",
    )
    trend_topic_used: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Trending topic incorporated into the script prompt",
    )

    # ── Auto-scheduling ────────────────────────────────────────
    is_auto_scheduled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        server_default="false",
        comment="Whether this video was auto-scheduled from trends",
    )
    schedule_queue_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        comment="FK to schedule_queue.id if auto-scheduled from queue",
    )

    # ── Voice selection ───────────────────────────────────────
    voice_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="ElevenLabs voice_id used for TTS",
    )

    # ── Language ──────────────────────────────────────────────
    language: Mapped[str] = mapped_column(
        String(10),
        default="en",
        nullable=False,
        server_default="en",
        comment="Language code for the video (en, es, fr, etc.)",
    )

    # ── Error tracking ───────────────────────────────────────
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Relationships ────────────────────────────────────────
    analytics = relationship(
        "VideoAnalytics",
        back_populates="project",
        foreign_keys="[VideoAnalytics.project_id]",
        primaryjoin="cast(VideoProject.id, String) == VideoAnalytics.project_id",
    )

    # ── Table-level indexes ───────────────────────────────────
    __table_args__ = (
        # Performance indexes (migration f6c0d6f1328b)
        Index("ix_video_projects_status", "status"),
        Index("ix_video_projects_created_at", "created_at"),
        Index(
            "ix_video_projects_celery_task_id",
            "celery_task_id",
            postgresql_where=text("celery_task_id IS NOT NULL"),
        ),
        Index(
            "ix_video_projects_youtube_video_id",
            "youtube_video_id",
            unique=True,
            postgresql_where=text("youtube_video_id IS NOT NULL"),
        ),
        Index("ix_video_projects_status_created_at", "status", "created_at"),
        # Composite indexes (migration b9f3e4d5c6a7)
        Index("ix_video_projects_telegram_user_created_at", "telegram_user_id", "created_at"),
        Index("ix_video_projects_id_status", "id", "status"),
        Index("ix_video_projects_updated_at", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<VideoProject {self.id} topic='{self.topic[:40]}…' status={self.status.value}>"

    # ── State machine validation ─────────────────────────────
    _VALID_TRANSITIONS: dict[VideoStatus, set[VideoStatus]] = {
        VideoStatus.PENDING: {VideoStatus.SCRIPT_GENERATING, VideoStatus.FAILED},
        VideoStatus.SCRIPT_GENERATING: {
            VideoStatus.SCENE_SPLITTING,  # AI video path
            VideoStatus.AUDIO_GENERATING,  # stock_only path (direct)
            VideoStatus.VIDEO_GENERATING,
            VideoStatus.FAILED,
        },
        VideoStatus.SCENE_SPLITTING: {
            VideoStatus.AUDIO_GENERATING,
            VideoStatus.VIDEO_GENERATING,
            VideoStatus.FAILED,
        },
        VideoStatus.AUDIO_GENERATING: {
            VideoStatus.SCENE_SPLITTING,  # AI path: audio-first sequential
            VideoStatus.VIDEO_GENERATING,
            VideoStatus.ASSEMBLING,
            VideoStatus.FAILED,
        },
        VideoStatus.VIDEO_GENERATING: {
            VideoStatus.AUDIO_GENERATING,
            VideoStatus.ASSEMBLING,
            VideoStatus.FAILED,
        },
        VideoStatus.ASSEMBLING: {VideoStatus.UPLOADING, VideoStatus.COMPLETED, VideoStatus.FAILED},
        VideoStatus.UPLOADING: {VideoStatus.COMPLETED, VideoStatus.FAILED},
        VideoStatus.COMPLETED: set(),
        VideoStatus.FAILED: {VideoStatus.PENDING},  # Only via retry
    }

    def validate_status_transition(self, new_status: VideoStatus) -> bool:
        """Validate state transition is allowed by FSM."""
        if new_status not in self._VALID_TRANSITIONS.get(self.status, set()):
            raise ValueError(f"Invalid transition: {self.status.value} → {new_status.value}")
        return True
