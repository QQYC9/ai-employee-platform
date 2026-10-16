import uuid
import pytest
from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.auth.jwt_service import create_access_token
from packages.core.database import SessionLocal
from packages.models.domain import Channel, Conversation, Customer, Message, User
from packages.models.tenant import Tenant
from packages.services.audit_service import AuditService
from packages.services.channel_service import ChannelService
from packages.services.conversation_service import ConversationService
from packages.services.customer_service import CustomerService

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


@pytest.fixture
def tenant(db):
    t = Tenant(
        name="Phase 10 Tenant A",
        slug=f"p10-tenant-a-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def tenant_b(db):
    t = Tenant(
        name="Phase 10 Tenant B",
        slug=f"p10-tenant-b-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(t)
    db.flush()
    return t


@pytest.fixture
def owner_user(db, tenant):
    u = User(
        tenant_id=tenant.id,
        name="Phase 10 Owner",
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_owner",
        status="active",
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def member_user(db, tenant):
    u = User(
        tenant_id=tenant.id,
        name="Phase 10 Member",
        email=f"member-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_member",
        status="active",
    )
    db.add(u)
    db.flush()
    return u


# ---------------------------------------------------------------------------
# 1. CustomerService Tests
# ---------------------------------------------------------------------------

def test_create_customer_success(db, tenant):
    """Customer is created with valid fields and audit event is recorded."""
    service = CustomerService(db)
    customer = service.create_customer(
        tenant_id=tenant.id,
        name="Sarah Connor",
        email="sarah@skynet-defense.com",
        phone="+1234567890",
        customer_type="business",
        profile={"company": "Cyberdyne", "title": "Security Lead"},
    )

    assert customer.id is not None
    assert customer.name == "Sarah Connor"
    assert customer.email == "sarah@skynet-defense.com"
    assert customer.status == "active"
    assert customer.customer_type == "business"
    assert customer.profile["company"] == "Cyberdyne"

    # Verify audit event
    audit_service = AuditService(db)
    events = audit_service.list_events(tenant.id, event_type="customer_created")
    assert len(events) >= 1
    assert events[0].event_metadata["customer_id"] == str(customer.id)


def test_create_customer_duplicate_email_rejected(db, tenant):
    """Creating two customers with identical emails within the same tenant fails."""
    service = CustomerService(db)
    email = f"duplicate-{uuid.uuid4().hex[:6]}@example.com"
    service.create_customer(tenant_id=tenant.id, name="User One", email=email)

    with pytest.raises(ValueError, match="already exists"):
        service.create_customer(tenant_id=tenant.id, name="User Two", email=email)


def test_customer_search_and_filtering(db, tenant):
    """List customers with search term and status filters."""
    service = CustomerService(db)
    c1 = service.create_customer(tenant_id=tenant.id, name="Alice In Wonderland", email=f"alice-{uuid.uuid4().hex[:6]}@rabbit.com")
    c2 = service.create_customer(tenant_id=tenant.id, name="Bob The Builder", email=f"bob-{uuid.uuid4().hex[:6]}@construction.com")

    # Search for Alice
    results = service.list_customers(tenant.id, search="Wonderland")
    ids = [c.id for c in results]
    assert c1.id in ids
    assert c2.id not in ids

    # Filter by type
    vip = service.create_customer(tenant_id=tenant.id, name="VIP Client", customer_type="vip")
    vip_list = service.list_customers(tenant.id, customer_type="vip")
    assert vip.id in [c.id for c in vip_list]


def test_update_and_soft_delete_customer(db, tenant):
    """Updating fields and soft-deleting customer sets status to deleted and hides from normal lists."""
    service = CustomerService(db)
    customer = service.create_customer(tenant_id=tenant.id, name="Temporary Customer")

    updated = service.update_customer(
        tenant_id=tenant.id,
        customer_id=customer.id,
        name="Updated Name",
        profile={"tier": "gold"},
    )
    assert updated.name == "Updated Name"
    assert updated.profile["tier"] == "gold"

    # Soft delete
    service.delete_customer(tenant.id, customer.id)
    assert service.get_customer(tenant.id, customer.id) is None


# ---------------------------------------------------------------------------
# 2. ChannelService Tests
# ---------------------------------------------------------------------------

def test_register_channel_success(db, tenant):
    """Registering a channel creates the record and logs an audit event."""
    service = ChannelService(db)
    channel = service.register_channel(
        tenant_id=tenant.id,
        name="Primary WhatsApp",
        channel_type="whatsapp",
        provider="twilio",
        config={"phone_number": "+18005550199"},
    )

    assert channel.id is not None
    assert channel.channel_type == "whatsapp"
    assert channel.provider == "twilio"
    assert channel.status == "active"


def test_invalid_channel_type_rejected(db, tenant):
    """Unsupported channel types are rejected."""
    service = ChannelService(db)
    with pytest.raises(ValueError, match="Unsupported channel type"):
        service.register_channel(
            tenant_id=tenant.id,
            name="Carrier Pigeon",
            channel_type="carrier_pigeon",
        )


def test_update_and_delete_channel(db, tenant):
    """Updating channel status and deleting channel works cleanly."""
    service = ChannelService(db)
    channel = service.register_channel(
        tenant_id=tenant.id,
        name="Web Widget",
        channel_type="webchat",
    )

    updated = service.update_channel(
        tenant.id,
        channel.id,
        status="maintenance",
        config={"theme": "dark"},
    )
    assert updated.status == "maintenance"
    assert updated.config["theme"] == "dark"

    service.delete_channel(tenant.id, channel.id)
    assert service.get_channel(tenant.id, channel.id) is None


# ---------------------------------------------------------------------------
# 3. ConversationService Tests
# ---------------------------------------------------------------------------

def test_start_conversation_success(db, tenant):
    """Starting a conversation creates open session and logs audit event."""
    cust_service = CustomerService(db)
    customer = cust_service.create_customer(tenant.id, name="John Doe")

    chan_service = ChannelService(db)
    channel = chan_service.register_channel(tenant.id, name="Web Chat", channel_type="webchat")

    conv_service = ConversationService(db)
    conversation = conv_service.start_conversation(
        tenant_id=tenant.id,
        customer_id=customer.id,
        channel_id=channel.id,
        subject="Billing Question",
    )

    assert conversation.id is not None
    assert conversation.status == "open"
    assert conversation.subject == "Billing Question"
    assert conversation.started_at is not None


def test_blocked_customer_cannot_start_conversation(db, tenant):
    """Blocked customer is rejected from starting new conversations."""
    cust_service = CustomerService(db)
    customer = cust_service.create_customer(tenant.id, name="Spammer")
    cust_service.update_customer(tenant.id, customer.id, status="blocked")

    conv_service = ConversationService(db)
    with pytest.raises(ValueError, match="blocked"):
        conv_service.start_conversation(
            tenant_id=tenant.id,
            customer_id=customer.id,
            subject="Spam message",
        )


def test_send_messages_chronological_order(db, tenant):
    """Messages from customer, agent, and system are stored and returned in order."""
    cust_service = CustomerService(db)
    customer = cust_service.create_customer(tenant.id, name="Jane Roe")

    conv_service = ConversationService(db)
    conv = conv_service.start_conversation(tenant.id, customer_id=customer.id)

    # 1. Customer asks question
    m1 = conv_service.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="How do I reset my password?",
    )

    # 2. Agent answers
    m2 = conv_service.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="agent",
        content="You can reset your password under Settings > Security.",
    )

    # 3. Customer confirms
    m3 = conv_service.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="Thank you, that worked!",
    )

    messages = conv_service.list_messages(tenant.id, conv.id)
    assert len(messages) == 3
    assert [m.id for m in messages] == [m1.id, m2.id, m3.id]
    assert messages[0].sender_type == "customer"
    assert messages[1].sender_type == "agent"
    assert messages[2].sender_type == "customer"

    # Verify last_message_at was updated on conversation
    db.refresh(conv)
    assert conv.last_message_at is not None


