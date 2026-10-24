from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.agent.main import app
from packages.auth.jwt_service import create_access_token
from packages.auth.rate_limiter import rate_limiter
from packages.auth.security import hash_password
from packages.core.config import settings
from packages.core.database import SessionLocal
from packages.models.domain import (
    Agent,
    Approval,
    AuditEvent,
    Channel,
    Conversation,
    Customer,
    Message,
    Task,
    User,
)
from packages.models.tenant import Tenant
from packages.services.audit_service import AuditService


@pytest.fixture(autouse=True)
def setup_test_env():
    """Ensure clean rate limiter and test environment settings."""
    rate_limiter.reset()
    orig_env = settings.environment
    orig_allow = settings.allow_dev_auth_header
    settings.environment = "development"
    settings.allow_dev_auth_header = True
    yield
    rate_limiter.reset()
    settings.environment = orig_env
    settings.allow_dev_auth_header = orig_allow


def create_test_tenant(name: str = "Test Tenant", status: str = "active") -> Tenant:
    db = SessionLocal()
    tenant = Tenant(
        id=uuid4(),
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        status=status,
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    tenant_id = tenant.id
    db.close()
    tenant.id = tenant_id
    return tenant


def create_test_user(
    role: str = "tenant_user",
    tenant_id=None,
    name: str = "Test User",
) -> tuple[User, str]:
    db = SessionLocal()
    user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        email=f"user-{uuid4().hex[:8]}@example.com",
        role=role,
        status="active",
        password_hash=hash_password("SecurePass123!"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    u_role = user.role
    u_tid = user.tenant_id
    db.close()

    user.id = user_id
    user.role = u_role
    user.tenant_id = u_tid
    token = create_access_token(user_id, u_tid, u_role)
    return user, token


# =============================================================================
# 1. Authentication & Tenant Isolation on New Endpoints
# =============================================================================

def test_unauthenticated_requests_fail_401():
    client = TestClient(app)
    fake_id = uuid4()

    # Conversation list
    r1 = client.get(f"/api/v1/admin/platform/tenants/{fake_id}/conversations")
    assert r1.status_code == 401

    # Messages read
    r2 = client.get(f"/api/v1/admin/platform/tenants/{fake_id}/conversations/{fake_id}/messages")
    assert r2.status_code == 401

    # Emergency channel
    r3 = client.patch(
        f"/api/v1/admin/platform/tenants/{fake_id}/channels/{fake_id}/status",
        json={"status": "disabled", "reason": "Emergency security quarantine"},
    )
    assert r3.status_code == 401

    # Emergency agent
    r4 = client.patch(
        f"/api/v1/admin/platform/tenants/{fake_id}/agents/{fake_id}/status",
        json={"status": "disabled", "reason": "Emergency security quarantine"},
    )
    assert r4.status_code == 401

    # Emergency task cancel
    r5 = client.post(
        f"/api/v1/admin/platform/tenants/{fake_id}/tasks/{fake_id}/emergency-cancel",
        json={"reason": "Emergency runaway task abort"},
    )
    assert r5.status_code == 401


def test_tenant_user_cannot_access_platform_admin_endpoints():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant User Alpha")
    tenant_id = tenant.id
    _, token = create_test_user(role="tenant_user", tenant_id=tenant_id)

    r = client.get(
        f"/api/v1/admin/platform/tenants/{tenant_id}/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert "lacks required permissions" in r.json()["detail"]


# =============================================================================
# 2. Audited Conversation & Message Reading with Pre-Fetch Audit Locking
# =============================================================================

def test_platform_admin_reads_messages_with_pre_fetch_audit():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Read Audit")
    tenant_id = tenant.id
    _, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    conv_id = uuid4()
    db = SessionLocal()
    conv = Conversation(
        id=conv_id,
        tenant_id=tenant_id,
        status="open",
        subject="Order inquiry",
    )
    db.add(conv)
    db.flush()

    now = datetime.now(timezone.utc)
    msg1 = Message(
        id=uuid4(),
        tenant_id=tenant_id,
        conversation_id=conv_id,
        sender_type="customer",
        content="كم سعر المنتج؟",
        created_at=now,
    )
    msg2 = Message(
        id=uuid4(),
        tenant_id=tenant_id,
        conversation_id=conv_id,
        sender_type="agent",
        content="سعر المنتج 150 ريال",
        created_at=now + timedelta(seconds=1),
    )
    db.add_all([msg1, msg2])
    db.commit()
    db.close()

    resp = client.get(
        f"/api/v1/admin/platform/tenants/{tenant_id}/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) == 2
    assert messages[0]["content"] == "كم سعر المنتج؟"

    # Verify audit event in DB
    db = SessionLocal()
    audit = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.event_type == "admin.conversation_messages.read",
        )
        .order_by(AuditEvent.created_at.desc())
    )
    assert audit is not None
    assert audit.action == "access_requested"
    assert audit.event_metadata["status"] == "disclosed"
    assert audit.event_metadata["disclosed_count"] == 2
    assert "resource_id" in audit.event_metadata
    db.close()


def test_read_audit_failure_prevents_message_disclosure_zero_leakage():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Audit Fail")
    tenant_id = tenant.id
    _, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    conv_id = uuid4()
    db = SessionLocal()
    conv = Conversation(
        id=conv_id,
        tenant_id=tenant_id,
        status="open",
    )
    db.add(conv)
    db.flush()

    msg = Message(
        id=uuid4(),
        tenant_id=tenant_id,
        conversation_id=conv_id,
        sender_type="customer",
        content="SUPER_CONFIDENTIAL_CUSTOMER_SECRET_DATA",
    )
    db.add(msg)
    db.commit()
    db.close()

    # Simulate database audit recording failure in independent session
    with patch.object(AuditService, "record_access_event", side_effect=RuntimeError("DB Disk Full")):
        resp = client.get(
            f"/api/v1/admin/platform/tenants/{tenant_id}/conversations/{conv_id}/messages",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 500
        # Strict zero-leakage check: confidential content must never be in response body!
        assert "SUPER_CONFIDENTIAL_CUSTOMER_SECRET_DATA" not in resp.text
        assert "Administrative audit logging failed; access denied" in resp.json()["detail"]


def test_audit_sanitizer_prevents_secrets_and_message_content_leakage():
    dirty_metadata = {
        "content": "Secret chat message",
        "raw_message": "Sensitive payload",
        "api_key": "sk-123456789abcdef",
        "password": "supersecretpassword",
        "authorization": "Bearer eyJhbGciOi...",
        "safe_limit": 50,
        "resource_type": "conversation_messages",
        "nested": {
            "token": "ghp_secrettoken",
            "safe_counter": 10,
        },
    }
    sanitized = AuditService.sanitize_audit_metadata(dirty_metadata)

    # All sensitive keys must be purged
    assert "content" not in sanitized
    assert "raw_message" not in sanitized
    assert "api_key" not in sanitized
    assert "password" not in sanitized
    assert "authorization" not in sanitized
    assert "token" not in sanitized["nested"]

    # Safe keys preserved
    assert sanitized["safe_limit"] == 50
    assert sanitized["resource_type"] == "conversation_messages"
    assert sanitized["nested"]["safe_counter"] == 10


# =============================================================================
# 3. Commercial Approvals Protection vs Platform Admin Override
# =============================================================================

def test_platform_admin_cannot_approve_routine_commercial_approvals():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Approvals Guard")
    tenant_id = tenant.id
    owner, owner_token = create_test_user(role="tenant_owner", tenant_id=tenant_id)
    platform_admin, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    approval_id = uuid4()
    db = SessionLocal()
    approval = Approval(
        id=approval_id,
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="commercial_discount_50_percent",
        description="Customer requested 50% discount",
        status="pending",
    )
    db.add(approval)
    db.commit()
    db.close()

    # Platform admin attempts to approve routine tenant commercial approval -> 403 Forbidden!
    resp = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"reason": "Admin attempting to approve commercial discount"},
    )
    assert resp.status_code == 403
    assert "Platform administrators cannot approve or reject" in resp.json()["detail"]

    # Verify approval status is STILL PENDING!
    db = SessionLocal()
    db_app = db.scalar(select(Approval).where(Approval.id == approval_id))
    assert db_app.status == "pending"
    db.close()


def test_tenant_owner_routine_commercial_approvals_unaffected():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Owner Flow")
    tenant_id = tenant.id
    owner, owner_token = create_test_user(role="tenant_owner", tenant_id=tenant_id)
    owner_id = owner.id

    approval_id = uuid4()
    db = SessionLocal()
    approval = Approval(
        id=approval_id,
        tenant_id=tenant_id,
        requested_for="tenant_owner",
        action="custom_order_fulfillment",
        description="Fulfill order with custom pricing",
        status="pending",
    )
    db.add(approval)
    db.commit()
    db.close()

    # Tenant owner approves via standard endpoint -> 200 OK!
    resp = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"reason": "Approved by verified business owner."},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["decision_by_user_id"] == str(owner_id)

    # Verify in DB
    db = SessionLocal()
    db_app = db.scalar(select(Approval).where(Approval.id == approval_id))
    assert db_app.status == "approved"
    db.close()


