from __future__ import annotations

import uuid
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.models.tenant import Tenant
from packages.models.domain import (
    Agent,
    Channel,
    Conversation,
    EmployeePersona,
)


@pytest.fixture
def test_tenant(test_db_session: Session) -> Tenant:
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Stage 5.1 Test Retail Enterprise",
        slug=f"stage51-retail-{uuid.uuid4().hex[:8]}",
        status="active",
        employee_name="Legacy Fallback Name",
    )
    test_db_session.add(tenant)
    test_db_session.commit()
    test_db_session.refresh(tenant)
    return tenant


class TestStage51SchemaAndModels:
    """
    Micro-Stage 5.1 Verification Test Suite
    Validates:
    1. Schema creation of employee_personas table with all required columns.
    2. Partial unique indexes for system templates (tenant_id IS NULL) and tenant personas (tenant_id IS NOT NULL).
    3. Multi-agent foreign key bindings (Agent.persona_id, Channel.agent_id, Conversation.agent_id).
    4. ON DELETE SET NULL referential actions.
    5. Baseline seeded system persona templates.
    6. Multi-employee concurrent binding per tenant.
    7. Tenant.employee_name deprecation status.
    """

    def test_seeded_system_persona_templates_exist(self, test_db_session: Session) -> None:
        """
        Verifies that the 3 canonical baseline system persona templates are seeded
        and have correct types, categories, and version.
        """
        stmt = select(EmployeePersona).where(EmployeePersona.is_system_template == True).order_by(EmployeePersona.slug)
        templates = test_db_session.scalars(stmt).all()

        slugs = [t.slug for t in templates]
        assert "system_customer_support" in slugs
        assert "system_sales_consultant" in slugs
        assert "system_operations_coordinator" in slugs

        # 1. Customer Support Template
        support = next(t for t in templates if t.slug == "system_customer_support")
        assert support.tenant_id is None
        assert support.role_type == "support"
        assert support.version == 1
        assert support.is_active is True
        assert support.permitted_tool_categories == ["READ_ONLY_INQUIRY"]
        assert support.tone_profile.get("dialect") == "saudi_corporate"
        assert support.escalation_policy.get("auto_escalate_on_frustration") is True

        # 2. Sales Consultant Template
        sales = next(t for t in templates if t.slug == "system_sales_consultant")
        assert sales.tenant_id is None
        assert sales.role_type == "sales"
        assert sales.version == 1
        assert sales.is_active is True
        assert "READ_ONLY_INQUIRY" in sales.permitted_tool_categories
        assert "SAFE_WRITE_MUTATION" in sales.permitted_tool_categories
        assert sales.tone_profile.get("dialect") == "gcc_friendly"

        # 3. Operations Coordinator Template
        ops = next(t for t in templates if t.slug == "system_operations_coordinator")
        assert ops.tenant_id is None
        assert ops.role_type == "operations"
        assert ops.version == 1
        assert ops.is_active is True
        assert "READ_ONLY_INQUIRY" in ops.permitted_tool_categories
        assert "SAFE_WRITE_MUTATION" in ops.permitted_tool_categories

    def test_partial_unique_index_system_slug(self, test_db_session: Session) -> None:
        """
        Verifies that attempting to create duplicate system templates (tenant_id IS NULL)
        with the same slug is blocked by uq_employee_personas_system_slug.
        """
        dup_template = EmployeePersona(
            id=uuid.uuid4(),
            tenant_id=None,
            name="Duplicate Support",
            slug="system_customer_support",  # already exists in seeded templates
            role_type="support",
            version=1,
            tone_profile={},
            system_instructions="test duplicate",
            permitted_tool_categories=[],
            escalation_policy={},
            is_active=True,
            is_system_template=True,
        )
        test_db_session.add(dup_template)
        with pytest.raises(IntegrityError) as exc_info:
            test_db_session.commit()
        test_db_session.rollback()
        assert "uq_employee_personas_system_slug" in str(exc_info.value) or "duplicate key" in str(exc_info.value)

    def test_partial_unique_index_tenant_slug(
        self, test_db_session: Session, test_tenant: Tenant
    ) -> None:
        """
        Verifies that:
        1. Duplicate slugs within the same tenant are blocked.
        2. The same slug can exist across two different tenants.
        3. A tenant can create a persona with a slug identical to a system template.
        """
        # Create tenant custom persona with same slug as system template -> Must SUCCEED
        custom_p1 = EmployeePersona(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            name="Custom Support",
            slug="system_customer_support",
            role_type="support",
            version=1,
            tone_profile={},
            system_instructions="tenant specific instructions",
            permitted_tool_categories=["READ_ONLY_INQUIRY"],
            escalation_policy={},
            is_active=True,
            is_system_template=False,
        )
        test_db_session.add(custom_p1)
        test_db_session.commit()

        # Attempt duplicate slug in the SAME tenant -> Must FAIL
        custom_p1_dup = EmployeePersona(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            name="Custom Support Duplicate",
            slug="system_customer_support",
            role_type="support",
            version=1,
            tone_profile={},
            system_instructions="duplicate instructions",
            permitted_tool_categories=["READ_ONLY_INQUIRY"],
            escalation_policy={},
            is_active=True,
            is_system_template=False,
        )
        test_db_session.add(custom_p1_dup)
        with pytest.raises(IntegrityError) as exc_info:
            test_db_session.commit()
        test_db_session.rollback()
        assert "uq_employee_personas_tenant_slug" in str(exc_info.value) or "duplicate key" in str(exc_info.value)

        # Create second tenant and add same slug -> Must SUCCEED (cross-tenant isolation)
        second_tenant = Tenant(
            id=uuid.uuid4(),
            name="Second Enterprise Tenant",
            slug=f"stage51-tenant2-{uuid.uuid4().hex[:8]}",
            status="active",
        )
        test_db_session.add(second_tenant)
        test_db_session.commit()

        custom_p2 = EmployeePersona(
            id=uuid.uuid4(),
            tenant_id=second_tenant.id,
            name="Second Tenant Support",
            slug="system_customer_support",
            role_type="support",
            version=1,
            tone_profile={},
            system_instructions="second tenant instructions",
            permitted_tool_categories=["READ_ONLY_INQUIRY"],
            escalation_policy={},
            is_active=True,
            is_system_template=False,
        )
        test_db_session.add(custom_p2)
        test_db_session.commit()
        assert custom_p2.id is not None

    def test_agent_persona_binding_and_set_null_on_delete(
        self, test_db_session: Session, test_tenant: Tenant
    ) -> None:
        """
        Verifies that an Agent can be bound to an EmployeePersona,
        and deleting the EmployeePersona sets agent.persona_id to NULL without deleting the Agent.
        """
        # Create a custom persona
        persona = EmployeePersona(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            name="Ephemeral Persona",
            slug=f"ephemeral-{uuid.uuid4().hex[:6]}",
            role_type="support",
            version=1,
            tone_profile={"dialect": "saudi_corporate"},
            system_instructions="test",
            permitted_tool_categories=["READ_ONLY_INQUIRY"],
            escalation_policy={},
            is_active=True,
            is_system_template=False,
        )
        test_db_session.add(persona)
        test_db_session.commit()

        # Create Agent bound to this persona
        agent = Agent(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            name="فهد الدعم",
            agent_type="main",
            status="active",
            persona_id=persona.id,
            persona_overrides={"display_name": "فهد الدعم الفني"},
        )
        test_db_session.add(agent)
        test_db_session.commit()
        test_db_session.refresh(agent)

        assert agent.persona_id == persona.id
        assert agent.persona_overrides == {"display_name": "فهد الدعم الفني"}

        # Delete persona -> Agent must survive with persona_id = NULL
        test_db_session.delete(persona)
        test_db_session.commit()
        test_db_session.refresh(agent)

        assert agent.persona_id is None
        assert agent.name == "فهد الدعم"

    def test_multi_agent_multi_channel_and_conversation_bindings(
        self, test_db_session: Session, test_tenant: Tenant
    ) -> None:
        """
        Verifies multi-employee representation within the same tenant:
        - Employee 1 (Support) bound to Telegram Channel and Conversation 1
        - Employee 2 (Sales) bound to WhatsApp Channel and Conversation 2
        - Deleting Employee 1 sets channel.agent_id and conversation.agent_id to NULL.
        """
        # Query seeded templates
        support_template = test_db_session.scalars(
            select(EmployeePersona).where(
                EmployeePersona.slug == "system_customer_support",
                EmployeePersona.tenant_id.is_(None),
            )
        ).one()
        sales_template = test_db_session.scalars(
            select(EmployeePersona).where(
                EmployeePersona.slug == "system_sales_consultant",
                EmployeePersona.tenant_id.is_(None),
            )
        ).one()

        # Employee 1: Support
        emp_support = Agent(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            name="موظف الدعم فهد",
            status="active",
            persona_id=support_template.id,
            persona_overrides={"display_name": "فهد - خدمة العملاء"},
        )
        # Employee 2: Sales
        emp_sales = Agent(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            name="موظفة المبيعات سارة",
            status="active",
            persona_id=sales_template.id,
            persona_overrides={"display_name": "سارة - المبيعات"},
        )
        test_db_session.add_all([emp_support, emp_sales])
        test_db_session.commit()

        # Channel 1: Telegram bound to Employee 1
        tg_channel = Channel(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            name="قناة تيليجرام للدعم",
            channel_type="telegram",
            provider="telegram",
            status="active",
            agent_id=emp_support.id,
            config={"bot_token": "mock-token"},
        )
        # Channel 2: WhatsApp bound to Employee 2
        wa_channel = Channel(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            name="قناة واتساب للمبيعات",
            channel_type="whatsapp",
            provider="whatsapp_cloud",
            status="active",
            agent_id=emp_sales.id,
            config={"phone_number_id": "12345"},
        )
        test_db_session.add_all([tg_channel, wa_channel])
        test_db_session.commit()

        # Conversation 1: Handled by Employee 1 on Telegram
        conv_support = Conversation(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            channel_id=tg_channel.id,
            agent_id=emp_support.id,
            status="open",
            subject="استفسار عن الشحن",
        )
        # Conversation 2: Handled by Employee 2 on WhatsApp
        conv_sales = Conversation(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            channel_id=wa_channel.id,
            agent_id=emp_sales.id,
            status="open",
            subject="طلب عرض أسعار",
        )
        test_db_session.add_all([conv_support, conv_sales])
        test_db_session.commit()

        # Refresh and verify bindings
        test_db_session.refresh(tg_channel)
        test_db_session.refresh(wa_channel)
        test_db_session.refresh(conv_support)
        test_db_session.refresh(conv_sales)

        assert tg_channel.agent_id == emp_support.id
        assert wa_channel.agent_id == emp_sales.id
        assert conv_support.agent_id == emp_support.id
        assert conv_sales.agent_id == emp_sales.id

        # ON DELETE SET NULL test: Delete Employee 1
        test_db_session.delete(emp_support)
        test_db_session.commit()

        test_db_session.refresh(tg_channel)
        test_db_session.refresh(conv_support)
        test_db_session.refresh(wa_channel)
        test_db_session.refresh(conv_sales)

        # Telegram channel & conversation survive with agent_id = NULL
        assert tg_channel.agent_id is None
        assert conv_support.agent_id is None

        # Employee 2 (Sales) and WhatsApp channel/conversation remain intact
        assert wa_channel.agent_id == emp_sales.id
        assert conv_sales.agent_id == emp_sales.id

    def test_tenant_employee_name_deprecation_documented(self) -> None:
        """
        Verifies that Tenant.employee_name is formally documented as deprecated
        in packages/models/tenant.py.
        """
        import inspect
        from packages.models import tenant as tenant_module

        source = inspect.getsource(tenant_module)
        assert "DEPRECATED (Phase 5 Stage 5.1)" in source
        assert "agents.name is the authoritative source" in source
