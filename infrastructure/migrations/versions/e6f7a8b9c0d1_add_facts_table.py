"""add facts table for phase 2 facts store

Revision ID: e6f7a8b9c0d1
Revises: c4d5e6f7a8b9
Create Date: 2026-10-25 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create facts table
    op.create_table(
        'facts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('topic', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column(
            'value',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='owner_stated'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('visibility', sa.String(length=50), nullable=False, server_default='public'),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='confirmed'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('superseded_by', sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(['superseded_by'], ['facts.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )

    # 2. Indexes for tenant-isolated queries
    op.create_index('ix_facts_tenant_topic', 'facts', ['tenant_id', 'topic'], unique=False)
    op.create_index('ix_facts_tenant_status', 'facts', ['tenant_id', 'status'], unique=False)
    op.create_index('ix_facts_tenant_subject', 'facts', ['tenant_id', 'subject'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_facts_tenant_subject', table_name='facts')
    op.drop_index('ix_facts_tenant_status', table_name='facts')
    op.drop_index('ix_facts_tenant_topic', table_name='facts')
    op.drop_table('facts')
