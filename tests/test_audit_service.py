import uuid

from packages.models.domain import AuditEvent
from packages.models.tenant import Tenant
from packages.services.audit_service import AuditService
from tests.test_action_policy_service import db


def test_record_audit_event(db):
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Audit Test Tenant",
        slug=f"audit-{uuid.uuid4().hex[:8]}",
    )

    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    service = AuditService(db)

    event = service.record_event(
        tenant_id=tenant.id,
        event_type="tool_execution",
        action="run_tool",
        description="Test tool execution",
        event_metadata={
            "tool_slug": "test_tool",
            "status": "executed",
        },
    )

    db.commit()

    assert event.id is not None
    assert event.tenant_id == tenant.id
    assert event.event_type == "tool_execution"
    assert event.action == "run_tool"
    assert event.description == "Test tool execution"
    assert event.event_metadata["tool_slug"] == "test_tool"


def test_list_audit_events_is_tenant_scoped(db):
    tenant_a = Tenant(
        id=uuid.uuid4(),
        name="Audit Tenant A",
        slug=f"audit-a-{uuid.uuid4().hex[:8]}",
    )

    tenant_b = Tenant(
        id=uuid.uuid4(),
        name="Audit Tenant B",
        slug=f"audit-b-{uuid.uuid4().hex[:8]}",
    )

    db.add_all([tenant_a, tenant_b])
    db.commit()

    service = AuditService(db)

    service.record_event(
        tenant_id=tenant_a.id,
        event_type="tool_execution",
        action="run_tool",
    )

    service.record_event(
        tenant_id=tenant_b.id,
        event_type="tool_execution",
        action="run_tool",
    )

    db.commit()

    events = service.list_events(tenant_a.id)

    assert len(events) == 1
    assert events[0].tenant_id == tenant_a.id


def test_list_audit_events_supports_filters(db):
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Audit Filter Tenant",
        slug=f"audit-filter-{uuid.uuid4().hex[:8]}",
    )

    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    service = AuditService(db)

    service.record_event(
        tenant_id=tenant.id,
        event_type="tool_execution",
        action="run_tool",
    )

    service.record_event(
        tenant_id=tenant.id,
        event_type="approval",
        action="approve",
    )

    db.commit()

    events = service.list_events(
        tenant.id,
        event_type="tool_execution",
        action="run_tool",
    )

    assert len(events) == 1
    assert events[0].event_type == "tool_execution"
    assert events[0].action == "run_tool"


def test_record_audit_event_rejects_empty_event_type(db):
    service = AuditService(db)

    try:
        service.record_event(
            event_type="   ",
        )
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "Event type cannot be empty"
