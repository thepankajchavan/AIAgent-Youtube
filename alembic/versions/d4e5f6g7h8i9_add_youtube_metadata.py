"""Add YouTube metadata columns to video_projects

Revision ID: d4e5f6g7h8i9
Revises: 3967a5f94766
Create Date: 2026-03-12

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4e5f6g7h8i9"
down_revision = "c2d3e4f5g6h7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "video_projects",
        sa.Column("youtube_title", sa.String(200), nullable=True, comment="Video title used on YouTube"),
    )
    op.add_column(
        "video_projects",
        sa.Column("youtube_description", sa.Text(), nullable=True, comment="SEO description used on YouTube"),
    )
    op.add_column(
        "video_projects",
        sa.Column("youtube_tags", sa.JSON(), nullable=True, comment="Tags list used on YouTube"),
    )
    op.add_column(
        "video_projects",
        sa.Column("youtube_hashtags", sa.JSON(), nullable=True, comment="Hashtags list used on YouTube"),
    )
    op.add_column(
        "video_projects",
        sa.Column("youtube_category", sa.String(50), nullable=True, comment="YouTube category used"),
    )


def downgrade() -> None:
    op.drop_column("video_projects", "youtube_category")
    op.drop_column("video_projects", "youtube_hashtags")
    op.drop_column("video_projects", "youtube_tags")
    op.drop_column("video_projects", "youtube_description")
    op.drop_column("video_projects", "youtube_title")
