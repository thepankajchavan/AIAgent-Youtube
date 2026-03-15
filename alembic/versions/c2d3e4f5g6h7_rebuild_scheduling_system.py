"""Rebuild scheduling system - enhanced trends, schedule queue, audit log, blacklist

Revision ID: c2d3e4f5g6h7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5g6h7"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enhance trending_topics table ─────────────────────────
    op.add_column(
        "trending_topics",
        sa.Column("velocity", sa.String(20), nullable=False, server_default="rising",
                  comment="Trend velocity: rising, peaked, declining"),
    )
    op.add_column(
        "trending_topics",
        sa.Column("quality_score", sa.Float(), nullable=False, server_default="0.0",
                  comment="Composite quality score (0-100)"),
    )
    op.add_column(
        "trending_topics",
        sa.Column("viral_potential", sa.Float(), nullable=False, server_default="0.0",
                  comment="Estimated viral potential (0-1)"),
    )
    op.add_column(
        "trending_topics",
        sa.Column("niche", sa.String(50), nullable=True,
                  comment="Detected niche: science, tech, history, etc."),
    )
    op.add_column(
        "trending_topics",
        sa.Column("source_url", sa.String(1024), nullable=True,
                  comment="Original URL from source"),
    )
    op.add_column(
        "trending_topics",
        sa.Column("source_metadata", sa.Text(), nullable=True,
                  comment="JSON: upvotes, comments, subreddit, hashtags"),
    )
    op.add_column(
        "trending_topics",
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0",
                  comment="How many times used for video generation"),
    )
    op.add_column(
        "trending_topics",
        sa.Column("is_blacklisted", sa.Boolean(), nullable=False, server_default="false",
                  comment="Manually blacklisted topic"),
    )
    op.create_index("ix_trending_niche_score", "trending_topics", ["niche", sa.text("quality_score DESC")])
    op.create_index("ix_trending_velocity", "trending_topics", ["velocity"])
    op.create_index("ix_trending_niche", "trending_topics", ["niche"])

    # ── Create schedule_queue table ───────────────────────────
    op.create_table(
        "schedule_queue",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("topic", sa.String(512), nullable=False),
        sa.Column("trend_id", sa.String(36), nullable=True),
        sa.Column("niche", sa.String(50), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("visual_strategy", sa.String(20), nullable=False, server_default="stock_only"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_schedule_queue_status_time", "schedule_queue", ["status", "scheduled_for"])

    # ── Create schedule_audit_log table ───────────────────────
    op.create_table(
        "schedule_audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("topic", sa.String(512), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_log_action_created", "schedule_audit_log", ["action", "created_at"])

    # ── Create topic_blacklist table ──────────────────────────
    op.create_table(
        "topic_blacklist",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("keyword", sa.String(256), nullable=False, unique=True),
        sa.Column("list_type", sa.String(20), nullable=False, server_default="blacklist"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ── Add scheduling + voice + language columns to video_projects ──
    op.add_column(
        "video_projects",
        sa.Column("is_auto_scheduled", sa.Boolean(), nullable=False, server_default="false",
                  comment="Whether this video was auto-scheduled from trends"),
    )
    op.add_column(
        "video_projects",
        sa.Column("schedule_queue_id", sa.String(36), nullable=True,
                  comment="FK to schedule_queue.id if auto-scheduled from queue"),
    )
    op.add_column(
        "video_projects",
        sa.Column("voice_id", sa.String(100), nullable=True,
                  comment="ElevenLabs voice_id used for TTS"),
    )
    op.add_column(
        "video_projects",
        sa.Column("language", sa.String(10), nullable=False, server_default="en",
                  comment="Language code for the video (en, es, fr, etc.)"),
    )


def downgrade() -> None:
    op.drop_column("video_projects", "language")
    op.drop_column("video_projects", "voice_id")
    op.drop_column("video_projects", "schedule_queue_id")
    op.drop_column("video_projects", "is_auto_scheduled")
    op.drop_table("topic_blacklist")
    op.drop_index("ix_audit_log_action_created", table_name="schedule_audit_log")
    op.drop_table("schedule_audit_log")
    op.drop_index("ix_schedule_queue_status_time", table_name="schedule_queue")
    op.drop_table("schedule_queue")
    op.drop_index("ix_trending_niche", table_name="trending_topics")
    op.drop_index("ix_trending_velocity", table_name="trending_topics")
    op.drop_index("ix_trending_niche_score", table_name="trending_topics")
    op.drop_column("trending_topics", "is_blacklisted")
    op.drop_column("trending_topics", "used_count")
    op.drop_column("trending_topics", "source_metadata")
    op.drop_column("trending_topics", "source_url")
    op.drop_column("trending_topics", "niche")
    op.drop_column("trending_topics", "viral_potential")
    op.drop_column("trending_topics", "quality_score")
    op.drop_column("trending_topics", "velocity")
