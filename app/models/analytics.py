"""Analytics models for the self-improvement feedback loop system."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class VideoAnalytics(Base, UUIDPrimaryKeyMixin):
    """Snapshot of YouTube video performance metrics for a specific date."""

    __tablename__ = "video_analytics"

    project_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="FK to video_projects.id",
    )
    youtube_video_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="YouTube video ID",
    )
    snapshot_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Date of this metrics snapshot",
    )

    # Metrics
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    watch_time_minutes: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    average_view_duration_seconds: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )
    click_through_rate: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="CTR percentage (0-100)",
    )
    average_view_percentage: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Retention percentage",
    )

    # Metadata
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="When we fetched this data",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationship
    project = relationship(
        "VideoProject",
        back_populates="analytics",
        foreign_keys=[project_id],
        primaryjoin="VideoAnalytics.project_id == cast(VideoProject.id, String)",
    )

    __table_args__ = (
        UniqueConstraint("youtube_video_id", "snapshot_date", name="uq_video_snapshot"),
        Index("ix_video_analytics_yt_snapshot", "youtube_video_id", "snapshot_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<VideoAnalytics {self.id} yt={self.youtube_video_id} "
            f"date={self.snapshot_date} views={self.views}>"
        )


class TrendingTopic(Base, UUIDPrimaryKeyMixin):
    """A trending topic/keyword from multiple sources (YouTube, Google, Reddit, Twitter)."""

    __tablename__ = "trending_topics"

    topic: Mapped[str] = mapped_column(String(512), nullable=False)
    category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Category (tech, finance, health, etc.)",
    )
    trend_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Relative popularity score (0-100)",
    )
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="google_trends, youtube_trending, reddit, twitter",
    )
    region: Mapped[str] = mapped_column(
        String(10),
        default="US",
        nullable=False,
        comment="Country code (US, IN, GB, etc.)",
    )
    related_queries: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="JSON string of related search queries",
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this trend data becomes stale",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # ── New columns for smart scheduling ───────────────────────
    velocity: Mapped[str] = mapped_column(
        String(20),
        default="rising",
        nullable=False,
        server_default="rising",
        comment="Trend velocity: rising, peaked, declining",
    )
    quality_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        server_default="0.0",
        comment="Composite quality score (0-100): relevance + freshness + viral potential",
    )
    viral_potential: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
        server_default="0.0",
        comment="Estimated viral potential (0-1)",
    )
    niche: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="Detected niche: science, tech, history, etc.",
    )
    source_url: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="Original URL from source (Reddit post, tweet, video)",
    )
    source_metadata: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="JSON: upvotes, comments, subreddit, hashtags, etc.",
    )
    used_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        server_default="0",
        comment="How many times this topic was used for video generation",
    )
    is_blacklisted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        server_default="false",
        comment="Manually blacklisted topic",
    )

    __table_args__ = (
        Index("ix_trending_source_fetched", "source", "fetched_at"),
        Index("ix_trending_expires", "expires_at"),
        Index("ix_trending_niche_score", "niche", quality_score.desc()),
        Index("ix_trending_velocity", "velocity"),
    )

    def __repr__(self) -> str:
        return f"<TrendingTopic {self.id} topic='{self.topic[:40]}' score={self.trend_score}>"


class ScheduleQueue(Base, UUIDPrimaryKeyMixin):
    """A topic queued for auto-scheduled video creation at a specific time."""

    __tablename__ = "schedule_queue"

    topic: Mapped[str] = mapped_column(String(512), nullable=False)
    trend_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        comment="ID of the TrendingTopic this was sourced from",
    )
    niche: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this video should be dispatched for creation",
    )
    quality_score: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
        server_default="pending",
        comment="pending, dispatched, completed, cancelled, failed",
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        comment="FK to video_projects.id — set after dispatch",
    )
    visual_strategy: Mapped[str] = mapped_column(
        String(20),
        default="stock_only",
        nullable=False,
        server_default="stock_only",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_schedule_queue_status_time", "status", "scheduled_for"),
    )

    def __repr__(self) -> str:
        return (
            f"<ScheduleQueue {self.id} topic='{self.topic[:30]}' "
            f"status={self.status} for={self.scheduled_for}>"
        )


class ScheduleAuditLog(Base, UUIDPrimaryKeyMixin):
    """Records every scheduling decision for transparency and debugging."""

    __tablename__ = "schedule_audit_log"

    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="topic_selected, topic_rejected, schedule_dispatched, toggle_changed, etc.",
    )
    topic: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Human-readable explanation of the decision",
    )
    details: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="JSON extra data (scores, alternatives, etc.)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_audit_log_action_created", "action", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ScheduleAuditLog {self.id} action={self.action} topic='{(self.topic or '')[:30]}'>"


class TopicBlacklist(Base, UUIDPrimaryKeyMixin):
    """Explicit blacklist/whitelist for topics or keywords."""

    __tablename__ = "topic_blacklist"

    keyword: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        unique=True,
    )
    list_type: Mapped[str] = mapped_column(
        String(20),
        default="blacklist",
        nullable=False,
        server_default="blacklist",
        comment="blacklist or whitelist",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<TopicBlacklist {self.id} keyword='{self.keyword}' type={self.list_type}>"


class PerformancePattern(Base, UUIDPrimaryKeyMixin):
    """A discovered performance pattern from video analytics analysis."""

    __tablename__ = "performance_patterns"

    pattern_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="hook_style, topic, cta, script_structure, length",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Human-readable pattern description",
    )
    pattern_data: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="JSON structured pattern details",
    )
    confidence_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="0.0 to 1.0",
    )
    sample_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Number of videos this pattern is based on",
    )
    avg_views: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Average views for videos matching this pattern",
    )
    avg_retention: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Average retention percentage",
    )
    supporting_evidence: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="JSON list of project_ids and their stats",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_pattern_type_active", "pattern_type", "is_active"),
        Index("ix_pattern_confidence", confidence_score.desc()),
    )

    def __repr__(self) -> str:
        return (
            f"<PerformancePattern {self.id} type={self.pattern_type} "
            f"confidence={self.confidence_score:.2f}>"
        )


class PromptVersion(Base, UUIDPrimaryKeyMixin):
    """A versioned prompt template for script generation."""

    __tablename__ = "prompt_versions"

    version_label: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="v1, v2.1, experiment-hooks-q3",
    )
    template: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Full prompt template with {placeholders}",
    )
    variables: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="JSON default variable values",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
        comment="Currently in use (only one active at a time)",
    )
    is_baseline: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Is this the baseline for A/B comparison",
    )
    usage_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    avg_views: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_retention: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_ctr: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_prompt_avg_views", avg_views.desc()),)

    def __repr__(self) -> str:
        return (
            f"<PromptVersion {self.id} label={self.version_label} "
            f"active={self.is_active} usage={self.usage_count}>"
        )
