"""add composite indexes for performance

Revision ID: b9f3e4d5c6a7
Revises: f19ac12d9af5
Create Date: 2026-03-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b9f3e4d5c6a7'
down_revision = 'f19ac12d9af5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOTE: ix_video_projects_status_created_at already exists from f6c0d6f1328b
    # NOTE: ix_video_projects_youtube_video_id already exists from f6c0d6f1328b

    # Composite index for telegram user queries: filter by user_id, order by created_at
    op.create_index(
        'ix_video_projects_telegram_user_created_at',
        'video_projects',
        ['telegram_user_id', 'created_at'],
        unique=False
    )

    # Composite index for project lookup with status filter
    op.create_index(
        'ix_video_projects_id_status',
        'video_projects',
        ['id', 'status'],
        unique=False
    )

    # Index on updated_at for cleanup queries (find old projects)
    op.create_index(
        'ix_video_projects_updated_at',
        'video_projects',
        ['updated_at'],
        unique=False
    )


def downgrade() -> None:
    # Drop only the indexes created in this migration
    op.drop_index('ix_video_projects_updated_at', table_name='video_projects')
    op.drop_index('ix_video_projects_id_status', table_name='video_projects')
    op.drop_index('ix_video_projects_telegram_user_created_at', table_name='video_projects')
