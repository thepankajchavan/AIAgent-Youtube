"""add self-improvement feedback loop tables

Revision ID: a1b2c3d4e5f6
Revises: 7373379bba85
Create Date: 2026-03-07 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "7373379bba85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── video_analytics ──────────────────────────────────────
    op.create_table(
        "video_analytics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("youtube_video_id", sa.String(64), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("likes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comments", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shares", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("watch_time_minutes", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("average_view_duration_seconds", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("click_through_rate", sa.Float(), nullable=True),
        sa.Column("average_view_percentage", sa.Float(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("youtube_video_id", "snapshot_date", name="uq_video_snapshot"),
    )
    op.create_index("ix_video_analytics_project_id", "video_analytics", ["project_id"])
    op.create_index("ix_video_analytics_snapshot_date", "video_analytics", ["snapshot_date"])
    op.create_index("ix_video_analytics_yt_snapshot", "video_analytics", ["youtube_video_id", "snapshot_date"])

    # ── trending_topics ──────────────────────────────────────
    op.create_table(
        "trending_topics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("topic", sa.String(512), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("trend_score", sa.Float(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("region", sa.String(10), nullable=False, server_default="US"),
        sa.Column("related_queries", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_trending_category", "trending_topics", ["category"])
    op.create_index("ix_trending_source_fetched", "trending_topics", ["source", "fetched_at"])
    op.create_index("ix_trending_expires", "trending_topics", ["expires_at"])

    # ── performance_patterns ─────────────────────────────────
    op.create_table(
        "performance_patterns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pattern_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("pattern_data", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("avg_views", sa.Float(), nullable=False),
        sa.Column("avg_retention", sa.Float(), nullable=True),
        sa.Column("supporting_evidence", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pattern_type_active", "performance_patterns", ["pattern_type", "is_active"])
    op.create_index("ix_pattern_confidence", "performance_patterns", [sa.text("confidence_score DESC")])

    # ── prompt_versions ──────────────────────────────────────
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version_label", sa.String(100), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("variables", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_views", sa.Float(), nullable=True),
        sa.Column("avg_retention", sa.Float(), nullable=True),
        sa.Column("avg_ctr", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_prompt_versions_is_active", "prompt_versions", ["is_active"])
    op.create_index("ix_prompt_avg_views", "prompt_versions", [sa.text("avg_views DESC")])

    # ── Alter video_projects ─────────────────────────────────
    op.add_column(
        "video_projects",
        sa.Column(
            "prompt_version_id",
            sa.String(36),
            nullable=True,
            comment="FK to prompt_versions.id",
        ),
    )
    op.add_column(
        "video_projects",
        sa.Column(
            "trend_topic_used",
            sa.String(512),
            nullable=True,
            comment="Trending topic incorporated into the script prompt",
        ),
    )


def downgrade() -> None:
    op.drop_column("video_projects", "trend_topic_used")
    op.drop_column("video_projects", "prompt_version_id")
    op.drop_table("prompt_versions")
    op.drop_table("performance_patterns")
    op.drop_table("trending_topics")
    op.drop_table("video_analytics")
