import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.auth.context import get_tenant_context
from packages.auth.dependencies import get_current_user, get_db
from packages.core.database import SessionLocal
from packages.models.domain import (
    ActionPolicy,
    Approval,
    AuditEvent,
    Channel,
    Conversation,
    Customer,
    GeneratedDocument,
    Message,
    OutboxEvent,
    Permission,
    Task,
    User,
)
from packages.models.tenant import Tenant
from packages.services.approval_service import ApprovalService
from packages.services.channel_service import ChannelService
from packages.services.conversational_agent_engine import ConversationalAgentEngine
from packages.tools.contract import ToolExecutionContext
from packages.tools.document_tool import DocumentGeneratorTool


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def test_tenant(db_session: Session):
    tenant = Tenant(
        name=f"Integration Tenant {uuid.uuid4().hex[:6]}",
        slug=f"integ-tenant-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


@pytest.fixture
def test_user(db_session: Session, test_tenant: Tenant):
    user = User(
        tenant_id=test_tenant.id,
        email=f"user-{uuid.uuid4().hex[:6]}@example.com",
        name="Lead Engineer",
        role="tenant_admin",
        password_hash="fake-hash",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def client(db_session: Session, test_user: User):
    def override_get_db():
        yield db_session

    def override_get_current_user():
        return test_user

    def override_get_tenant_context():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_tenant_context] = override_get_tenant_context

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


# ==============================================================================
# Conversational Agent Real Tool Execution Tests
# ==============================================================================

class TestConversationalAgentToolIntegration:
    def test_conversational_agent_executes_customer_search_tool(
        self, db_session: Session, test_tenant: Tenant
    ):
        # Create a customer
        cust = Customer(
            tenant_id=test_tenant.id,
            name="Zaid Al-Harbi",
            phone="+966555555555",
            email="zaid@example.com",
            status="active",
        )
        db_session.add(cust)

        # Grant execute permission
        perm = Permission(
            tenant_id=test_tenant.id,
            action="execute:customer_search",
            resource="tools:customer_search",
            effect="allow",
        )
        db_session.add(perm)
        db_session.commit()

        engine = ConversationalAgentEngine(db_session)
        result = engine.execute_tool_action(
            tenant_id=test_tenant.id,
            tool_slug="customer_search",
            parameters={"query": "Zaid"},
        )

        assert result.status == "executed"
        assert result.decision == "ALLOW"
        assert len(result.output) == 1
        assert result.output[0]["name"] == "Zaid Al-Harbi"

    def test_conversational_agent_enforces_approval_policy(
        self, db_session: Session, test_tenant: Tenant
    ):
        # Grant permission
        perm = Permission(
            tenant_id=test_tenant.id,
            action="execute:generate_document",
            resource="tools:generate_document",
            effect="allow",
        )
        db_session.add(perm)

        # Configure ActionPolicy requiring human approval
        policy = ActionPolicy(
            tenant_id=test_tenant.id,
            action="execute:generate_document",
            resource="tools:generate_document",
            requires_approval=True,
        )
        db_session.add(policy)
        db_session.commit()

        engine = ConversationalAgentEngine(db_session)

        # Attempt execution before approval
        result = engine.execute_tool_action(
            tenant_id=test_tenant.id,
            tool_slug="generate_document",
            parameters={
                "title": "Sensitive Financial Document",
                "content": "Secret numbers",
                "format": "txt",
            },
        )

        # Must be blocked by DecisionEngine
        assert result.status == "blocked"
        assert result.decision == "APPROVAL_REQUIRED"

        # Verify audit event was logged
        audit = db_session.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == test_tenant.id,
                AuditEvent.event_type == "tool_execution_blocked",
            )
        )
        assert audit is not None
        assert audit.action == "execute:generate_document"

    def test_conversational_agent_blocks_when_permission_missing(
        self, db_session: Session, test_tenant: Tenant
    ):
        engine = ConversationalAgentEngine(db_session)
        # Attempt to execute task_create with NO permission granted in database
        result = engine.execute_tool_action(
            tenant_id=test_tenant.id,
            tool_slug="task_create",
            parameters={"title": "Unauthorized Task", "objective": "Should be denied"},
        )

        # DecisionEngine must deny execution
        assert result.status == "blocked"
        assert result.decision == "DENY"

    def test_tool_idempotency_prevents_duplicate_side_effect(
        self, db_session: Session, test_tenant: Tenant
    ):
        perm = Permission(
            tenant_id=test_tenant.id,
            action="execute:task_create",
            resource="tools:task_create",
            effect="allow",
        )
        db_session.add(perm)
        db_session.commit()


        engine = ConversationalAgentEngine(db_session)
        idem_key = f"idem-task-{uuid.uuid4().hex[:8]}"

        # First execution
        res1 = engine.execute_tool_action(
            tenant_id=test_tenant.id,
            tool_slug="task_create",
            parameters={"title": "Idempotent Task Creation", "objective": "Run once only"},
            idempotency_key=idem_key,
        )
        assert res1.status == "executed"
        task_id = res1.output["task_id"]

        # Second execution with identical idempotency key
        res2 = engine.execute_tool_action(
            tenant_id=test_tenant.id,
            tool_slug="task_create",
            parameters={"title": "Idempotent Task Creation", "objective": "Run once only"},
            idempotency_key=idem_key,
        )
        assert res2.status == "executed"
        # Must return the cached task_id without creating a duplicate task record
        assert res2.output["task_id"] == task_id

        # Total tasks in DB must be exactly 1
        all_tasks = db_session.scalars(
            select(Task).where(Task.tenant_id == test_tenant.id, Task.title == "Idempotent Task Creation")
        ).all()
        assert len(all_tasks) == 1


