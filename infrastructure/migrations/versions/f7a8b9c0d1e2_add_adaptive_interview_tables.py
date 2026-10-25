"""add adaptive interview tables and tenant interview columns for phase 3

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-10-25 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, Sequence[str], None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add interview_required and interview_threshold to tenants table
    op.add_column(
        'tenants',
        sa.Column(
            'interview_required',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
        ),
    )
    op.add_column(
        'tenants',
        sa.Column(
            'interview_threshold',
            sa.Float(),
            nullable=False,
            server_default=sa.text('80.0'),
        ),
    )

    # 2. Create interview_topics table
    op.create_table(
        'interview_topics',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('slug', sa.String(length=255), nullable=False),
        sa.Column('label', sa.String(length=500), nullable=False),
        sa.Column('why_it_matters', sa.Text(), nullable=True),
        sa.Column('criticality', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column(
            'depends_on',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='unknown'),
        sa.Column('coverage', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('source_message_id', sa.Uuid(), nullable=True),
        sa.Column('group_name', sa.String(length=100), nullable=True, server_default='universal'),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_message_id'], ['messages.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'slug', name='uq_interview_topics_tenant_slug'),
    )

    op.create_index('ix_interview_topics_tenant_id', 'interview_topics', ['tenant_id'], unique=False)
    op.create_index('ix_interview_topics_tenant_status', 'interview_topics', ['tenant_id', 'status'], unique=False)
    op.create_index('ix_interview_topics_tenant_criticality', 'interview_topics', ['tenant_id', 'criticality'], unique=False)

    # 3. Create interview_states table
    op.create_table(
        'interview_states',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('stage', sa.String(length=50), nullable=False, server_default='classification_1'),
        sa.Column(
            'classification_answers',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column('current_topic_slug', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('last_off_topic_reply', sa.Text(), nullable=True),
        sa.Column(
            'last_interaction_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', name='uq_interview_states_tenant_id'),
    )

    op.create_index('ix_interview_states_tenant_id', 'interview_states', ['tenant_id'], unique=False)


def downgrade() -> None:
    # 1. Drop interview_states
    op.drop_index('ix_interview_states_tenant_id', table_name='interview_states')
    op.drop_table('interview_states')

    # 2. Drop interview_topics
    op.drop_index('ix_interview_topics_tenant_criticality', table_name='interview_topics')
    op.drop_index('ix_interview_topics_tenant_status', table_name='interview_topics')
    op.drop_index('ix_interview_topics_tenant_id', table_name='interview_topics')
    op.drop_table('interview_topics')

    # 3. Drop tenants columns
    op.drop_column('tenants', 'interview_threshold')
    op.drop_column('tenants', 'interview_required')
