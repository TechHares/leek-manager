"""add_model_feature_config

Revision ID: a1b2c3d4e5f6
Revises: f4cee0271a9c
Create Date: 2025-01-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f4cee0271a9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add feature_config column to models table
    op.add_column('models', sa.Column('feature_config', sa.JSON(), nullable=True, comment='Feature configuration used for training'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('models', 'feature_config')
