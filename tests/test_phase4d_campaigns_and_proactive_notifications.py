from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.auth.jwt_service import create_access_token
from packages.connectors.base import OutboundDeliveryResult
from packages.core.database import SessionLocal
from packages.models.domain import (
    Approval,
    Campaign,
    CampaignRecipient,
    Channel,
    Conversation,
    Customer,
    Message,
    OutboxEvent,
    User,
)
from packages.models.tenant import Tenant
from packages.services.campaign_service import (
    ApprovalRequiredError,
    CampaignError,
    CampaignService,
    InvalidStateTransitionError,
)
from packages.services.outbox_worker import OutboxWorker
from packages.services.proactive_notification_service import ProactiveNotificationService

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def clean_outbox(db: Session):
    db.query(OutboxEvent).delete()
    db.commit()
    yield
    db.query(OutboxEvent).delete()
    db.commit()


@pytest.fixture
def tenant(db: Session):
    t = Tenant(
        name=f"Enterprise-{uuid.uuid4().hex[:6]}",
        slug=f"ent-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(t)
    db.flush()

    owner = User(
        tenant_id=t.id,
        name="Owner User",
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture
def owner_token(db: Session, tenant: Tenant):
    user = db.scalar(select(User).where(User.tenant_id == tenant.id))
    return create_access_token(user_id=user.id, tenant_id=tenant.id, role=user.role)


@pytest.fixture
def channel(db: Session, tenant: Tenant):
    ch = Channel(
        tenant_id=tenant.id,
        name="Official WhatsApp",
        channel_type="whatsapp",
        status="active",
        config={
            "phone_number_id": "123456789",
            "access_token": "wa-token",
            "owner_phone": "+966500000000",
        },
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return ch


# ===========================================================================
# 1. Campaign Lifecycle & State Transitions
# ===========================================================================

def test_campaign_lifecycle_and_state_transitions(db: Session, tenant: Tenant, channel: Channel):
    service = CampaignService(db)

    # 1. Create Draft
    campaign = service.create_campaign(
        tenant_id=tenant.id,
        name="Spring Promotion 2026",
        goal="Reactivate inactive customers",
        message_template="Hello {{name}}, check out our spring collection!",
        channel_id=channel.id,
        batch_size=20,
    )
    assert campaign.status == "draft"
    assert campaign.metrics["total_recipients"] == 0

    # 2. Update Draft
    updated = service.update_campaign(
        tenant_id=tenant.id,
        campaign_id=campaign.id,
        name="Spring Grand Sale 2026",
        message_template="Hi {{name}}, enjoy 30% off today!",
    )
    assert updated.name == "Spring Grand Sale 2026"
    assert "30% off" in updated.message_template

    # 3. Schedule Campaign
    future_time = datetime.now(timezone.utc)
    scheduled = service.schedule_campaign(tenant.id, campaign.id, future_time)
    assert scheduled.status == "scheduled"
    assert scheduled.scheduled_at == future_time

    # 4. Start Campaign
    started = service.start_campaign(tenant.id, campaign.id)
    assert started.status == "running"
    assert started.started_at is not None

    # 5. Pause Campaign
    paused = service.pause_campaign(tenant.id, campaign.id)
    assert paused.status == "paused"

    # 6. Resume Campaign
    resumed = service.resume_campaign(tenant.id, campaign.id)
    assert resumed.status == "running"

    # 7. Cancel Campaign
    cancelled = service.cancel_campaign(tenant.id, campaign.id)
    assert cancelled.status == "cancelled"
    assert cancelled.completed_at is not None

    # 8. Illegal Transition from Cancelled
    with pytest.raises(InvalidStateTransitionError):
        service.start_campaign(tenant.id, campaign.id)


# ===========================================================================
# 2. Audience Selection, Consent & Opt-Out Safety
# ===========================================================================

def test_audience_selection_consent_and_opt_out_safety(db: Session, tenant: Tenant, channel: Channel):
    service = CampaignService(db)

    # Eligible Customer
    c1 = Customer(
        tenant_id=tenant.id,
        name="Salim Ali",
        phone="+966511111111",
        status="active",
        metadata_json={"tags": ["vip", "retail"]},
    )
    # Opted-out Customer
    c2 = Customer(
        tenant_id=tenant.id,
        name="Fatima Khalid",
        phone="+966522222222",
        status="active",
        metadata_json={"opted_out": True, "tags": ["vip"]},
    )
    # Missing Phone Customer
    c3 = Customer(
        tenant_id=tenant.id,
        name="Omar Tariq",
        email="omar@example.com",
        phone=None,
        status="active",
        metadata_json={"tags": ["vip"]},
    )
    # Inactive Customer
    c4 = Customer(
        tenant_id=tenant.id,
        name="Zaid Noor",
        phone="+966544444444",
        status="inactive",
        metadata_json={"tags": ["vip"]},
    )
    db.add_all([c1, c2, c3, c4])
    db.commit()

    campaign = service.create_campaign(
        tenant_id=tenant.id,
        name="VIP Outreach",
        message_template="Hello {{name}}!",
        channel_id=channel.id,
        audience_filter={"tags": ["vip"]},
    )

    enrolled_count = service.enroll_audience(tenant.id, campaign.id)
    # c1 is enrolled
    assert enrolled_count == 1

    recipients = service.get_recipients(tenant.id, campaign.id)
    rec_by_customer = {r.customer_id: r for r in recipients}

    assert c1.id in rec_by_customer
    assert rec_by_customer[c1.id].status == "pending"
    assert rec_by_customer[c1.id].recipient_address == "+966511111111"

    # c2 is skipped due to opt-out
    assert c2.id in rec_by_customer
    assert rec_by_customer[c2.id].status == "skipped"
    assert rec_by_customer[c2.id].skip_reason == "opted_out"

    # c3 is skipped due to missing channel address for WhatsApp
    assert c3.id in rec_by_customer
    assert rec_by_customer[c3.id].status == "skipped"
    assert rec_by_customer[c3.id].skip_reason == "missing_channel_address"

    # c4 was inactive and excluded by query filter
    assert c4.id not in rec_by_customer

    # Per-recipient Deduplication: Enrolling again produces 0 new recipients
    re_enrolled = service.enroll_audience(tenant.id, campaign.id)
    assert re_enrolled == 0


# ===========================================================================
# 3. Batch Processing & Transactional Outbox Enqueueing
# ===========================================================================

def test_batch_processing_and_transactional_outbox(db: Session, tenant: Tenant, channel: Channel):
    service = CampaignService(db)

    customer = Customer(
        tenant_id=tenant.id,
        name="Ahmad Mansoor",
        phone="+966555555555",
        status="active",
        profile={"tier": "Gold"},
    )
    db.add(customer)
    db.commit()

    campaign = service.create_campaign(
        tenant_id=tenant.id,
        name="Gold Tier Promo",
        message_template="Dear {{name}}, as a {{tier}} member you get extra rewards!",
        channel_id=channel.id,
    )
    service.start_campaign(tenant.id, campaign.id)

    # Process batch
    enqueued = service.process_campaign_batch(tenant.id, campaign.id, batch_size=10)
    assert enqueued == 1

    # Check recipient status
    recipients = service.get_recipients(tenant.id, campaign.id)
    rec = recipients[0]
    assert rec.status == "enqueued"
    assert rec.rendered_content == "Dear Ahmad Mansoor, as a Gold member you get extra rewards!"
    assert rec.message_id is not None
    assert rec.outbox_event_id is not None

    # Check created Message
    msg = db.scalar(select(Message).where(Message.id == rec.message_id))
    assert msg is not None
    assert msg.sender_type == "agent"
    assert msg.content == rec.rendered_content

    # Check created OutboxEvent
    outbox = db.scalar(select(OutboxEvent).where(OutboxEvent.id == rec.outbox_event_id))
    assert outbox is not None
    assert outbox.event_type == "dispatch_campaign_message"
    assert outbox.payload["recipient_address"] == "+966555555555"
    assert outbox.payload["campaign_id"] == str(campaign.id)

    # Check campaign metrics
    db.refresh(campaign)
    assert campaign.metrics["enqueued_count"] == 1


# ===========================================================================
# 4. Outbox Worker Dispatching & Metrics Accuracy
# ===========================================================================

def test_outbox_worker_campaign_dispatch(db: Session, tenant: Tenant, channel: Channel):
    service = CampaignService(db)

    customer = Customer(
        tenant_id=tenant.id,
        name="Sara Al-Nasser",
        phone="+966566666666",
        status="active",
    )
    db.add(customer)
    db.commit()

    campaign = service.create_campaign(
        tenant_id=tenant.id,
        name="Product Launch",
        message_template="Hello {{name}}, our new feature is live!",
        channel_id=channel.id,
    )
    service.start_campaign(tenant.id, campaign.id)
    service.process_campaign_batch(tenant.id, campaign.id)
    db.commit()

    outbox_event = db.scalar(
        select(OutboxEvent).where(
            OutboxEvent.event_type == "dispatch_campaign_message",
            OutboxEvent.tenant_id == tenant.id,
        )
    )
    assert outbox_event is not None

    # Mock ChannelService message dispatch
    mock_channel_svc = MagicMock()
    mock_channel_svc.send_channel_message.return_value = OutboundDeliveryResult(
        success=True,
        channel_type="whatsapp",
        recipient_id="+966566666666",
        external_message_id="wa-msg-12345",
        status="delivered",
    )

    worker = OutboxWorker(
        tenant_id=tenant.id,
        session_factory=SessionLocal,
        channel_service=mock_channel_svc,
    )

    success = worker.process_event(outbox_event.id)
    assert success is True

    # Check recipient updated to delivered
    recipients = service.get_recipients(tenant.id, campaign.id)
    assert recipients[0].status == "delivered"
    assert recipients[0].delivered_at is not None

    # Check campaign completed and metrics
    db.refresh(campaign)
    assert campaign.status == "completed"
    assert campaign.completed_at is not None
    assert campaign.metrics["delivered_count"] == 1
    assert campaign.metrics["sent_count"] == 1


# ===========================================================================
# 5. Outbox Worker Transient Failure and Backoff
# ===========================================================================

def test_outbox_worker_campaign_failure_and_retry(db: Session, tenant: Tenant, channel: Channel):
    service = CampaignService(db)

    customer = Customer(
        tenant_id=tenant.id,
        name="Khaled Fahad",
        phone="+966577777777",
        status="active",
    )
    db.add(customer)
    db.commit()

    campaign = service.create_campaign(
        tenant_id=tenant.id,
        name="Retry Test Campaign",
        message_template="Hello {{name}}",
        channel_id=channel.id,
    )
    service.start_campaign(tenant.id, campaign.id)
    service.process_campaign_batch(tenant.id, campaign.id)
    db.commit()

    outbox_event = db.scalar(
        select(OutboxEvent).where(
            OutboxEvent.event_type == "dispatch_campaign_message",
            OutboxEvent.tenant_id == tenant.id,
        )
    )

    # Transient network error
    mock_channel_svc = MagicMock()
    mock_channel_svc.send_channel_message.return_value = OutboundDeliveryResult(
        success=False,
        channel_type="whatsapp",
        recipient_id="+966577777777",
        error="Network timeout connecting to WhatsApp gateway",
        status="failed",
    )

    worker = OutboxWorker(
        tenant_id=tenant.id,
        session_factory=SessionLocal,
        channel_service=mock_channel_svc,
    )

    worker.run_once()

    # Event remains failed or retrying with backoff
    db.refresh(outbox_event)
    assert outbox_event.status == "pending"  # Backed off for retry
    assert outbox_event.attempt_count == 1


# ===========================================================================
# 6. Approval Gating
# ===========================================================================

def test_campaign_approval_gating(db: Session, tenant: Tenant, channel: Channel):
    service = CampaignService(db)

    campaign = service.create_campaign(
        tenant_id=tenant.id,
        name="High-Volume Discount Blast",
        message_template="50% off everything!",
        channel_id=channel.id,
        requires_approval=True,
    )

    # Attempting to start without approval raises ApprovalRequiredError
    with pytest.raises(ApprovalRequiredError):
        service.start_campaign(tenant.id, campaign.id)

    # Create pending approval
    approval = Approval(
        tenant_id=tenant.id,
        requested_for="tenant_owner",
        action="launch_campaign",
        description=f"Launch campaign {campaign.name}",
        status="pending",
    )
    db.add(approval)
    db.commit()

    campaign.approval_id = approval.id
    db.commit()

    # Still raises if status is pending
    with pytest.raises(ApprovalRequiredError):
        service.start_campaign(tenant.id, campaign.id)

    # Approve
    approval.status = "approved"
    db.commit()

    # Now starting succeeds
    started = service.start_campaign(tenant.id, campaign.id)
    assert started.status == "running"


# ===========================================================================
# 7. Multi-Tenant Isolation
# ===========================================================================

def test_multi_tenant_isolation(db: Session, tenant: Tenant, channel: Channel):
    # Create second tenant
    tenant_b = Tenant(
        name=f"TenantB-{uuid.uuid4().hex[:6]}",
        slug=f"tenant-b-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(tenant_b)
    db.flush()

    customer_b = Customer(
        tenant_id=tenant_b.id,
        name="Customer of B",
        phone="+966599999999",
        status="active",
    )
    db.add(customer_b)
    db.commit()

    service_a = CampaignService(db)
    camp_a = service_a.create_campaign(
        tenant_id=tenant.id,
        name="Tenant A Campaign",
        message_template="Hello {{name}}",
        channel_id=channel.id,
    )
    service_a.start_campaign(tenant.id, camp_a.id)

    # Verify Customer B was NOT enrolled in Tenant A's campaign
    recipients_a = service_a.get_recipients(tenant.id, camp_a.id)
    assert all(r.customer_id != customer_b.id for r in recipients_a)

    # Verify Tenant B cannot access Tenant A's campaign
    service_b = CampaignService(db)
    camp_b_view = service_b.get_campaign(tenant_b.id, camp_a.id)
    assert camp_b_view is None


# ===========================================================================
# 8. Proactive Customer Notifications & Owner Alert Separation
# ===========================================================================

def test_proactive_notifications_and_owner_alert_separation(db: Session, tenant: Tenant, channel: Channel):
    proactive_svc = ProactiveNotificationService(db)

    customer = Customer(
        tenant_id=tenant.id,
        name="Layla Ibrahim",
        phone="+966588888888",
        status="active",
    )
    db.add(customer)
    db.commit()

    # 1. Appointment Reminder
    rem_res = proactive_svc.send_appointment_reminder(
        tenant_id=tenant.id,
        customer_id=customer.id,
        channel_id=channel.id,
        appointment_time="2026-11-01 10:00 AM",
        service_name="Car Maintenance",
    )
    assert rem_res["status"] == "dispatched"
    outbox_rem = db.scalar(select(OutboxEvent).where(OutboxEvent.id == uuid.UUID(rem_res["outbox_event_id"])))
    assert outbox_rem is not None
    assert "Car Maintenance" in outbox_rem.payload["content"]
    assert outbox_rem.payload["recipient"] == "+966588888888"

    # 2. Service Follow-up
    fol_res = proactive_svc.send_service_followup(
        tenant_id=tenant.id,
        customer_id=customer.id,
        channel_id=channel.id,
        service_name="Dentistry Checkup",
        feedback_url="https://review.example.com",
    )
    assert fol_res["status"] == "dispatched"

    # 3. Inactivity Re-engagement
    reeng_res = proactive_svc.send_inactivity_reengagement(
        tenant_id=tenant.id,
        customer_id=customer.id,
        channel_id=channel.id,
        offer_details="Free shipping on your next order",
    )
    assert reeng_res["status"] == "dispatched"

    # 4. Opt-Out Safety on Proactive
    customer.metadata_json = {"opted_out": True}
    db.commit()

    opt_out_res = proactive_svc.send_appointment_reminder(
        tenant_id=tenant.id,
        customer_id=customer.id,
        channel_id=channel.id,
        appointment_time="2026-11-02",
        service_name="Any Service",
    )
    assert opt_out_res["status"] == "skipped"
    assert opt_out_res["reason"] == "customer_opted_out"

    # 5. Proactive Approval Gating
    customer.metadata_json = {}
    db.commit()

    appr_res = proactive_svc.send_appointment_reminder(
        tenant_id=tenant.id,
        customer_id=customer.id,
        channel_id=channel.id,
        appointment_time="2026-11-02",
        service_name="VIP Consultation",
        requires_approval=True,
    )
    assert appr_res["status"] == "pending_approval"
    assert "approval_id" in appr_res

    # 6. Internal Owner Alert Separation
    owner_alert = proactive_svc.notify_owner_internal(
        tenant_id=tenant.id,
        channel_id=channel.id,
        alert_title="Low Stock Alert",
        alert_body="Inventory for item XYZ is below 5 units",
    )
    assert owner_alert["status"] == "enqueued"
    outbox_alert = db.scalar(select(OutboxEvent).where(OutboxEvent.id == uuid.UUID(owner_alert["outbox_event_id"])))
    assert outbox_alert.event_type == "notify_owner_task_result"
    assert outbox_alert.payload["task_title"] == "Low Stock Alert"


# ===========================================================================
# 9. REST API Integration Endpoints
# ===========================================================================

def test_campaigns_rest_api(db: Session, tenant: Tenant, channel: Channel, owner_token: str):
    headers = {"Authorization": f"Bearer {owner_token}"}

    # Add test customers
    c1 = Customer(tenant_id=tenant.id, name="User One", phone="+966500000010", status="active")
    c2 = Customer(tenant_id=tenant.id, name="User Two", phone="+966500000020", status="active")
    db.add_all([c1, c2])
    db.commit()

    # 1. POST /api/v1/campaigns
    create_resp = client.post(
        "/api/v1/campaigns",
        headers=headers,
        json={
            "name": "API Created Campaign",
            "goal": "Test API endpoints",
            "message_template": "Welcome {{name}} to our platform!",
            "channel_id": str(channel.id),
            "batch_size": 1,
            "rate_limit_per_minute": 50,
        },
    )
    assert create_resp.status_code == 201
    camp_data = create_resp.json()
    camp_id = camp_data["id"]
    assert camp_data["name"] == "API Created Campaign"
    assert camp_data["status"] == "draft"

    # 2. GET /api/v1/campaigns
    list_resp = client.get("/api/v1/campaigns", headers=headers)
    assert list_resp.status_code == 200
    assert any(c["id"] == camp_id for c in list_resp.json()["items"])

    # 3. GET /api/v1/campaigns/{id}
    get_resp = client.get(f"/api/v1/campaigns/{camp_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == camp_id

    # 4. PATCH /api/v1/campaigns/{id}
    patch_resp = client.patch(
        f"/api/v1/campaigns/{camp_id}",
        headers=headers,
        json={"name": "API Updated Campaign Name"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "API Updated Campaign Name"

    # 5. POST /api/v1/campaigns/{id}/start
    start_resp = client.post(f"/api/v1/campaigns/{camp_id}/start", headers=headers)
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "running"

    # 6. POST /api/v1/campaigns/{id}/pause
    pause_resp = client.post(f"/api/v1/campaigns/{camp_id}/pause", headers=headers)
    assert pause_resp.status_code == 200
    assert pause_resp.json()["status"] == "paused"

    # 7. POST /api/v1/campaigns/{id}/resume
    resume_resp = client.post(f"/api/v1/campaigns/{camp_id}/resume", headers=headers)
    assert resume_resp.status_code == 200
    assert resume_resp.json()["status"] == "running"

    # 8. POST /api/v1/campaigns/{id}/cancel
    cancel_resp = client.post(f"/api/v1/campaigns/{camp_id}/cancel", headers=headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    # 9. GET /api/v1/campaigns/{id}/recipients
    rec_resp = client.get(f"/api/v1/campaigns/{camp_id}/recipients", headers=headers)
    assert rec_resp.status_code == 200
    assert "items" in rec_resp.json()

    # 10. POST /api/v1/campaigns/proactive/trigger
    cust = Customer(
        tenant_id=tenant.id,
        name="Test API Customer",
        phone="+966500000001",
        status="active",
    )
    db.add(cust)
    db.commit()

    proact_resp = client.post(
        "/api/v1/campaigns/proactive/trigger",
        headers=headers,
        json={
            "customer_id": str(cust.id),
            "channel_id": str(channel.id),
            "notification_type": "appointment_reminder",
            "appointment_time": "Tomorrow 3 PM",
            "service_name": "Consulting",
        },
    )
    assert proact_resp.status_code == 201
    assert proact_resp.json()["status"] == "dispatched"