def test_customer_message_reopens_closed_conversation(db, tenant):
    """Sending a customer message to a closed conversation automatically reopens it."""
    conv_service = ConversationService(db)
    conv = conv_service.start_conversation(tenant.id, subject="Reopen Test")

    # Close conversation
    conv_service.update_status(tenant.id, conv.id, "closed")
    db.refresh(conv)
    assert conv.status == "closed"
    assert conv.closed_at is not None

    # Customer sends follow-up
    conv_service.send_message(
        tenant_id=tenant.id,
        conversation_id=conv.id,
        sender_type="customer",
        content="Wait, one more question!",
    )
    db.refresh(conv)
    assert conv.status == "open"
    assert conv.closed_at is None


# ---------------------------------------------------------------------------
# 4. Multi-Tenant Isolation Tests
# ---------------------------------------------------------------------------

def test_tenant_isolation_customers_and_conversations(db, tenant, tenant_b):
    """Tenant B cannot view, modify, or send messages to Tenant A's customer or conversation."""
    cust_service = CustomerService(db)
    cust_a = cust_service.create_customer(tenant.id, name="Customer A", email="cust_a@example.com")

    conv_service = ConversationService(db)
    conv_a = conv_service.start_conversation(tenant.id, customer_id=cust_a.id)

    # Tenant B attempts access to Tenant A's customer
    assert cust_service.get_customer(tenant_b.id, cust_a.id) is None
    with pytest.raises(ValueError, match="not found"):
        cust_service.update_customer(tenant_b.id, cust_a.id, name="Hacked")

    # Tenant B attempts access to Tenant A's conversation
    assert conv_service.get_conversation(tenant_b.id, conv_a.id) is None
    with pytest.raises(ValueError, match="not found"):
        conv_service.send_message(
            tenant_id=tenant_b.id,
            conversation_id=conv_a.id,
            sender_type="user",
            content="Intruder message",
        )


