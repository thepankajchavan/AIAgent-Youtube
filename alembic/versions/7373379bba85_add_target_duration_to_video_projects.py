"""add_target_duration_to_video_projects

Revision ID: 7373379bba85
Revises: d1e2f3a4b5c6
Create Date: 2026-03-06 18:29:25.081597
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7373379bba85'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'video_projects',
        sa.Column(
            'target_duration',
            sa.Integer(),
            nullable=True,
            comment='User-requested target duration in seconds',
        ),
    )


def downgrade() -> None:
    op.drop_column('video_projects', 'target_duration')
