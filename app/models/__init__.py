"""Database models."""

from app.models.analytics import (
    PerformancePattern,
    PromptVersion,
    ScheduleAuditLog,
    ScheduleQueue,
    TopicBlacklist,
    TrendingTopic,
    VideoAnalytics,
)
from app.models.api_key import APIKey
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.telegram_user import TelegramUser
from app.models.video import VideoFormat, VideoProject, VideoStatus, VisualStrategy

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "VideoProject",
    "VideoStatus",
    "VideoFormat",
    "VisualStrategy",
    "TelegramUser",
    "APIKey",
    "VideoAnalytics",
    "TrendingTopic",
    "PerformancePattern",
    "PromptVersion",
    "ScheduleQueue",
    "ScheduleAuditLog",
    "TopicBlacklist",
]