# ==============================================================================
# Document Download API Tests (with Tenant Isolation)
# ==============================================================================

class TestDocumentDownloadAPI:
    def test_tenant_can_download_own_document(
        self, client: TestClient, db_session: Session, test_tenant: Tenant, tmp_path: Path
    ):
        # Generate document
        tool = DocumentGeneratorTool(db_session, base_storage_dir=tmp_path)
        ctx = ToolExecutionContext(tenant_id=test_tenant.id)
        doc_info = tool.run(ctx, title="Customer Statement", format="html", content="Account Balance: 500 SAR")
        db_session.commit()

        doc_id = doc_info["document_id"]

        # Request download via API
        resp = client.get(f"/api/v1/documents/{doc_id}/download")
        assert resp.status_code == 200
        assert "Account Balance: 500 SAR" in resp.text
        assert resp.headers["content-type"].startswith("text/html")

    def test_tenant_cannot_download_other_tenant_document(
        self, client: TestClient, db_session: Session, tmp_path: Path
    ):
        other_tenant = Tenant(name="Hostile Tenant", slug=f"hostile-{uuid.uuid4().hex[:6]}")
        db_session.add(other_tenant)
        db_session.commit()

        # Other tenant's document
        tool = DocumentGeneratorTool(db_session, base_storage_dir=tmp_path)
        ctx = ToolExecutionContext(tenant_id=other_tenant.id)
        doc_info = tool.run(ctx, title="Confidential", format="txt", content="Secret")
        db_session.commit()

        other_doc_id = doc_info["document_id"]

        # Current user (test_user from test_tenant) requests other tenant's document
        resp = client.get(f"/api/v1/documents/{other_doc_id}/download")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Document not found"

    def test_document_download_rejects_path_outside_tenant_sandbox(
        self, client: TestClient, db_session: Session, test_tenant: Tenant, tmp_path: Path
    ):
        # Create a document record whose file_path points outside the tenant's folder
        outside_file = tmp_path / "system.conf"
        outside_file.write_text("root=true", encoding="utf-8")

        fake_doc = GeneratedDocument(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            title="Escaped Doc",
            document_type="report",
            format="txt",
            filename="system.conf",
            file_path=str(outside_file),
            file_size=len("root=true"),
            mime_type="text/plain",
        )
        db_session.add(fake_doc)
        db_session.commit()

        resp = client.get(f"/api/v1/documents/{fake_doc.id}/download")
        assert resp.status_code == 403
        assert "escapes tenant boundary" in resp.json()["detail"]


# ==============================================================================
# Webhooks Endpoints Tests
# ==============================================================================

class TestWebhookEndpoints:
    def test_whatsapp_webhook_challenge_get(
        self, client: TestClient, db_session: Session, test_tenant: Tenant
    ):
        service = ChannelService(db_session)
        channel = service.register_channel(
            tenant_id=test_tenant.id,
            name="Meta Channel",
            channel_type="whatsapp",
            config={
                "phone_number_id": "999888777",
                "access_token": "valid-token",
                "webhook_verify_token": "meta-verify-12345",
            },
        )
        db_session.commit()

        resp = client.get(
            f"/api/v1/webhooks/whatsapp/{channel.id}",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "meta-verify-12345",
                "hub.challenge": "challenge_string_abc",
            },
        )
        assert resp.status_code == 200
        assert resp.text == "challenge_string_abc"

    def test_telegram_webhook_post_event(
        self, client: TestClient, db_session: Session, test_tenant: Tenant
    ):
        service = ChannelService(db_session)
        channel = service.register_channel(
            tenant_id=test_tenant.id,
            name="Telegram Channel",
            channel_type="telegram",
            config={
                "bot_token": "123:token",
                "secret_token": "tg-secret-999",
            },
        )
        db_session.commit()

        payload = {
            "update_id": 10001,
            "message": {
                "message_id": 501,
                "from": {"id": 999111, "first_name": "Tariq"},
                "chat": {"id": 999111},
                "text": "مرحباً، أود معرفة ساعات العمل",
                "date": 1670000000,
            },
        }

        # Request with valid secret token
        resp = client.post(
            f"/api/v1/webhooks/telegram/{channel.id}",
            headers={"X-Telegram-Bot-Api-Secret-Token": "tg-secret-999"},
            json=payload,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["processed_count"] == 1

        # Verify message persisted in database
        msg = db_session.scalar(
            select(Message).where(Message.content == "مرحباً، أود معرفة ساعات العمل")
        )
        assert msg is not None
        assert msg.sender_type == "customer"

    def test_webhook_rejects_inactive_channel(
        self, client: TestClient, db_session: Session, test_tenant: Tenant
    ):
        service = ChannelService(db_session)
        channel = service.register_channel(
            tenant_id=test_tenant.id,
            name="Paused Telegram",
            channel_type="telegram",
            config={"bot_token": "token", "secret_token": "secret"},
        )
        channel.status = "inactive"
        db_session.commit()

        resp = client.post(
            f"/api/v1/webhooks/telegram/{channel.id}",
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
            json={"update_id": 1, "message": {"message_id": 1, "chat": {"id": 1}, "text": "Hi"}},
        )
        assert resp.status_code == 400
        assert "Channel is not active" in resp.json()["detail"]
