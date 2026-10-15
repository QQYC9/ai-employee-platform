"""add idempotency records

Revision ID: f4a8b1c2d3e4
Revises: d7d89b1f9794
Create Date: 2026-10-15 20:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f4a8b1c2d3e4'
down_revision: Union[str, Sequence[str], None] = 'd7d89b1f9794'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'idempotency_records',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('tool_id', sa.Uuid(), nullable=True),
        sa.Column('action', sa.String(length=150), nullable=False),
        sa.Column('resource', sa.String(length=150), nullable=True),
        sa.Column('parameters_hash', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=50), server_default='in_progress', nullable=False),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tool_id'], ['tools.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'idempotency_key', name='uq_tenant_idempotency_key')
    )
    op.create_index(op.f('ix_idempotency_records_tenant_id'), 'idempotency_records', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_idempotency_records_idempotency_key'), 'idempotency_records', ['idempotency_key'], unique=False)
    op.create_index(op.f('ix_idempotency_records_tool_id'), 'idempotency_records', ['tool_id'], unique=False)
    op.create_index(op.f('ix_idempotency_records_status'), 'idempotency_records', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_idempotency_records_status'), table_name='idempotency_records')
    op.drop_index(op.f('ix_idempotency_records_tool_id'), table_name='idempotency_records')
    op.drop_index(op.f('ix_idempotency_records_idempotency_key'), table_name='idempotency_records')
    op.drop_index(op.f('ix_idempotency_records_tenant_id'), table_name='idempotency_records')
    op.drop_table('idempotency_records')
