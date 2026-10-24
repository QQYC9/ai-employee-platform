"""add execution traces and steps tables with comprehensive composite foreign keys

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-10-23 03:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add UniqueConstraint('tenant_id', 'id') to referenced tables if not present
    op.create_unique_constraint('uq_agents_tenant_id', 'agents', ['tenant_id', 'id'])
    op.create_unique_constraint('uq_tasks_tenant_id', 'tasks', ['tenant_id', 'id'])
    op.create_unique_constraint('uq_conversations_tenant_id', 'conversations', ['tenant_id', 'id'])
    op.create_unique_constraint('uq_messages_tenant_id', 'messages', ['tenant_id', 'id'])
    op.create_unique_constraint('uq_approvals_tenant_id', 'approvals', ['tenant_id', 'id'])
    op.create_unique_constraint('uq_outbox_events_tenant_id', 'outbox_events', ['tenant_id', 'id'])

    # 2. Create execution_traces table
    op.create_table(
        'execution_traces',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('trace_id', sa.Uuid(), nullable=False),
        sa.Column('trigger_type', sa.String(length=50), server_default='inbound_message', nullable=False),
        sa.Column('conversation_id', sa.Uuid(), nullable=True),
        sa.Column('inbound_message_id', sa.Uuid(), nullable=True),
        sa.Column('reply_message_id', sa.Uuid(), nullable=True),
        sa.Column('task_id', sa.Uuid(), nullable=True),
        sa.Column('agent_id', sa.Uuid(), nullable=True),
        sa.Column('status', sa.String(length=50), server_default='running', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('error_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trace_id', name='uq_execution_traces_trace_id'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_execution_traces_tenant_id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'conversation_id'],
            ['conversations.tenant_id', 'conversations.id'],
            ondelete='SET NULL (conversation_id)',
            name='fk_traces_conversation_tenant',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'inbound_message_id'],
            ['messages.tenant_id', 'messages.id'],
            ondelete='SET NULL (inbound_message_id)',
            name='fk_traces_inbound_msg_tenant',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'reply_message_id'],
            ['messages.tenant_id', 'messages.id'],
            ondelete='SET NULL (reply_message_id)',
            name='fk_traces_reply_msg_tenant',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'task_id'],
            ['tasks.tenant_id', 'tasks.id'],
            ondelete='SET NULL (task_id)',
            name='fk_traces_task_tenant',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'agent_id'],
            ['agents.tenant_id', 'agents.id'],
            ondelete='SET NULL (agent_id)',
            name='fk_traces_agent_tenant',
        ),
    )
    op.create_index(op.f('ix_execution_traces_tenant_id'), 'execution_traces', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_execution_traces_trace_id'), 'execution_traces', ['trace_id'], unique=True)
    op.create_index(op.f('ix_execution_traces_status'), 'execution_traces', ['status'], unique=False)
    op.create_index(op.f('ix_execution_traces_started_at'), 'execution_traces', ['started_at'], unique=False)
    op.create_index(op.f('ix_execution_traces_conversation_id'), 'execution_traces', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_execution_traces_task_id'), 'execution_traces', ['task_id'], unique=False)
    op.create_index('ix_execution_traces_tenant_status', 'execution_traces', ['tenant_id', 'status'], unique=False)
    op.create_index('ix_execution_traces_tenant_created', 'execution_traces', ['tenant_id', 'created_at'], unique=False)

    # 3. Create execution_steps table
    op.create_table(
        'execution_steps',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('trace_id', sa.Uuid(), nullable=False),
        sa.Column('parent_step_id', sa.Uuid(), nullable=True),
        sa.Column('task_id', sa.Uuid(), nullable=True),
        sa.Column('approval_id', sa.Uuid(), nullable=True),
        sa.Column('outbox_event_id', sa.Uuid(), nullable=True),
        sa.Column('step_order', sa.Integer(), server_default='1', nullable=False),
        sa.Column('step_type', sa.String(length=50), nullable=False),
        sa.Column('step_name', sa.String(length=150), nullable=False),
        sa.Column('status', sa.String(length=50), server_default='pending', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), server_default='1', nullable=False),
        sa.Column('attempts_history', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('input_summary', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('output_summary', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('error_info', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('idempotency_key', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'id', name='uq_execution_steps_tenant_id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'trace_id'],
            ['execution_traces.tenant_id', 'execution_traces.id'],
            ondelete='CASCADE',
            name='fk_steps_trace_tenant',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'parent_step_id'],
            ['execution_steps.tenant_id', 'execution_steps.id'],
            ondelete='CASCADE',
            name='fk_steps_parent_tenant',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'task_id'],
            ['tasks.tenant_id', 'tasks.id'],
            ondelete='SET NULL (task_id)',
            name='fk_steps_task_tenant',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'approval_id'],
            ['approvals.tenant_id', 'approvals.id'],
            ondelete='SET NULL (approval_id)',
            name='fk_steps_approval_tenant',
        ),
        sa.ForeignKeyConstraint(
            ['tenant_id', 'outbox_event_id'],
            ['outbox_events.tenant_id', 'outbox_events.id'],
            ondelete='SET NULL (outbox_event_id)',
            name='fk_steps_outbox_event_tenant',
        ),
    )
    op.create_index(op.f('ix_execution_steps_tenant_id'), 'execution_steps', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_execution_steps_trace_id'), 'execution_steps', ['trace_id'], unique=False)
    op.create_index(op.f('ix_execution_steps_parent_step_id'), 'execution_steps', ['parent_step_id'], unique=False)
    op.create_index(op.f('ix_execution_steps_status'), 'execution_steps', ['status'], unique=False)
    op.create_index(op.f('ix_execution_steps_step_type'), 'execution_steps', ['step_type'], unique=False)
    op.create_index(op.f('ix_execution_steps_started_at'), 'execution_steps', ['started_at'], unique=False)
    op.create_index(op.f('ix_execution_steps_idempotency_key'), 'execution_steps', ['idempotency_key'], unique=False)
    op.create_index('ix_execution_steps_tenant_trace_order', 'execution_steps', ['tenant_id', 'trace_id', 'step_order'], unique=False)
    op.create_index('ix_execution_steps_tenant_status', 'execution_steps', ['tenant_id', 'status'], unique=False)


def downgrade() -> None:
    # 1. Drop execution_steps
    op.drop_index('ix_execution_steps_tenant_status', table_name='execution_steps')
    op.drop_index('ix_execution_steps_tenant_trace_order', table_name='execution_steps')
    op.drop_index(op.f('ix_execution_steps_idempotency_key'), table_name='execution_steps')
    op.drop_index(op.f('ix_execution_steps_started_at'), table_name='execution_steps')
    op.drop_index(op.f('ix_execution_steps_step_type'), table_name='execution_steps')
    op.drop_index(op.f('ix_execution_steps_status'), table_name='execution_steps')
    op.drop_index(op.f('ix_execution_steps_parent_step_id'), table_name='execution_steps')
    op.drop_index(op.f('ix_execution_steps_trace_id'), table_name='execution_steps')
    op.drop_index(op.f('ix_execution_steps_tenant_id'), table_name='execution_steps')
    op.drop_table('execution_steps')

    # 2. Drop execution_traces
    op.drop_index('ix_execution_traces_tenant_created', table_name='execution_traces')
    op.drop_index('ix_execution_traces_tenant_status', table_name='execution_traces')
    op.drop_index(op.f('ix_execution_traces_task_id'), table_name='execution_traces')
    op.drop_index(op.f('ix_execution_traces_conversation_id'), table_name='execution_traces')
    op.drop_index(op.f('ix_execution_traces_started_at'), table_name='execution_traces')
    op.drop_index(op.f('ix_execution_traces_status'), table_name='execution_traces')
    op.drop_index(op.f('ix_execution_traces_trace_id'), table_name='execution_traces')
    op.drop_index(op.f('ix_execution_traces_tenant_id'), table_name='execution_traces')
    op.drop_table('execution_traces')

    # 3. Drop referenced UniqueConstraints
    op.drop_constraint('uq_outbox_events_tenant_id', 'outbox_events', type_='unique')
    op.drop_constraint('uq_approvals_tenant_id', 'approvals', type_='unique')
    op.drop_constraint('uq_messages_tenant_id', 'messages', type_='unique')
    op.drop_constraint('uq_conversations_tenant_id', 'conversations', type_='unique')
    op.drop_constraint('uq_tasks_tenant_id', 'tasks', type_='unique')
    op.drop_constraint('uq_agents_tenant_id', 'agents', type_='unique')
