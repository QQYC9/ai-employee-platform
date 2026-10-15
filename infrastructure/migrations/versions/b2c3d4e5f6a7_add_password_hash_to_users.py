"""add password_hash to users

Revision ID: b2c3d4e5f6a7
Revises: f4a8b1c2d3e4
Create Date: 2026-10-16 00:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'f4a8b1c2d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add password_hash column to users table."""
    op.add_column(
        'users',
        sa.Column('password_hash', sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema: remove password_hash column from users table."""
    op.drop_column('users', 'password_hash')
