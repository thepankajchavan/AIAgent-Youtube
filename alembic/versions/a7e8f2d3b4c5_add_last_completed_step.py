"""add last_completed_step to VideoProject

Revision ID: a7e8f2d3b4c5
Revises: 2570d3ae3726
Create Date: 2026-03-03 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7e8f2d3b4c5'
down_revision = '2570d3ae3726'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add last_completed_step column to video_projects table
    op.add_column(
        'video_projects',
        sa.Column('last_completed_step', sa.String(length=50), nullable=True)
    )

    # Add artifacts_available column to track if intermediate files exist
    op.add_column(
        'video_projects',
        sa.Column('artifacts_available', sa.JSON, nullable=True, server_default='{}')
    )


def downgrade() -> None:
    # Remove the columns
    op.drop_column('video_projects', 'artifacts_available')
    op.drop_column('video_projects', 'last_completed_step')
