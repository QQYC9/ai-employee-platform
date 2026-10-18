"""add self development and capability versions tables

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-10-18 18:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create capability_versions table
    op.create_table(
        'capability_versions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('capability_id', sa.Uuid(), nullable=True),
        sa.Column('request_id', sa.Uuid(), nullable=True),
        sa.Column('version_number', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('slug', sa.String(length=150), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('specification', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('implementation_code', sa.Text(), nullable=True),
        sa.Column('risk_level', sa.String(length=50), server_default='medium', nullable=False),
        sa.Column('status', sa.String(length=50), server_default='draft', nullable=False),
        sa.Column('approval_id', sa.Uuid(), nullable=True),
        sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('test_results', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rolled_back_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rollback_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['capability_id'], ['capabilities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['request_id'], ['development_requests.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['approval_id'], ['approvals.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_capability_versions_tenant_id'), 'capability_versions', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_capability_versions_capability_id'), 'capability_versions', ['capability_id'], unique=False)
    op.create_index(op.f('ix_capability_versions_request_id'), 'capability_versions', ['request_id'], unique=False)
    op.create_index(op.f('ix_capability_versions_slug'), 'capability_versions', ['slug'], unique=False)
    op.create_index(op.f('ix_capability_versions_risk_level'), 'capability_versions', ['risk_level'], unique=False)
    op.create_index(op.f('ix_capability_versions_status'), 'capability_versions', ['status'], unique=False)
    op.create_index(op.f('ix_capability_versions_approval_id'), 'capability_versions', ['approval_id'], unique=False)
    op.create_index(op.f('ix_capability_versions_created_at'), 'capability_versions', ['created_at'], unique=False)

    # 2. Create development_runs table
    op.create_table(
        'development_runs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('request_id', sa.Uuid(), nullable=True),
        sa.Column('capability_version_id', sa.Uuid(), nullable=True),
        sa.Column('run_type', sa.String(length=100), server_default='sandbox_test', nullable=False),
        sa.Column('status', sa.String(length=50), server_default='running', nullable=False),
        sa.Column('test_summary', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('security_verdict', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('logs', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['request_id'], ['development_requests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['capability_version_id'], ['capability_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_development_runs_tenant_id'), 'development_runs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_development_runs_request_id'), 'development_runs', ['request_id'], unique=False)
    op.create_index(op.f('ix_development_runs_capability_version_id'), 'development_runs', ['capability_version_id'], unique=False)
    op.create_index(op.f('ix_development_runs_status'), 'development_runs', ['status'], unique=False)
    op.create_index(op.f('ix_development_runs_created_at'), 'development_runs', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_development_runs_created_at'), table_name='development_runs')
    op.drop_index(op.f('ix_development_runs_status'), table_name='development_runs')
    op.drop_index(op.f('ix_development_runs_capability_version_id'), table_name='development_runs')
    op.drop_index(op.f('ix_development_runs_request_id'), table_name='development_runs')
    op.drop_index(op.f('ix_development_runs_tenant_id'), table_name='development_runs')
    op.drop_table('development_runs')

    op.drop_index(op.f('ix_capability_versions_created_at'), table_name='capability_versions')
    op.drop_index(op.f('ix_capability_versions_approval_id'), table_name='capability_versions')
    op.drop_index(op.f('ix_capability_versions_status'), table_name='capability_versions')
    op.drop_index(op.f('ix_capability_versions_risk_level'), table_name='capability_versions')
    op.drop_index(op.f('ix_capability_versions_slug'), table_name='capability_versions')
    op.drop_index(op.f('ix_capability_versions_request_id'), table_name='capability_versions')
    op.drop_index(op.f('ix_capability_versions_capability_id'), table_name='capability_versions')
    op.drop_index(op.f('ix_capability_versions_tenant_id'), table_name='capability_versions')
    op.drop_table('capability_versions')