# =============================================================================
# 4. Strict Cross-Tenant Isolation for Emergency Infrastructure Interventions
# =============================================================================

def test_cross_tenant_emergency_channel_isolation():
    client = TestClient(app)
    tenant_a = create_test_tenant("Tenant Channel A")
    tenant_b = create_test_tenant("Tenant Channel B")
    tenant_a_id = tenant_a.id
    tenant_b_id = tenant_b.id
    _, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    channel_b_id = uuid4()
    db = SessionLocal()
    channel_b = Channel(
        id=channel_b_id,
        tenant_id=tenant_b_id,
        name="Telegram B",
        channel_type="telegram",
        status="active",
        config={},
    )
    db.add(channel_b)
    db.commit()
    db.close()

    # Attempting to modify Tenant B's channel under Tenant A's route -> 404 Not Found!
    resp = client.patch(
        f"/api/v1/admin/platform/tenants/{tenant_a_id}/channels/{channel_b_id}/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "disabled", "reason": "Emergency quarantine verification"},
    )
    assert resp.status_code == 404
    assert "Channel not found for this tenant" in resp.json()["detail"]


def test_cross_tenant_emergency_agent_isolation():
    client = TestClient(app)
    tenant_a = create_test_tenant("Tenant Agent A")
    tenant_b = create_test_tenant("Tenant Agent B")
    tenant_a_id = tenant_a.id
    tenant_b_id = tenant_b.id
    _, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    agent_b_id = uuid4()
    db = SessionLocal()
    agent_b = Agent(
        id=agent_b_id,
        tenant_id=tenant_b_id,
        name="Sales Agent B",
        status="active",
        system_config={},
    )
    db.add(agent_b)
    db.commit()
    db.close()

    # Attempting to modify Tenant B's agent under Tenant A's route -> 404 Not Found!
    resp = client.patch(
        f"/api/v1/admin/platform/tenants/{tenant_a_id}/agents/{agent_b_id}/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "disabled", "reason": "Emergency quarantine verification"},
    )
    assert resp.status_code == 404
    assert "Agent not found for this tenant" in resp.json()["detail"]


