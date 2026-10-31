"""add_cr0501_owner_approval_anti_hijack

Revision ID: 2a3b4c5d6e7f
Revises: 16142be6ce15
Create Date: 2026-10-31 19:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '2a3b4c5d6e7f'
down_revision: Union[str, Sequence[str], None] = '16142be6ce15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # 1. Upgrade table 'approvals'
    # =========================================================================
    op.add_column(
        'approvals',
        sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default=sa.text('0')),
    )
    op.add_column(
        'approvals',
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default=sa.text('3')),
    )
    op.add_column(
        'approvals',
        sa.Column('payload_hash', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'approvals',
        sa.Column('parameters_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        'approvals',
        sa.Column('execution_status', sa.String(length=50), nullable=False, server_default=sa.text("'not_started'")),
    )
    op.add_column(
        'approvals',
        sa.Column('idempotency_key', sa.String(length=255), nullable=True),
    )

    # Indexes and constraints on 'approvals'
    op.create_index(
        'ix_approvals_execution_status',
        'approvals',
        ['tenant_id', 'execution_status'],
        unique=False,
    )
    op.create_unique_constraint(
        'uq_approvals_tenant_idempotency_key',
        'approvals',
        ['tenant_id', 'idempotency_key'],
    )

    # =========================================================================
    # 2. Upgrade table 'outbox_events'
    # =========================================================================
    # Make conversation_id and message_id nullable for non-message events (e.g. approval_action_execution)
    op.alter_column('outbox_events', 'conversation_id', nullable=True)
    op.alter_column('outbox_events', 'message_id', nullable=True)

    # Add approval_id and first_external_attempt_at
    op.add_column(
        'outbox_events',
        sa.Column('approval_id', sa.Uuid(), nullable=True),
    )
    op.add_column(
        'outbox_events',
        sa.Column('first_external_attempt_at', sa.DateTime(timezone=True), nullable=True),
    )

    # Index on approval_id
    op.create_index(
        'ix_outbox_events_approval_id',
        'outbox_events',
        ['approval_id'],
        unique=False,
    )

    # Composite Foreign Key: (tenant_id, approval_id) -> approvals(tenant_id, id) ON DELETE RESTRICT
    # Targets existing constraint uq_approvals_tenant_id on approvals(tenant_id, id)
    op.create_foreign_key(
        'fk_outbox_events_approval_composite',
        'outbox_events',
        'approvals',
        ['tenant_id', 'approval_id'],
        ['tenant_id', 'id'],
        ondelete='RESTRICT',
    )

    # Check constraint: event_type != 'approval_action_execution' OR approval_id IS NOT NULL
    op.create_check_constraint(
        'ck_outbox_approval_execution_requires_approval_id',
        'outbox_events',
        sa.text("event_type != 'approval_action_execution' OR approval_id IS NOT NULL"),
    )

    # Partial Unique Index: exactly one execution event per approval per tenant
    op.create_index(
        'uq_outbox_tenant_approval_execution',
        'outbox_events',
        ['tenant_id', 'approval_id'],
        unique=True,
        postgresql_where=sa.text("event_type = 'approval_action_execution'"),
    )


def downgrade() -> None:
    # 2. Revert outbox_events
    op.drop_index('uq_outbox_tenant_approval_execution', table_name='outbox_events')
    op.drop_constraint('ck_outbox_approval_execution_requires_approval_id', 'outbox_events', type_='check')
    op.drop_constraint('fk_outbox_events_approval_composite', 'outbox_events', type_='foreignkey')
    op.drop_index('ix_outbox_events_approval_id', table_name='outbox_events')
    op.drop_column('outbox_events', 'first_external_attempt_at')
    op.drop_column('outbox_events', 'approval_id')
    op.alter_column('outbox_events', 'message_id', nullable=False)
    op.alter_column('outbox_events', 'conversation_id', nullable=False)

    # 1. Revert approvals
    op.drop_constraint('uq_approvals_tenant_idempotency_key', 'approvals', type_='unique')
    op.drop_index('ix_approvals_execution_status', table_name='approvals')
    op.drop_column('approvals', 'idempotency_key')
    op.drop_column('approvals', 'execution_status')
    op.drop_column('approvals', 'parameters_json')
    op.drop_column('approvals', 'payload_hash')
    op.drop_column('approvals', 'max_attempts')
    op.drop_column('approvals', 'failed_attempts')
