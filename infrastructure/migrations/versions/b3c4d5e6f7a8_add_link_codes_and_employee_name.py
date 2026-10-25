"""add link codes table, employee_name, decided_by, and scrub plaintext connection codes

Revision ID: b3c4d5e6f7a8
Revises: f7a8b9c0d1e2
Create Date: 2026-10-25 22:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add employee_name column to tenants table
    op.add_column(
        'tenants',
        sa.Column('employee_name', sa.String(length=100), nullable=True),
    )

    # 2. Add decided_by column to interview_topics table
    op.add_column(
        'interview_topics',
        sa.Column('decided_by', sa.String(length=50), nullable=True),
    )

    # 3. Create tenant_link_codes table
    op.create_table(
        'tenant_link_codes',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('channel_id', sa.Uuid(), nullable=False),
        sa.Column('code_hash', sa.String(length=128), nullable=False),
        sa.Column('code_prefix', sa.String(length=16), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_used', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('used_by_sender_id', sa.String(length=255), nullable=True),
        sa.Column('attempts_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default=sa.text('5')),
        sa.Column('is_revoked', sa.Boolean(), nullable=False, server_default=sa.text('false')),
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
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index(
        'ix_tenant_link_codes_tenant_id',
        'tenant_link_codes',
        ['tenant_id'],
        unique=False,
    )
    op.create_index(
        'ix_tenant_link_codes_channel_id',
        'tenant_link_codes',
        ['channel_id'],
        unique=False,
    )
    op.create_index(
        'ix_tenant_link_codes_code_hash',
        'tenant_link_codes',
        ['code_hash'],
        unique=False,
    )
    op.create_index(
        'ix_tenant_link_codes_expires_at',
        'tenant_link_codes',
        ['expires_at'],
        unique=False,
    )
    op.create_index(
        'ix_tenant_link_codes_is_used',
        'tenant_link_codes',
        ['is_used'],
        unique=False,
    )

    # 4. Invalidate & remove any legacy plaintext connection_code values from channels.config
    op.execute(
        "UPDATE channels SET config = config - 'connection_code' WHERE config ? 'connection_code'"
    )


def downgrade() -> None:
    op.drop_index('ix_tenant_link_codes_is_used', table_name='tenant_link_codes')
    op.drop_index('ix_tenant_link_codes_expires_at', table_name='tenant_link_codes')
    op.drop_index('ix_tenant_link_codes_code_hash', table_name='tenant_link_codes')
    op.drop_index('ix_tenant_link_codes_channel_id', table_name='tenant_link_codes')
    op.drop_index('ix_tenant_link_codes_tenant_id', table_name='tenant_link_codes')
    op.drop_table('tenant_link_codes')

    op.drop_column('interview_topics', 'decided_by')
    op.drop_column('tenants', 'employee_name')
