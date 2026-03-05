import enum
import uuid

from sqlalchemy import BigInteger, Enum, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class VideoStatus(str, enum.Enum):
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


class VideoFormat(str, enum.Enum):
    SHORT = "short"    # 9:16 vertical
    LONG = "long"      # 16:9 horizontal


class VisualStrategy(str, enum.Enum):
    STOCK_ONLY = "stock_only"
    AI_ONLY = "ai_only"
    HYBRID = "hybrid"


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
        comment="LLM provider used: openai or anthropic"
    )

    # ── Celery tracking ──────────────────────────────────────
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Resume from Failure support ──────────────────────────
    last_completed_step: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Last successfully completed pipeline step (for resuming)"
    )
    artifacts_available: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
        comment="JSON object tracking which intermediate artifacts exist"
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

    # ── Artefact paths ───────────────────────────────────────
    audio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="Path to video thumbnail (JPEG extracted from middle frame)"
    )

    # ── YouTube ──────────────────────────────────────────────
    youtube_video_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ── Telegram integration ─────────────────────────────────
    telegram_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
        comment="Telegram user ID who requested this video"
    )
    telegram_chat_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="Telegram chat ID where video was requested"
    )
    telegram_message_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Telegram message ID to edit with status updates"
    )

    # ── Error tracking ───────────────────────────────────────
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<VideoProject {self.id} topic='{self.topic[:40]}…' status={self.status.value}>"

    # ── State machine validation ─────────────────────────────
    _VALID_TRANSITIONS: dict[VideoStatus, set[VideoStatus]] = {
        VideoStatus.PENDING: {VideoStatus.SCRIPT_GENERATING, VideoStatus.FAILED},
        VideoStatus.SCRIPT_GENERATING: {
            VideoStatus.SCENE_SPLITTING,      # AI video path
            VideoStatus.AUDIO_GENERATING,     # stock_only path (direct)
            VideoStatus.VIDEO_GENERATING,
            VideoStatus.FAILED,
        },
        VideoStatus.SCENE_SPLITTING: {
            VideoStatus.AUDIO_GENERATING,
            VideoStatus.VIDEO_GENERATING,
            VideoStatus.FAILED,
        },
        VideoStatus.AUDIO_GENERATING: {VideoStatus.VIDEO_GENERATING, VideoStatus.ASSEMBLING, VideoStatus.FAILED},
        VideoStatus.VIDEO_GENERATING: {VideoStatus.AUDIO_GENERATING, VideoStatus.ASSEMBLING, VideoStatus.FAILED},
        VideoStatus.ASSEMBLING: {VideoStatus.UPLOADING, VideoStatus.COMPLETED, VideoStatus.FAILED},
        VideoStatus.UPLOADING: {VideoStatus.COMPLETED, VideoStatus.FAILED},
        VideoStatus.COMPLETED: set(),
        VideoStatus.FAILED: {VideoStatus.PENDING},  # Only via retry
    }

    def validate_status_transition(self, new_status: VideoStatus) -> bool:
        """Validate state transition is allowed by FSM."""
        if new_status not in self._VALID_TRANSITIONS.get(self.status, set()):
            raise ValueError(
                f"Invalid transition: {self.status.value} → {new_status.value}"
            )
        return True
