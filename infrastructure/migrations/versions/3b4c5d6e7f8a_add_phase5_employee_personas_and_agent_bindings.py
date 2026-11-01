"""add_phase5_employee_personas_and_agent_bindings

Revision ID: 3b4c5d6e7f8a
Revises: 2a3b4c5d6e7f
Create Date: 2026-11-01 04:30:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3b4c5d6e7f8a'
down_revision: Union[str, Sequence[str], None] = '2a3b4c5d6e7f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # 1. Create table 'employee_personas'
    # =========================================================================
    op.create_table(
        'employee_personas',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('slug', sa.String(length=50), nullable=False),
        sa.Column('role_type', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('tone_profile', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('system_instructions', sa.Text(), nullable=False),
        sa.Column('permitted_tool_categories', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('escalation_policy', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_system_template', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index(
        op.f('ix_employee_personas_tenant_id'),
        'employee_personas',
        ['tenant_id'],
        unique=False
    )

    # Partial unique index for system templates (tenant_id IS NULL)
    op.create_index(
        'uq_employee_personas_system_slug',
        'employee_personas',
        ['slug'],
        unique=True,
        postgresql_where=sa.text('tenant_id IS NULL')
    )

    # Partial unique index for tenant-scoped personas (tenant_id IS NOT NULL)
    op.create_index(
        'uq_employee_personas_tenant_slug',
        'employee_personas',
        ['tenant_id', 'slug'],
        unique=True,
        postgresql_where=sa.text('tenant_id IS NOT NULL')
    )

    # =========================================================================
    # 2. Upgrade table 'agents'
    # =========================================================================
    op.add_column(
        'agents',
        sa.Column('persona_id', sa.Uuid(), nullable=True),
    )
    op.add_column(
        'agents',
        sa.Column('persona_overrides', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index(
        op.f('ix_agents_persona_id'),
        'agents',
        ['persona_id'],
        unique=False,
    )
    op.create_foreign_key(
        'fk_agents_persona_id_employee_personas',
        'agents',
        'employee_personas',
        ['persona_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # =========================================================================
    # 3. Upgrade table 'channels'
    # =========================================================================
    op.add_column(
        'channels',
        sa.Column('agent_id', sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f('ix_channels_agent_id'),
        'channels',
        ['agent_id'],
        unique=False,
    )
    op.create_foreign_key(
        'fk_channels_agent_id_agents',
        'channels',
        'agents',
        ['agent_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # =========================================================================
    # 4. Upgrade table 'conversations'
    # =========================================================================
    op.add_column(
        'conversations',
        sa.Column('agent_id', sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f('ix_conversations_agent_id'),
        'conversations',
        ['agent_id'],
        unique=False,
    )
    op.create_foreign_key(
        'fk_conversations_agent_id_agents',
        'conversations',
        'agents',
        ['agent_id'],
        ['id'],
        ondelete='SET NULL',
    )

    # =========================================================================
    # 5. Seed Baseline System Persona Templates
    # =========================================================================
    personas_table = sa.table(
        'employee_personas',
        sa.column('id', sa.Uuid),
        sa.column('tenant_id', sa.Uuid),
        sa.column('name', sa.String),
        sa.column('slug', sa.String),
        sa.column('role_type', sa.String),
        sa.column('description', sa.Text),
        sa.column('version', sa.Integer),
        sa.column('tone_profile', postgresql.JSONB),
        sa.column('system_instructions', sa.Text),
        sa.column('permitted_tool_categories', postgresql.JSONB),
        sa.column('escalation_policy', postgresql.JSONB),
        sa.column('is_active', sa.Boolean),
        sa.column('is_system_template', sa.Boolean),
    )

    op.bulk_insert(
        personas_table,
        [
            {
                'id': uuid.UUID('0ff50a05-59da-5f5c-8573-4c94d9d0b74e'),
                'tenant_id': None,
                'name': 'Customer Support Specialist',
                'slug': 'system_customer_support',
                'role_type': 'support',
                'description': 'موظف دعم فني وخدمة عملاء متخصص في الإجابة على استفسارات المنتجات، تتبع الطلبات، وسياسات المتجر.',
                'version': 1,
                'tone_profile': {'dialect': 'saudi_corporate', 'formality': 'high', 'empathy': 'high'},
                'system_instructions': 'أنت موظف خدمة عملاء رسمي ومحترف. تجيب بدقة على أسئلة العملاء وتعتمد فقط على المعلومات المؤكدة لكتالوج المنتجات وسياسات المتجر. لا تقدم وعودًا باسترجاع الأموال أو تعديل الطلبات خارج الصلاحيات.',
                'permitted_tool_categories': ['READ_ONLY_INQUIRY'],
                'escalation_policy': {'auto_escalate_on_frustration': True, 'escalate_to_human_on_request': True, 'escalate_on_refund_request': True},
                'is_active': True,
                'is_system_template': True,
            },
            {
                'id': uuid.UUID('ff35b775-e834-516b-84cb-5eab65be332f'),
                'tenant_id': None,
                'name': 'Sales Consultant',
                'slug': 'system_sales_consultant',
                'role_type': 'sales',
                'description': 'موظف مبيعات واستشارات تجارية يركز على مساعدة العملاء في اختيار المنتجات المناسبة وتجميع بيانات العملاء المحتملين.',
                'version': 1,
                'tone_profile': {'dialect': 'gcc_friendly', 'formality': 'medium', 'empathy': 'high'},
                'system_instructions': 'أنت مستشار مبيعات ودود ومهني. تساعد العملاء في استكشاف كتالوج المنتجات وتوضيح المزايا والأسعار المؤكدة، وتسجيل بيانات التواصل للعملاء المهتمين. لا تعدل أسعار المنتجات.',
                'permitted_tool_categories': ['READ_ONLY_INQUIRY', 'SAFE_WRITE_MUTATION'],
                'escalation_policy': {'auto_escalate_on_frustration': True, 'escalate_to_human_on_request': True, 'escalate_on_contract_change': True},
                'is_active': True,
                'is_system_template': True,
            },
            {
                'id': uuid.UUID('bca24b03-9ebf-5094-8820-7cadd06760b3'),
                'tenant_id': None,
                'name': 'Operations Coordinator',
                'slug': 'system_operations_coordinator',
                'role_type': 'operations',
                'description': 'موظف تنسيق العمليات الداخلية، جدولة المهام، وإصدار مستندات ومسودات الفواتير والملخصات.',
                'version': 1,
                'tone_profile': {'dialect': 'saudi_corporate', 'formality': 'high', 'empathy': 'medium'},
                'system_instructions': 'أنت منسق عمليات منظم ودقيق. تتابع حالة الطلبات وتساعد في إنشاء المهام الداخلية وإصدار ملخصات المستندات الإدارية المعتمدة وفق سياسة المنشأة.',
                'permitted_tool_categories': ['READ_ONLY_INQUIRY', 'SAFE_WRITE_MUTATION'],
                'escalation_policy': {'auto_escalate_on_frustration': True, 'escalate_to_human_on_request': True},
                'is_active': True,
                'is_system_template': True,
            },
        ]
    )


def downgrade() -> None:
    # 4. Revert conversations
    op.drop_constraint('fk_conversations_agent_id_agents', 'conversations', type_='foreignkey')
    op.drop_index(op.f('ix_conversations_agent_id'), table_name='conversations')
    op.drop_column('conversations', 'agent_id')

    # 3. Revert channels
    op.drop_constraint('fk_channels_agent_id_agents', 'channels', type_='foreignkey')
    op.drop_index(op.f('ix_channels_agent_id'), table_name='channels')
    op.drop_column('channels', 'agent_id')

    # 2. Revert agents
    op.drop_constraint('fk_agents_persona_id_employee_personas', 'agents', type_='foreignkey')
    op.drop_index(op.f('ix_agents_persona_id'), table_name='agents')
    op.drop_column('agents', 'persona_overrides')
    op.drop_column('agents', 'persona_id')

    # 1. Revert employee_personas
    op.drop_index('uq_employee_personas_tenant_slug', table_name='employee_personas')
    op.drop_index('uq_employee_personas_system_slug', table_name='employee_personas')
    op.drop_index(op.f('ix_employee_personas_tenant_id'), table_name='employee_personas')
    op.drop_table('employee_personas')
