"""add proactive_workflows and ai_metrics tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. proactive_workflows
    op.create_table(
        'proactive_workflows',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('agent_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('trigger_type', sa.String(length=50), server_default='schedule', nullable=False),
        sa.Column('schedule_type', sa.String(length=50), server_default='interval', nullable=False),
        sa.Column('cron_expression', sa.String(length=100), nullable=True),
        sa.Column('interval_seconds', sa.Integer(), nullable=True),
        sa.Column('timezone', sa.String(length=100), server_default='UTC', nullable=False),
        sa.Column('action_type', sa.String(length=100), server_default='run_task', nullable=False),
        sa.Column('action_payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('status', sa.String(length=50), server_default='active', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_runs', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_retries', sa.Integer(), server_default='3', nullable=False),
        sa.Column('retry_backoff_seconds', sa.Integer(), server_default='30', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_proactive_workflows_tenant_id'), 'proactive_workflows', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_proactive_workflows_agent_id'), 'proactive_workflows', ['agent_id'], unique=False)
    op.create_index(op.f('ix_proactive_workflows_trigger_type'), 'proactive_workflows', ['trigger_type'], unique=False)
    op.create_index(op.f('ix_proactive_workflows_action_type'), 'proactive_workflows', ['action_type'], unique=False)
    op.create_index(op.f('ix_proactive_workflows_status'), 'proactive_workflows', ['status'], unique=False)
    op.create_index(op.f('ix_proactive_workflows_is_active'), 'proactive_workflows', ['is_active'], unique=False)
    op.create_index(op.f('ix_proactive_workflows_next_run_at'), 'proactive_workflows', ['next_run_at'], unique=False)

    # 2. workflow_runs
    op.create_table(
        'workflow_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('workflow_id', sa.Uuid(), nullable=False),
        sa.Column('task_id', sa.Uuid(), nullable=True),
        sa.Column('trigger_source', sa.String(length=50), server_default='schedule', nullable=False),
        sa.Column('trigger_event_id', sa.String(length=255), nullable=True),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=50), server_default='pending', nullable=False),
        sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_attempts', sa.Integer(), server_default='3', nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('locked_by', sa.String(length=255), nullable=True),
        sa.Column('lock_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workflow_id'], ['proactive_workflows.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'idempotency_key', name='uq_tenant_workflow_run_idempotency'),
    )
    op.create_index(op.f('ix_workflow_runs_tenant_id'), 'workflow_runs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_workflow_runs_workflow_id'), 'workflow_runs', ['workflow_id'], unique=False)
    op.create_index(op.f('ix_workflow_runs_task_id'), 'workflow_runs', ['task_id'], unique=False)
    op.create_index(op.f('ix_workflow_runs_idempotency_key'), 'workflow_runs', ['idempotency_key'], unique=False)
    op.create_index(op.f('ix_workflow_runs_status'), 'workflow_runs', ['status'], unique=False)
    op.create_index(op.f('ix_workflow_runs_scheduled_at'), 'workflow_runs', ['scheduled_at'], unique=False)
    op.create_index(op.f('ix_workflow_runs_lock_expires_at'), 'workflow_runs', ['lock_expires_at'], unique=False)
    op.create_index('ix_workflow_runs_claim', 'workflow_runs', ['status', 'scheduled_at'], unique=False)

    # 3. workflow_trigger_events
    op.create_table(
        'workflow_trigger_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('source_id', sa.String(length=255), nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('status', sa.String(length=50), server_default='pending', nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'idempotency_key', name='uq_tenant_trigger_event_idempotency'),
    )
    op.create_index(op.f('ix_workflow_trigger_events_tenant_id'), 'workflow_trigger_events', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_workflow_trigger_events_event_type'), 'workflow_trigger_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_workflow_trigger_events_idempotency_key'), 'workflow_trigger_events', ['idempotency_key'], unique=False)
    op.create_index(op.f('ix_workflow_trigger_events_status'), 'workflow_trigger_events', ['status'], unique=False)

    # 4. ai_usage_logs
    op.create_table(
        'ai_usage_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('model', sa.String(length=150), nullable=False),
        sa.Column('prompt_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('completion_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('total_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('duration_ms', sa.Integer(), server_default='0', nullable=False),
        sa.Column('status', sa.String(length=50), server_default='success', nullable=False),
        sa.Column('error_category', sa.String(length=50), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('fallback_from_provider', sa.String(length=50), nullable=True),
        sa.Column('fallback_reason', sa.String(length=255), nullable=True),
        sa.Column('task_id', sa.Uuid(), nullable=True),
        sa.Column('conversation_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ai_usage_logs_tenant_id'), 'ai_usage_logs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_provider'), 'ai_usage_logs', ['provider'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_model'), 'ai_usage_logs', ['model'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_status'), 'ai_usage_logs', ['status'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_task_id'), 'ai_usage_logs', ['task_id'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_conversation_id'), 'ai_usage_logs', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_ai_usage_logs_created_at'), 'ai_usage_logs', ['created_at'], unique=False)

    # 5. tenant_ai_budgets
    op.create_table(
        'tenant_ai_budgets',
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('daily_token_limit', sa.Integer(), nullable=True),
        sa.Column('monthly_token_limit', sa.Integer(), nullable=True),
        sa.Column('is_hard_limit', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('current_day_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('current_month_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_reset_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('tenant_id'),
    )


def downgrade() -> None:
    op.drop_table('tenant_ai_budgets')
    op.drop_table('ai_usage_logs')
    op.drop_table('workflow_trigger_events')
    op.drop_table('workflow_runs')
    op.drop_table('proactive_workflows')
