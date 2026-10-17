"""add outbox_events table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create outbox_events table for transactional outbox pattern."""
    op.create_table(
        'outbox_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=100), server_default='process_incoming_message', nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('conversation_id', sa.Uuid(), nullable=False),
        sa.Column('message_id', sa.Uuid(), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('status', sa.String(length=50), server_default='pending', nullable=False),
        sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_attempts', sa.Integer(), server_default='5', nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('locked_by', sa.String(length=255), nullable=True),
        sa.Column('lock_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'idempotency_key', name='uq_tenant_outbox_idempotency_key'),
    )
    op.create_index(op.f('ix_outbox_events_tenant_id'), 'outbox_events', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_outbox_events_event_type'), 'outbox_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_outbox_events_idempotency_key'), 'outbox_events', ['idempotency_key'], unique=False)
    op.create_index(op.f('ix_outbox_events_conversation_id'), 'outbox_events', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_outbox_events_message_id'), 'outbox_events', ['message_id'], unique=False)
    op.create_index(op.f('ix_outbox_events_status'), 'outbox_events', ['status'], unique=False)
    op.create_index(op.f('ix_outbox_events_scheduled_at'), 'outbox_events', ['scheduled_at'], unique=False)
    op.create_index(op.f('ix_outbox_events_lock_expires_at'), 'outbox_events', ['lock_expires_at'], unique=False)
    op.create_index('ix_outbox_events_claim', 'outbox_events', ['status', 'scheduled_at'], unique=False)


def downgrade() -> None:
    """Drop outbox_events table."""
    op.drop_index('ix_outbox_events_claim', table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_lock_expires_at'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_scheduled_at'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_status'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_message_id'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_conversation_id'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_idempotency_key'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_event_type'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_tenant_id'), table_name='outbox_events')
    op.drop_table('outbox_events')
