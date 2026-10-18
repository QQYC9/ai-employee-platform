"""add generated_documents table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-18 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'generated_documents',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('document_type', sa.String(length=50), server_default='document', nullable=False),
        sa.Column('format', sa.String(length=20), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('file_path', sa.String(length=1000), nullable=False),
        sa.Column('file_size', sa.Integer(), server_default='0', nullable=False),
        sa.Column('mime_type', sa.String(length=100), server_default='text/plain', nullable=False),
        sa.Column('sha256_hash', sa.String(length=64), nullable=True),
        sa.Column('created_by_agent_id', sa.Uuid(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by_agent_id'], ['agents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_generated_documents_tenant_id'), 'generated_documents', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_generated_documents_document_type'), 'generated_documents', ['document_type'], unique=False)
    op.create_index(op.f('ix_generated_documents_format'), 'generated_documents', ['format'], unique=False)
    op.create_index(op.f('ix_generated_documents_created_by_agent_id'), 'generated_documents', ['created_by_agent_id'], unique=False)
    op.create_index(op.f('ix_generated_documents_created_at'), 'generated_documents', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_generated_documents_created_at'), table_name='generated_documents')
    op.drop_index(op.f('ix_generated_documents_created_by_agent_id'), table_name='generated_documents')
    op.drop_index(op.f('ix_generated_documents_format'), table_name='generated_documents')
    op.drop_index(op.f('ix_generated_documents_document_type'), table_name='generated_documents')
    op.drop_index(op.f('ix_generated_documents_tenant_id'), table_name='generated_documents')
    op.drop_table('generated_documents')
