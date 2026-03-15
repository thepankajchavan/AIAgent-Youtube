"""Add BGM fields to video_projects

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-03-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b7c8d9e0f1a2"
down_revision = "3967a5f94766"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "video_projects",
        sa.Column("bgm_mood", sa.String(50), nullable=True, comment="Mood tag used for BGM selection"),
    )
    op.add_column(
        "video_projects",
        sa.Column("bgm_track_id", sa.String(255), nullable=True, comment="Pixabay track ID used for BGM"),
    )
    op.add_column(
        "video_projects",
        sa.Column("bgm_path", sa.String(1024), nullable=True, comment="Path to downloaded BGM audio file"),
    )


def downgrade() -> None:
    op.drop_column("video_projects", "bgm_path")
    op.drop_column("video_projects", "bgm_track_id")
    op.drop_column("video_projects", "bgm_mood")
