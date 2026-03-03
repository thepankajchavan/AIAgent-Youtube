import enum
import uuid

from sqlalchemy import Enum, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class VideoStatus(str, enum.Enum):
    """Lifecycle states of a video project."""

    PENDING = "pending"
    SCRIPT_GENERATING = "script_generating"
    AUDIO_GENERATING = "audio_generating"
    VIDEO_GENERATING = "video_generating"
    ASSEMBLING = "assembling"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoFormat(str, enum.Enum):
    SHORT = "short"    # 9:16 vertical
    LONG = "long"      # 16:9 horizontal


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

    # ── Celery tracking ──────────────────────────────────────
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Artefact paths ───────────────────────────────────────
    audio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # ── YouTube ──────────────────────────────────────────────
    youtube_video_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ── Error tracking ───────────────────────────────────────
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<VideoProject {self.id} topic='{self.topic[:40]}…' status={self.status.value}>"
