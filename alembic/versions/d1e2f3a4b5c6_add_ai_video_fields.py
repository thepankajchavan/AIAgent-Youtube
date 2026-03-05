"""add AI video fields to video_projects

Revision ID: d1e2f3a4b5c6
Revises: c8d4e3f2a1b0
Create Date: 2026-03-04 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c8d4e3f2a1b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add visual_strategy column (defaults to stock_only for existing rows)
    op.add_column(
        "video_projects",
        sa.Column(
            "visual_strategy",
            sa.String(length=20),
            nullable=False,
            server_default="stock_only",
            comment="Visual strategy: stock_only, ai_only, hybrid",
        ),
    )

    # Add ai_video_provider column
    op.add_column(
        "video_projects",
        sa.Column(
            "ai_video_provider",
            sa.String(length=20),
            nullable=True,
            comment="AI video provider: runway, stability, kling",
        ),
    )

    # Add scene_plan column (JSON)
    op.add_column(
        "video_projects",
        sa.Column(
            "scene_plan",
            sa.JSON(),
            nullable=True,
            comment="LLM-generated scene plan with per-scene visual decisions",
        ),
    )

    # Add ai_video_cost column
    op.add_column(
        "video_projects",
        sa.Column(
            "ai_video_cost",
            sa.Float(),
            nullable=True,
            server_default="0.0",
            comment="Total AI video generation cost in USD",
        ),
    )

    # Add SCENE_SPLITTING to the video_status enum (without AFTER as it's incompatible with IF NOT EXISTS)
    op.execute(
        "ALTER TYPE video_status ADD VALUE IF NOT EXISTS 'scene_splitting'"
    )


def downgrade() -> None:
    op.drop_column("video_projects", "ai_video_cost")
    op.drop_column("video_projects", "scene_plan")
    op.drop_column("video_projects", "ai_video_provider")
    op.drop_column("video_projects", "visual_strategy")
    # Note: PostgreSQL does not support removing enum values
