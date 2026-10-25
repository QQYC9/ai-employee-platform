"""add owner_inquiries table for Phase 1 inquiry loop

Revision ID: c1d2e3f4a5b6
Revises: b3c4d5e6f7a8
Create Date: 2026-10-26 02:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'owner_inquiries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column(
            'inquiry_number',
            sa.Integer(),
            sa.Identity(start=1, increment=1),
            nullable=False,
        ),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('customer_conversation_id', sa.Uuid(), nullable=False),
        sa.Column('customer_sender', sa.String(length=255), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('normalized_question', sa.String(length=500), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default=sa.text("'open'")),
        sa.Column('owner_answer', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column('asked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('owner_notification_message_id', sa.String(length=255), nullable=True),
        sa.Column('reminded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('timeout_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scope', sa.String(length=50), nullable=False, server_default=sa.text("'public'")),
        sa.Column('waiting_customers', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('inquiry_number', name='uq_owner_inquiries_number'),
    )
    op.create_index(op.f('ix_owner_inquiries_tenant_id'), 'owner_inquiries', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_owner_inquiries_customer_conversation_id'), 'owner_inquiries', ['customer_conversation_id'], unique=False)
    op.create_index(op.f('ix_owner_inquiries_customer_sender'), 'owner_inquiries', ['customer_sender'], unique=False)
    op.create_index(op.f('ix_owner_inquiries_normalized_question'), 'owner_inquiries', ['normalized_question'], unique=False)
    op.create_index(op.f('ix_owner_inquiries_status'), 'owner_inquiries', ['status'], unique=False)
    op.create_index(op.f('ix_owner_inquiries_owner_notification_message_id'), 'owner_inquiries', ['owner_notification_message_id'], unique=False)
    op.create_index('ix_owner_inquiries_tenant_normalized', 'owner_inquiries', ['tenant_id', 'normalized_question'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_owner_inquiries_tenant_normalized', table_name='owner_inquiries')
    op.drop_index(op.f('ix_owner_inquiries_owner_notification_message_id'), table_name='owner_inquiries')
    op.drop_index(op.f('ix_owner_inquiries_status'), table_name='owner_inquiries')
    op.drop_index(op.f('ix_owner_inquiries_normalized_question'), table_name='owner_inquiries')
    op.drop_index(op.f('ix_owner_inquiries_customer_sender'), table_name='owner_inquiries')
    op.drop_index(op.f('ix_owner_inquiries_customer_conversation_id'), table_name='owner_inquiries')
    op.drop_index(op.f('ix_owner_inquiries_tenant_id'), table_name='owner_inquiries')
    op.drop_table('owner_inquiries')
