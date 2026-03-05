"""add thumbnail_path to video_projects

Revision ID: c8d4e3f2a1b0
Revises: b9f3e4d5c6a7
Create Date: 2026-03-03 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8d4e3f2a1b0'
down_revision = 'b9f3e4d5c6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add thumbnail_path column to video_projects table
    op.add_column(
        'video_projects',
        sa.Column(
            'thumbnail_path',
            sa.String(length=1024),
            nullable=True,
            comment='Path to video thumbnail (JPEG extracted from middle frame)'
        )
    )


def downgrade() -> None:
    # Remove the column
    op.drop_column('video_projects', 'thumbnail_path')
