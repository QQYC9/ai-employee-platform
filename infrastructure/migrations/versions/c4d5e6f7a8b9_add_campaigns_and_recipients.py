"""add campaigns and campaign recipients tables

Revision ID: c4d5e6f7a8b9
Revises: a1b2c3d4e5f6
Create Date: 2026-10-23 18:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create campaigns table
    op.create_table(
        'campaigns',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('goal', sa.Text(), nullable=True),
        sa.Column('message_template', sa.Text(), nullable=False),
        sa.Column('channel_id', sa.Uuid(), nullable=True),
        sa.Column('status', sa.String(length=50), server_default='draft', nullable=False),
        sa.Column('audience_filter', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'metrics',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{"total_recipients": 0, "enqueued_count": 0, "sent_count": 0, "delivered_count": 0, "failed_count": 0, "skipped_count": 0}',
            nullable=False,
        ),
        sa.Column('requires_approval', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('approval_id', sa.Uuid(), nullable=True),
        sa.Column('rate_limit_per_minute', sa.Integer(), server_default='60', nullable=False),
        sa.Column('batch_size', sa.Integer(), server_default='50', nullable=False),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_campaigns_tenant_id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['approval_id'], ['approvals.id'], ondelete='SET NULL'),
    )
    op.create_index(op.f('ix_campaigns_tenant_id'), 'campaigns', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_campaigns_channel_id'), 'campaigns', ['channel_id'], unique=False)
    op.create_index(op.f('ix_campaigns_status'), 'campaigns', ['status'], unique=False)
    op.create_index(op.f('ix_campaigns_scheduled_at'), 'campaigns', ['scheduled_at'], unique=False)
    op.create_index('ix_campaigns_tenant_status', 'campaigns', ['tenant_id', 'status'], unique=False)

    # 2. Create campaign_recipients table
    op.create_table(
        'campaign_recipients',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('campaign_id', sa.Uuid(), nullable=False),
        sa.Column('customer_id', sa.Uuid(), nullable=False),
        sa.Column('channel_id', sa.Uuid(), nullable=True),
        sa.Column('recipient_address', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), server_default='pending', nullable=False),
        sa.Column('skip_reason', sa.String(length=255), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('message_id', sa.Uuid(), nullable=True),
        sa.Column('outbox_event_id', sa.Uuid(), nullable=True),
        sa.Column('rendered_content', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('campaign_id', 'customer_id', name='uq_campaign_recipient_customer'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_campaign_recipients_tenant_id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['outbox_event_id'], ['outbox_events.id'], ondelete='SET NULL'),
    )
    op.create_index(op.f('ix_campaign_recipients_tenant_id'), 'campaign_recipients', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_campaign_recipients_campaign_id'), 'campaign_recipients', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_campaign_recipients_customer_id'), 'campaign_recipients', ['customer_id'], unique=False)
    op.create_index(op.f('ix_campaign_recipients_status'), 'campaign_recipients', ['status'], unique=False)
    op.create_index('ix_campaign_recipients_campaign_status', 'campaign_recipients', ['campaign_id', 'status'], unique=False)


def downgrade() -> None:
    # 1. Drop campaign_recipients
    op.drop_index('ix_campaign_recipients_campaign_status', table_name='campaign_recipients')
    op.drop_index(op.f('ix_campaign_recipients_status'), table_name='campaign_recipients')
    op.drop_index(op.f('ix_campaign_recipients_customer_id'), table_name='campaign_recipients')
    op.drop_index(op.f('ix_campaign_recipients_campaign_id'), table_name='campaign_recipients')
    op.drop_index(op.f('ix_campaign_recipients_tenant_id'), table_name='campaign_recipients')
    op.drop_table('campaign_recipients')

    # 2. Drop campaigns
    op.drop_index('ix_campaigns_tenant_status', table_name='campaigns')
    op.drop_index(op.f('ix_campaigns_scheduled_at'), table_name='campaigns')
    op.drop_index(op.f('ix_campaigns_status'), table_name='campaigns')
    op.drop_index(op.f('ix_campaigns_channel_id'), table_name='campaigns')
    op.drop_index(op.f('ix_campaigns_tenant_id'), table_name='campaigns')
    op.drop_table('campaigns')
