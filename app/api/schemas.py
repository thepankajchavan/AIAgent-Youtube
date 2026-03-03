"""
Pydantic models for API request/response validation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ── Enums (mirror DB enums for the API layer) ────────────────

class VideoFormatEnum(str, Enum):
    SHORT = "short"
    LONG = "long"


class LLMProviderEnum(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class VideoStatusEnum(str, Enum):
    PENDING = "pending"
    SCRIPT_GENERATING = "script_generating"
    AUDIO_GENERATING = "audio_generating"
    VIDEO_GENERATING = "video_generating"
    ASSEMBLING = "assembling"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Pipeline ─────────────────────────────────────────────────

class PipelineRequest(BaseModel):
    """Request body for triggering a new video pipeline."""
    topic: str = Field(
        ...,
        min_length=3,
        max_length=512,
        description="The topic or prompt for the video.",
        examples=["5 mindblowing facts about black holes"],
    )
    video_format: VideoFormatEnum = Field(
        default=VideoFormatEnum.SHORT,
        description="Video format: 'short' (9:16) or 'long' (16:9).",
    )
    provider: LLMProviderEnum = Field(
        default=LLMProviderEnum.OPENAI,
        description="LLM provider for script generation.",
    )
    skip_upload: bool = Field(
        default=False,
        description="If true, pipeline stops after assembly (no YouTube upload).",
    )


class PipelineResponse(BaseModel):
    """Response after triggering a pipeline."""
    project_id: uuid.UUID
    celery_task_id: str
    status: VideoStatusEnum
    message: str


# ── Project ──────────────────────────────────────────────────

class ProjectResponse(BaseModel):
    """Full project detail."""
    id: uuid.UUID
    topic: str
    script: str | None = None
    status: VideoStatusEnum
    format: VideoFormatEnum
    celery_task_id: str | None = None
    audio_path: str | None = None
    video_path: str | None = None
    output_path: str | None = None
    youtube_video_id: str | None = None
    youtube_url: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    """Paginated project listing."""
    total: int
    page: int
    per_page: int
    projects: list[ProjectSummary]


class ProjectSummary(BaseModel):
    """Lightweight project info for list views."""
    id: uuid.UUID
    topic: str
    status: VideoStatusEnum
    format: VideoFormatEnum
    youtube_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# Fix forward reference (ProjectListResponse references ProjectSummary)
ProjectListResponse.model_rebuild()


# ── Celery Task Status ───────────────────────────────────────

class TaskStatusResponse(BaseModel):
    """Status of a Celery background task."""
    task_id: str
    status: str
    result: dict | str | None = None


# ── Generic ──────────────────────────────────────────────────

class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


class HealthResponse(BaseModel):
    """System health check response."""
    status: str
    app: str
    database: str
    redis: str