def test_emergency_agent_shutdown_success_and_audited():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Agent Shutdown")
    tenant_id = tenant.id
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)
    admin_id = admin_user.id

    agent_id = uuid4()
    db = SessionLocal()
    agent = Agent(
        id=agent_id,
        tenant_id=tenant_id,
        name="Active Main Agent",
        status="active",
        system_config={},
    )
    db.add(agent)
    db.commit()
    db.close()

    reason = "Detected runaway agent hallucinations in customer chat."
    resp = client.patch(
        f"/api/v1/admin/platform/tenants/{tenant_id}/agents/{agent_id}/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "disabled", "reason": reason},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["new_status"] == "disabled"

    # Verify agent status in DB
    db = SessionLocal()
    db_agent = db.scalar(select(Agent).where(Agent.id == agent_id))
    assert db_agent.status == "disabled"

    # Verify audit event in DB
    audit = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.event_type == "admin.emergency.agent_status",
        )
        .order_by(AuditEvent.created_at.desc())
    )
    assert audit is not None
    assert audit.action == "emergency_agent_status_change"
    assert audit.user_id == admin_id
    assert audit.event_metadata["new_status"] == "disabled"
    assert audit.event_metadata["reason"] == reason
    db.close()


def test_emergency_agent_state_conflict_409():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Agent Conflict")
    tenant_id = tenant.id
    _, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    agent_id = uuid4()
    db = SessionLocal()
    agent = Agent(
        id=agent_id,
        tenant_id=tenant_id,
        name="Already Disabled Agent",
        status="disabled",
        system_config={},
    )
    db.add(agent)
    db.commit()
    db.close()

    # Attempting to disable already disabled agent -> 409 Conflict
    resp = client.patch(
        f"/api/v1/admin/platform/tenants/{tenant_id}/agents/{agent_id}/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "disabled", "reason": "Emergency quarantine duplicate"},
    )
    assert resp.status_code == 409
    assert "Agent is already in status 'disabled'" in resp.json()["detail"]