@pytest.fixture
def api_setup():
    db = SessionLocal()
    tenant = Tenant(
        name="API P10 Tenant",
        slug=f"api-p10-{uuid.uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant)
    db.flush()

    owner = User(
        tenant_id=tenant.id,
        name="API Owner",
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_owner",
        status="active",
    )
    db.add(owner)

    member = User(
        tenant_id=tenant.id,
        name="API Member",
        email=f"member-{uuid.uuid4().hex[:8]}@example.com",
        role="tenant_member",
        status="active",
    )
    db.add(member)
    db.commit()

    tenant_id = tenant.id
    owner_id = owner.id
    member_id = member.id
    db.close()

    yield {
        "tenant_id": tenant_id,
        "owner_id": owner_id,
        "member_id": member_id,
    }

    cleanup_db = SessionLocal()
    t = cleanup_db.get(Tenant, tenant_id)
    if t:
        cleanup_db.delete(t)
        cleanup_db.commit()
    cleanup_db.close()


# ---------------------------------------------------------------------------
# 5. REST API Integration Tests
# ---------------------------------------------------------------------------

def test_api_customer_lifecycle(api_setup):
    """Full HTTP API lifecycle for customer: POST, GET, PATCH, DELETE."""
    tenant_id = api_setup["tenant_id"]
    member_id = api_setup["member_id"]
    owner_id = api_setup["owner_id"]

    token = create_access_token(user_id=member_id, tenant_id=tenant_id, role="tenant_member")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create
    email = f"api-cust-{uuid.uuid4().hex[:6]}@example.com"
    resp = client.post(
        "/api/v1/customers",
        headers=headers,
        json={
            "name": "API Customer",
            "email": email,
            "phone": "+966501234567",
            "customer_type": "vip",
            "profile": {"company": "Acme Saudi"},
        },
    )
    assert resp.status_code == 201
    cust_data = resp.json()
    cust_id = cust_data["id"]
    assert cust_data["name"] == "API Customer"
    assert cust_data["customer_type"] == "vip"

    # 2. Get
    get_resp = client.get(f"/api/v1/customers/{cust_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["email"] == email

    # 3. Patch
    patch_resp = client.patch(
        f"/api/v1/customers/{cust_id}",
        headers=headers,
        json={"name": "API Customer Renamed"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "API Customer Renamed"

    # 4. Member cannot delete (403)
    del_forbidden = client.delete(f"/api/v1/customers/{cust_id}", headers=headers)
    assert del_forbidden.status_code == 403

    # 5. Owner can delete (200)
    owner_token = create_access_token(user_id=owner_id, tenant_id=tenant_id, role="tenant_owner")
    del_ok = client.delete(f"/api/v1/customers/{cust_id}", headers={"Authorization": f"Bearer {owner_token}"})
    assert del_ok.status_code == 200


def test_api_channel_rbac_and_lifecycle(api_setup):
    """Channel registration and updating requires Admin/Owner; Member can list."""
    tenant_id = api_setup["tenant_id"]
    member_id = api_setup["member_id"]
    owner_id = api_setup["owner_id"]

    owner_token = create_access_token(user_id=owner_id, tenant_id=tenant_id, role="tenant_owner")
    member_token = create_access_token(user_id=member_id, tenant_id=tenant_id, role="tenant_member")

    # 1. Member cannot register channel (403)
    resp_forbidden = client.post(
        "/api/v1/channels",
        headers={"Authorization": f"Bearer {member_token}"},
        json={"name": "Forbidden Channel", "channel_type": "slack"},
    )
    assert resp_forbidden.status_code == 403

    # 2. Owner registers channel (201)
    resp_ok = client.post(
        "/api/v1/channels",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "Support Slack", "channel_type": "slack", "provider": "slack_app"},
    )
    assert resp_ok.status_code == 201
    channel_id = resp_ok.json()["id"]

    # 3. Member can list channels (200)
    list_resp = client.get("/api/v1/channels", headers={"Authorization": f"Bearer {member_token}"})
    assert list_resp.status_code == 200
    assert any(c["id"] == channel_id for c in list_resp.json())


def test_api_conversation_and_messaging_flow(api_setup):
    """Start conversation, send messages, and fetch message history via REST API."""
    tenant_id = api_setup["tenant_id"]
    member_id = api_setup["member_id"]

    token = create_access_token(user_id=member_id, tenant_id=tenant_id, role="tenant_member")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Start conversation
    conv_resp = client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"subject": "Inquiry about enterprise pricing"},
    )
    assert conv_resp.status_code == 201
    conv_id = conv_resp.json()["id"]

    # 2. Post customer message
    msg_resp1 = client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
        json={
            "sender_type": "customer",
            "content": "Hello, do you offer volume discounts?",
        },
    )
    assert msg_resp1.status_code == 201
    assert msg_resp1.json()["content"] == "Hello, do you offer volume discounts?"

    # 3. Post agent response message
    msg_resp2 = client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=headers,
        json={
            "sender_type": "agent",
            "content": "Yes, we offer custom tiers for over 50 digital workers.",
        },
    )
    assert msg_resp2.status_code == 201

    # 4. List messages
    msgs_resp = client.get(f"/api/v1/conversations/{conv_id}/messages", headers=headers)
    assert msgs_resp.status_code == 200
    data = msgs_resp.json()
    assert len(data) == 2
    assert data[0]["sender_type"] == "customer"
    assert data[1]["sender_type"] == "agent"

    # 5. Resolve conversation
    res_resp = client.patch(
        f"/api/v1/conversations/{conv_id}/status",
        headers=headers,
        json={"status": "resolved"},
    )
    assert res_resp.status_code == 200
    assert res_resp.json()["status"] == "resolved"
    assert res_resp.json()["closed_at"] is not None

