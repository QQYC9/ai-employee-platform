"""add token and expires_at to approvals and partial index on proactive_workflows

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-10-25 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add token and expires_at columns to approvals table
    op.add_column(
        'approvals',
        sa.Column('token', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'approvals',
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_approvals_token',
        'approvals',
        ['token'],
        unique=False,
    )
    op.create_index(
        'ix_approvals_expires_at',
        'approvals',
        ['expires_at'],
        unique=False,
    )

    # 2. Backfill existing legacy records where token or expires_at are in description tags
    op.execute(
        sa.text("""
            UPDATE approvals
            SET token = substring(description from '\\[TOKEN:\\s*([A-Za-z0-9_-]+)\\]')
            WHERE description ~ '\\[TOKEN:\\s*[A-Za-z0-9_-]+\\]'
              AND token IS NULL;
        """)
    )
    op.execute(
        sa.text("""
            UPDATE approvals
            SET expires_at = (substring(description from '\\[EXPIRES:\\s*([^\\]]+)\\]'))::timestamptz
            WHERE description ~ '\\[EXPIRES:\\s*\\d{4}-\\d{2}-\\d{2}T'
              AND expires_at IS NULL;
        """)
    )

    # 3. Add partial unique index on proactive_workflows for continuous_learning_cycle
    op.create_index(
        'uq_tenant_continuous_learning_workflow',
        'proactive_workflows',
        ['tenant_id', 'action_type'],
        unique=True,
        postgresql_where=sa.text("action_type = 'continuous_learning_cycle'"),
    )


def downgrade() -> None:
    # 1. Drop partial unique index on proactive_workflows
    op.drop_index(
        'uq_tenant_continuous_learning_workflow',
        table_name='proactive_workflows',
        postgresql_where=sa.text("action_type = 'continuous_learning_cycle'"),
    )

    # 2. Drop indexes on approvals
    op.drop_index('ix_approvals_expires_at', table_name='approvals')
    op.drop_index('ix_approvals_token', table_name='approvals')

    # 3. Drop columns on approvals
    op.drop_column('approvals', 'expires_at')
    op.drop_column('approvals', 'token')