def test_cross_tenant_emergency_task_isolation():
    client = TestClient(app)
    tenant_a = create_test_tenant("Tenant Task A")
    tenant_b = create_test_tenant("Tenant Task B")
    tenant_a_id = tenant_a.id
    tenant_b_id = tenant_b.id
    _, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    task_b_id = uuid4()
    db = SessionLocal()
    task_b = Task(
        id=task_b_id,
        tenant_id=tenant_b_id,
        title="Looping Task B",
        objective="Analyze logs",
        status="in_progress",
    )
    db.add(task_b)
    db.commit()
    db.close()

    # Attempting to cancel Tenant B's task under Tenant A's route -> 404 Not Found!
    resp = client.post(
        f"/api/v1/admin/platform/tenants/{tenant_a_id}/tasks/{task_b_id}/emergency-cancel",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"reason": "Emergency runaway task abort"},
    )
    assert resp.status_code == 404
    assert "Task not found for this tenant" in resp.json()["detail"]


# =============================================================================
# 5. Invalid State Transition Rejection (409 Conflict)
# =============================================================================

def test_emergency_channel_state_conflict_409():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Channel Conflict")
    tenant_id = tenant.id
    _, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    channel_id = uuid4()
    db = SessionLocal()
    channel = Channel(
        id=channel_id,
        tenant_id=tenant_id,
        name="Already Disabled Channel",
        channel_type="telegram",
        status="disabled",
        config={},
    )
    db.add(channel)
    db.commit()
    db.close()

    # Attempting to disable already disabled channel -> 409 Conflict
    resp = client.patch(
        f"/api/v1/admin/platform/tenants/{tenant_id}/channels/{channel_id}/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "disabled", "reason": "Emergency quarantine duplicate"},
    )
    assert resp.status_code == 409
    assert "Channel is already in status 'disabled'" in resp.json()["detail"]


def test_emergency_task_cancel_terminal_state_conflict_409():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Task Conflict")
    tenant_id = tenant.id
    _, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    task_id = uuid4()
    db = SessionLocal()
    task = Task(
        id=task_id,
        tenant_id=tenant_id,
        title="Completed task",
        objective="Done work",
        status="completed",
    )
    db.add(task)
    db.commit()
    db.close()

    # Attempting to cancel already completed task -> 409 Conflict
    resp = client.post(
        f"/api/v1/admin/platform/tenants/{tenant_id}/tasks/{task_id}/emergency-cancel",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"reason": "Emergency abort attempted on finished task"},
    )
    assert resp.status_code == 409
    assert "Cannot cancel task in terminal status 'completed'" in resp.json()["detail"]


# =============================================================================
# 6. Successful Emergency Shutdown with Atomic Audit Logging
# =============================================================================

def test_emergency_channel_shutdown_success_and_audited():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Channel Shutdown")
    tenant_id = tenant.id
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)
    admin_id = admin_user.id

    channel_id = uuid4()
    db = SessionLocal()
    channel = Channel(
        id=channel_id,
        tenant_id=tenant_id,
        name="Active WhatsApp Support",
        channel_type="whatsapp",
        status="active",
        config={},
    )
    db.add(channel)
    db.commit()
    db.close()

    reason = "Detected rogue webhook flood, disabling channel immediately."
    resp = client.patch(
        f"/api/v1/admin/platform/tenants/{tenant_id}/channels/{channel_id}/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "disabled", "reason": reason},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["new_status"] == "disabled"

    # Verify channel status in DB
    db = SessionLocal()
    db_ch = db.scalar(select(Channel).where(Channel.id == channel_id))
    assert db_ch.status == "disabled"

    # Verify audit event in DB
    audit = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.event_type == "admin.emergency.channel_status",
        )
        .order_by(AuditEvent.created_at.desc())
    )
    assert audit is not None
    assert audit.action == "emergency_channel_status_change"
    assert audit.user_id == admin_id
    assert audit.event_metadata["new_status"] == "disabled"
    assert audit.event_metadata["reason"] == reason
    db.close()


def test_emergency_task_cancel_success_and_audited():
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Task Cancel")
    tenant_id = tenant.id
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    task_id = uuid4()
    db = SessionLocal()
    task = Task(
        id=task_id,
        tenant_id=tenant_id,
        title="Runaway task",
        objective="Looping query",
        status="in_progress",
    )
    db.add(task)
    db.commit()
    db.close()

    reason = "Runaway recursive loop detected in execution step 5."
    resp = client.post(
        f"/api/v1/admin/platform/tenants/{tenant_id}/tasks/{task_id}/emergency-cancel",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"reason": reason},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["new_status"] == "cancelled"

    # Verify in DB
    db = SessionLocal()
    db_task = db.scalar(select(Task).where(Task.id == task_id))
    assert db_task.status == "cancelled"
    assert "Emergency cancellation by platform admin" in db_task.error

    audit = db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.event_type == "admin.emergency.task_cancelled",
        )
        .order_by(AuditEvent.created_at.desc())
    )
    assert audit is not None
    assert audit.event_metadata["new_status"] == "cancelled"
    assert audit.event_metadata["reason"] == reason
    db.close()


