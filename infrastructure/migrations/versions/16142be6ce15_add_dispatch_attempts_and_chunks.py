"""add_dispatch_attempts_and_chunks

Revision ID: 16142be6ce15
Revises: c1d2e3f4a5b6
Create Date: 2026-10-31 17:41:02.790604

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16142be6ce15'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Upgrade outbox_events with claim_generation and dispatch_attempts_count
    op.add_column(
        'outbox_events',
        sa.Column('claim_generation', sa.Integer(), nullable=False, server_default=sa.text('0')),
    )
    op.add_column(
        'outbox_events',
        sa.Column('dispatch_attempts_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
    )

    # 2. Create dispatch_attempts table
    op.create_table(
        'dispatch_attempts',
        sa.Column('id', sa.Uuid(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('campaign_id', sa.Uuid(), nullable=False),
        sa.Column('recipient_id', sa.Uuid(), nullable=False),
        sa.Column('outbox_event_id', sa.Uuid(), nullable=False),
        sa.Column('message_id', sa.Uuid(), nullable=True),
        sa.Column('claim_generation', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default=sa.text("'claimed'")),
        sa.Column('outcome_category', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('dispatch_intent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('external_message_id', sa.String(length=255), nullable=True),
        sa.Column('transport_phase', sa.String(length=50), nullable=True),
        sa.Column('error_type', sa.String(length=100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('late_result_recorded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('late_result_category', sa.String(length=50), nullable=True),
        sa.Column('late_external_id', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.PrimaryKeyConstraint('id', name='pk_dispatch_attempts'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='RESTRICT', name='fk_attempts_tenant'),
        sa.ForeignKeyConstraint(['tenant_id', 'campaign_id'], ['campaigns.tenant_id', 'campaigns.id'], ondelete='RESTRICT', name='fk_attempts_campaign_composite'),
        sa.ForeignKeyConstraint(['tenant_id', 'recipient_id'], ['campaign_recipients.tenant_id', 'campaign_recipients.id'], ondelete='RESTRICT', name='fk_attempts_recipient_composite'),
        sa.ForeignKeyConstraint(['tenant_id', 'outbox_event_id'], ['outbox_events.tenant_id', 'outbox_events.id'], ondelete='RESTRICT', name='fk_attempts_outbox_composite'),
        sa.ForeignKeyConstraint(['tenant_id', 'message_id'], ['messages.tenant_id', 'messages.id'], ondelete='RESTRICT', name='fk_attempts_message_composite'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_dispatch_attempts_tenant_id'),
        sa.UniqueConstraint('outbox_event_id', 'claim_generation', name='uq_dispatch_attempts_event_generation'),
        sa.CheckConstraint(
            "status IN ('claimed', 'dispatching', 'accepted', 'rejected', 'indeterminate', 'reconciled')",
            name='chk_attempt_status',
        ),
        sa.CheckConstraint(
            "outcome_category IS NULL OR outcome_category IN ("
            "'provider_accepted', 'provider_rejected', 'connect_timeout_safe', 'connect_error_safe', "
            "'read_timeout_indeterminate', 'write_timeout_indeterminate', 'crash_indeterminate', "
            "'protocol_error_indeterminate', 'permanent_error', 'rate_limited_retry')",
            name='chk_attempt_outcome',
        ),
    )
    op.create_index('ix_dispatch_attempts_tenant_status', 'dispatch_attempts', ['tenant_id', 'status'], unique=False)
    op.create_index('ix_dispatch_attempts_recipient_status', 'dispatch_attempts', ['tenant_id', 'recipient_id', 'status'], unique=False)
    op.create_index('ix_dispatch_attempts_event_lookup', 'dispatch_attempts', ['tenant_id', 'outbox_event_id'], unique=False)

    # 3. Create dispatch_attempt_chunks table
    op.create_table(
        'dispatch_attempt_chunks',
        sa.Column('id', sa.Uuid(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('attempt_id', sa.Uuid(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default=sa.text("'pending'")),
        sa.Column('outcome_category', sa.String(length=50), nullable=True),
        sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('external_message_id', sa.String(length=255), nullable=True),
        sa.Column('transport_phase', sa.String(length=50), nullable=True),
        sa.Column('error_type', sa.String(length=100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('clock_timestamp()')),
        sa.PrimaryKeyConstraint('id', name='pk_dispatch_attempt_chunks'),
        sa.ForeignKeyConstraint(['tenant_id', 'attempt_id'], ['dispatch_attempts.tenant_id', 'dispatch_attempts.id'], ondelete='RESTRICT', name='fk_chunks_attempt_tenant_composite'),
        sa.UniqueConstraint('attempt_id', 'chunk_index', name='uq_chunk_attempt_index'),
        sa.CheckConstraint('chunk_index >= 0', name='chk_chunk_index_positive'),
        sa.CheckConstraint(
            "status IN ('pending', 'dispatching', 'accepted', 'rejected', 'indeterminate')",
            name='chk_chunk_status',
        ),
    )
    op.create_index('ix_dispatch_attempt_chunks_lookup', 'dispatch_attempt_chunks', ['tenant_id', 'attempt_id', 'chunk_index'], unique=False)
    op.create_index(
        'ix_dispatch_attempt_chunks_ext_id',
        'dispatch_attempt_chunks',
        ['tenant_id', 'external_message_id'],
        postgresql_where=sa.text('external_message_id IS NOT NULL'),
        unique=False,
    )


def downgrade() -> None:
    # 1. Drop dispatch_attempt_chunks
    op.drop_index('ix_dispatch_attempt_chunks_ext_id', table_name='dispatch_attempt_chunks')
    op.drop_index('ix_dispatch_attempt_chunks_lookup', table_name='dispatch_attempt_chunks')
    op.drop_table('dispatch_attempt_chunks')

    # 2. Drop dispatch_attempts
    op.drop_index('ix_dispatch_attempts_event_lookup', table_name='dispatch_attempts')
    op.drop_index('ix_dispatch_attempts_recipient_status', table_name='dispatch_attempts')
    op.drop_index('ix_dispatch_attempts_tenant_status', table_name='dispatch_attempts')
    op.drop_table('dispatch_attempts')

    # 3. Revert outbox_events columns
    op.drop_column('outbox_events', 'dispatch_attempts_count')
    op.drop_column('outbox_events', 'claim_generation')
