"""add performance indexes

Revision ID: f6c0d6f1328b
Revises: 182ef49c0f06
Create Date: 2026-03-03 12:08:46.890102
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6c0d6f1328b'
down_revision: Union[str, None] = '182ef49c0f06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### Performance indexes for video_projects table ###

    # 1. Index on status for filtering by status
    op.create_index(
        'ix_video_projects_status',
        'video_projects',
        ['status'],
        unique=False
    )

    # 2. Index on created_at for sorting by creation time
    op.create_index(
        'ix_video_projects_created_at',
        'video_projects',
        ['created_at'],
        unique=False
    )

    # 3. Partial index on celery_task_id (only non-null values)
    op.create_index(
        'ix_video_projects_celery_task_id',
        'video_projects',
        ['celery_task_id'],
        unique=False,
        postgresql_where=sa.text('celery_task_id IS NOT NULL')
    )

    # 4. Unique partial index on youtube_video_id (only non-null values)
    op.create_index(
        'ix_video_projects_youtube_video_id',
        'video_projects',
        ['youtube_video_id'],
        unique=True,
        postgresql_where=sa.text('youtube_video_id IS NOT NULL')
    )

    # 5. Composite index on status and created_at for filtered, sorted lists
    op.create_index(
        'ix_video_projects_status_created_at',
        'video_projects',
        ['status', 'created_at'],
        unique=False
    )


def downgrade() -> None:
    # ### Drop indexes in reverse order ###
    op.drop_index('ix_video_projects_status_created_at', table_name='video_projects')
    op.drop_index('ix_video_projects_youtube_video_id', table_name='video_projects')
    op.drop_index('ix_video_projects_celery_task_id', table_name='video_projects')
    op.drop_index('ix_video_projects_created_at', table_name='video_projects')
    op.drop_index('ix_video_projects_status', table_name='video_projects')