# =============================================================================
# 7. Audit Failure Safety & Full Rollback Verification
# =============================================================================

def test_post_fetch_audit_finalization_failure_blocks_messages_zero_leakage():
    """
    Verifies that if updating the audit record to 'disclosed' fails after fetching messages,
    the response MUST NOT disclose any message content and returns 500 error.
    """
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Post-Fetch Audit Fail")
    tenant_id = tenant.id
    _, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    conv_id = uuid4()
    db = SessionLocal()
    conv = Conversation(
        id=conv_id,
        tenant_id=tenant_id,
        status="open",
    )
    db.add(conv)
    db.flush()

    msg = Message(
        id=uuid4(),
        tenant_id=tenant_id,
        conversation_id=conv_id,
        sender_type="customer",
        content="LEAK_SENSITIVE_SECRET_CHAT_TEXT_999",
    )
    db.add(msg)
    db.commit()
    db.close()

    # Allow record_access_event to succeed, but make update_access_event_status fail on status="disclosed"
    orig_update = AuditService.update_access_event_status

    def mock_update(self, event_id, status, extra_metadata=None):
        if status == "disclosed":
            raise RuntimeError("Database connection dropped during post-fetch audit update")
        return orig_update(self, event_id, status, extra_metadata)

    with patch.object(AuditService, "update_access_event_status", side_effect=mock_update, autospec=True):
        resp = client.get(
            f"/api/v1/admin/platform/tenants/{tenant_id}/conversations/{conv_id}/messages",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 500
        # Strict zero-leakage check: message content must NOT be in the response body!
        assert "LEAK_SENSITIVE_SECRET_CHAT_TEXT_999" not in resp.text
        assert "Administrative audit finalization failed; access disclosure blocked" in resp.json()["detail"]


def test_emergency_channel_mutation_audit_failure_causes_rollback():
    """
    Verifies that if audit recording fails during channel status change,
    the transaction is rolled back and the channel status remains untouched in DB.
    """
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Channel Rollback")
    tenant_id = tenant.id
    _, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    channel_id = uuid4()
    db = SessionLocal()
    channel = Channel(
        id=channel_id,
        tenant_id=tenant_id,
        name="Active Channel To Rollback",
        channel_type="telegram",
        status="active",
        config={},
    )
    db.add(channel)
    db.commit()
    db.close()

    with patch.object(AuditService, "record_event", side_effect=RuntimeError("Audit Table Write Failure")):
        with pytest.raises(RuntimeError):
            client.patch(
                f"/api/v1/admin/platform/tenants/{tenant_id}/channels/{channel_id}/status",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"status": "disabled", "reason": "Emergency quarantine should rollback"},
            )

    # Practical verification: query fresh session to prove channel was NOT changed to disabled!
    db = SessionLocal()
    db_ch = db.scalar(select(Channel).where(Channel.id == channel_id))
    assert db_ch.status == "active"
    db.close()


def test_emergency_agent_mutation_audit_failure_causes_rollback():
    """
    Verifies that if audit recording fails during agent status change,
    the transaction is rolled back and the agent status remains untouched in DB.
    """
    client = TestClient(app)
    tenant = create_test_tenant("Tenant Agent Rollback")
    tenant_id = tenant.id
    _, admin_token = create_test_user(role="platform_admin", tenant_id=None)

    agent_id = uuid4()
    db = SessionLocal()
    agent = Agent(
        id=agent_id,
        tenant_id=tenant_id,
        name="Active Agent To Rollback",
        status="active",
        system_config={},
    )
    db.add(agent)
    db.commit()
    db.close()

    with patch.object(AuditService, "record_event", side_effect=RuntimeError("Audit Table Write Failure")):
        with pytest.raises(RuntimeError):
            client.patch(
                f"/api/v1/admin/platform/tenants/{tenant_id}/agents/{agent_id}/status",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"status": "disabled", "reason": "Emergency quarantine should rollback"},
            )

    # Practical verification: query fresh session to prove agent was NOT changed to disabled!
    db = SessionLocal()
    db_agent = db.scalar(select(Agent).where(Agent.id == agent_id))
    assert db_agent.status == "active"
    db.close()

