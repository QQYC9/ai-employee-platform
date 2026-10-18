import os
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.core.database import SessionLocal
from packages.models.tenant import Tenant
from packages.models.domain import Agent, Customer, GeneratedDocument, Task, User
from packages.tools.business_tools import (
    BusinessSummaryTool,
    CustomerCreateOrUpdateTool,
    CustomerGetTool,
    CustomerSearchTool,
    TaskCreateTool,
    TaskQueryTool,
)
from packages.tools.contract import ToolExecutionContext, ToolRiskLevel
from packages.tools.document_tool import (
    DocumentGeneratorTool,
    DocumentSecurityError,
)
from packages.tools.http_tool import (
    HttpRequestTool,
    ResponseTooLargeError,
    SSRFGuard,
    SSRFSecurityViolationError,
)
from packages.tools.registry import create_default_registry


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
        name=f"Tools Tenant {uuid.uuid4().hex[:6]}",
        slug=f"tools-tenant-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


# ==============================================================================
# HTTP Request Tool & SSRF Guard Tests
# ==============================================================================

class TestSSRFGuard:
    def test_block_loopback_and_local(self):
        with pytest.raises(SSRFSecurityViolationError):
            SSRFGuard.validate_url("http://127.0.0.1/admin")

        with pytest.raises(SSRFSecurityViolationError):
            SSRFGuard.validate_url("http://localhost:8080/metrics")

    def test_block_unspecified_ip(self):
        with pytest.raises(SSRFSecurityViolationError):
            SSRFGuard.validate_url("http://0.0.0.0/status")

    def test_block_private_networks(self):
        with pytest.raises(SSRFSecurityViolationError):
            SSRFGuard.validate_url("http://10.0.0.5/api")

        with pytest.raises(SSRFSecurityViolationError):
            SSRFGuard.validate_url("http://172.16.1.100/data")

        with pytest.raises(SSRFSecurityViolationError):
            SSRFGuard.validate_url("http://192.168.1.1/router")

    def test_block_cloud_metadata(self):
        with pytest.raises(SSRFSecurityViolationError):
            SSRFGuard.validate_url("http://169.254.169.254/latest/meta-data/")

        with pytest.raises(SSRFSecurityViolationError):
            SSRFGuard.validate_url("http://metadata.google.internal/computeMetadata/v1/")

    def test_block_carrier_grade_nat(self):
        with pytest.raises(SSRFSecurityViolationError):
            SSRFGuard.validate_url("http://100.64.0.1/service")

    def test_domain_allowlist(self):
        # Disallowed domain
        with pytest.raises(SSRFSecurityViolationError):
            SSRFGuard.validate_url("https://api.stripe.com/v1", allowed_domains=["*.example.com"])

    def test_block_invalid_scheme_and_ports(self):
        # Disallowed scheme
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            SSRFGuard.validate_url("ftp://ftp.example.com/file.txt")

        # Disallowed port
        with pytest.raises(SSRFSecurityViolationError, match="not permitted"):
            SSRFGuard.validate_url("https://api.example.com:22/ssh")

        with pytest.raises(SSRFSecurityViolationError, match="not permitted"):
            SSRFGuard.validate_url("http://api.example.com:3306/db")

        # Allowed domain
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
            res = SSRFGuard.validate_url("https://api.example.com/v1", allowed_domains=["*.example.com"])
            assert res == "https://api.example.com/v1"

    def test_sanitize_sensitive_headers(self):
        raw = {
            "Authorization": "Bearer secret-token-12345",
            "X-Api-Key": "my-key-9999",
            "Content-Type": "application/json",
            "User-Agent": "AI-Employee",
        }
        sanitized = SSRFGuard.sanitize_headers(raw)
        assert sanitized["Authorization"] == "********"
        assert sanitized["X-Api-Key"] == "********"
        assert sanitized["Content-Type"] == "application/json"
        assert sanitized["User-Agent"] == "AI-Employee"


class TestHttpRequestTool:
    def test_successful_get_request(self):
        mock_response = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            json={"message": "hello world"},
            request=httpx.Request("GET", "https://api.example.com/data"),
        )
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.send.return_value = mock_response

        tool = HttpRequestTool(client=mock_client)
        ctx = ToolExecutionContext(tenant_id=uuid.uuid4())

        with patch.object(SSRFGuard, "validate_url", return_value="https://api.example.com/data"):
            result = tool.run(ctx, url="https://api.example.com/data", method="GET")

        assert result["status_code"] == 200
        assert result["is_success"] is True
        assert result["data"] == {"message": "hello world"}

    def test_response_size_limit_exceeded(self):
        # Create a response with 2MB of data
        large_bytes = b"X" * (2 * 1024 * 1024)
        mock_response = httpx.Response(
            status_code=200,
            headers={"content-type": "text/plain"},
            content=large_bytes,
            request=httpx.Request("GET", "https://api.example.com/big"),
        )
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.send.return_value = mock_response

        tool = HttpRequestTool(client=mock_client)
        ctx = ToolExecutionContext(tenant_id=uuid.uuid4())

        with patch.object(SSRFGuard, "validate_url", return_value="https://api.example.com/big"):
            with pytest.raises(ResponseTooLargeError):
                tool.run(ctx, url="https://api.example.com/big", max_response_bytes=1024 * 1024)

    def test_redirect_to_internal_ip_blocked(self):
        # 302 redirect response pointing to internal loopback
        mock_redirect = httpx.Response(
            status_code=302,
            headers={"location": "http://127.0.0.1/admin"},
            request=httpx.Request("GET", "https://api.example.com/redirect"),
        )
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.send.return_value = mock_redirect

        tool = HttpRequestTool(client=mock_client)
        ctx = ToolExecutionContext(tenant_id=uuid.uuid4())

        with patch.object(SSRFGuard, "validate_url", side_effect=[
            "https://api.example.com/redirect",
            SSRFSecurityViolationError("Loopback blocked"),
        ]):
            with pytest.raises(SSRFSecurityViolationError):
                tool.run(ctx, url="https://api.example.com/redirect")

    def test_cross_origin_redirect_strips_sensitive_headers(self):
        mock_redirect = httpx.Response(
            status_code=302,
            headers={"location": "https://other-domain.com/webhook"},
            request=httpx.Request("GET", "https://api.example.com/start"),
        )
        mock_final = httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            json={"status": "ok"},
            request=httpx.Request("GET", "https://other-domain.com/webhook"),
        )
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.send.side_effect = [mock_redirect, mock_final]

        tool = HttpRequestTool(client=mock_client)
        ctx = ToolExecutionContext(tenant_id=uuid.uuid4())

        with patch.object(SSRFGuard, "validate_url", side_effect=[
            "https://api.example.com/start",
            "https://other-domain.com/webhook",
        ]):
            result = tool.run(
                ctx,
                url="https://api.example.com/start",
                method="GET",
                headers={
                    "Authorization": "Bearer super-secret",
                    "X-Api-Key": "key-12345",
                    "X-Custom-Tracking": "track-999",
                },
            )

        assert result["status_code"] == 200
        # Verify the second call stripped Authorization and X-Api-Key
        second_request = mock_client.build_request.call_args_list[1]
        sent_headers = second_request.kwargs["headers"]
        assert "Authorization" not in sent_headers
        assert "authorization" not in sent_headers
        assert "X-Api-Key" not in sent_headers
        assert sent_headers.get("X-Custom-Tracking") == "track-999"

    def test_max_redirects_exceeded(self):
        mock_redirect = httpx.Response(
            status_code=302,
            headers={"location": "https://api.example.com/loop"},
            request=httpx.Request("GET", "https://api.example.com/loop"),
        )
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.send.return_value = mock_redirect

        tool = HttpRequestTool(client=mock_client)
        ctx = ToolExecutionContext(tenant_id=uuid.uuid4())

        with patch.object(SSRFGuard, "validate_url", return_value="https://api.example.com/loop"):
            with pytest.raises(ValueError, match="Too many redirects"):
                tool.run(ctx, url="https://api.example.com/loop")


# ==============================================================================
# Business Data Tools Tests
# ==============================================================================

class TestBusinessDataTools:
    def test_customer_search_and_get_tenant_isolation(self, db_session: Session, test_tenant: Tenant):
        other_tenant = Tenant(name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:6]}")
        db_session.add(other_tenant)
        db_session.commit()

        # Customer in test_tenant
        c1 = Customer(
            tenant_id=test_tenant.id,
            name="Ahmed Al-Farsi",
            email="ahmed@example.com",
            phone="+966500000001",
            status="active",
        )
        # Customer in other_tenant with same name
        c2 = Customer(
            tenant_id=other_tenant.id,
            name="Ahmed Al-Farsi",
            email="ahmed.other@example.com",
            phone="+966500000002",
            status="active",
        )
        db_session.add_all([c1, c2])
        db_session.commit()

        search_tool = CustomerSearchTool(db_session)
        ctx = ToolExecutionContext(tenant_id=test_tenant.id)

        # Search should only return customer belonging to test_tenant
        results = search_tool.run(ctx, query="Ahmed")
        assert len(results) == 1
        assert results[0]["id"] == str(c1.id)
        assert results[0]["email"] == "ahmed@example.com"

        # CustomerGetTool
        get_tool = CustomerGetTool(db_session)
        details = get_tool.run(ctx, customer_id=str(c1.id))
        assert details["name"] == "Ahmed Al-Farsi"

        # CustomerGetTool must reject accessing other tenant's customer
        with pytest.raises(ValueError, match="Customer not found"):
            get_tool.run(ctx, customer_id=str(c2.id))

    def test_customer_create_or_update(self, db_session: Session, test_tenant: Tenant):
        tool = CustomerCreateOrUpdateTool(db_session)
        ctx = ToolExecutionContext(tenant_id=test_tenant.id)

        # Create
        res1 = tool.run(ctx, name="Sara Khalid", phone="+966511111111", email="sara@example.com")
        assert res1["action"] == "created"
        assert res1["customer_id"] is not None

        # Update
        res2 = tool.run(ctx, name="Sara K. Al-Saud", phone="+966511111111", metadata={"vip": True})
        assert res2["action"] == "updated"
        assert res2["customer_id"] == res1["customer_id"]
        assert res2["name"] == "Sara K. Al-Saud"

    def test_task_create_and_query(self, db_session: Session, test_tenant: Tenant):
        create_tool = TaskCreateTool(db_session)
        query_tool = TaskQueryTool(db_session)
        ctx = ToolExecutionContext(tenant_id=test_tenant.id)

        # Create task
        created = create_tool.run(ctx, title="Review Monthly Financials", priority="high")
        assert created["task_id"] is not None
        assert created["title"] == "Review Monthly Financials"
        assert created["status"] == "pending"

        # Query tasks
        tasks = query_tool.run(ctx, status="pending")
        assert len(tasks) >= 1
        assert any(t["id"] == created["task_id"] for t in tasks)

    def test_task_create_rejects_cross_tenant_agent_id(self, db_session: Session, test_tenant: Tenant):
        other_tenant = Tenant(name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:6]}")
        db_session.add(other_tenant)
        db_session.commit()

        foreign_agent = Agent(
            tenant_id=other_tenant.id,
            name="Foreign Agent",
            agent_type="main",
            status="active",
        )
        db_session.add(foreign_agent)
        db_session.commit()

        create_tool = TaskCreateTool(db_session)
        ctx = ToolExecutionContext(tenant_id=test_tenant.id)

        with pytest.raises(ValueError, match="not found for tenant"):
            create_tool.run(
                ctx,
                title="Unauthorized Task",
                agent_id=str(foreign_agent.id),
            )

    def test_business_summary_report(self, db_session: Session, test_tenant: Tenant):
        summary_tool = BusinessSummaryTool(db_session)
        ctx = ToolExecutionContext(tenant_id=test_tenant.id)

        report = summary_tool.run(ctx, days=14)
        assert report["tenant_id"] == str(test_tenant.id)
        assert "metrics" in report
        assert "total_customers" in report["metrics"]
        assert "active_conversations" in report["metrics"]


# ==============================================================================
# Document Generator Tool Tests
# ==============================================================================

class TestDocumentGeneratorTool:
    def test_generate_html_document_with_arabic(self, db_session: Session, test_tenant: Tenant, tmp_path: Path):
        tool = DocumentGeneratorTool(db_session, base_storage_dir=tmp_path)
        ctx = ToolExecutionContext(tenant_id=test_tenant.id)

        title = "تقرير الأداء الشهري للشركة"
        content = "تم تحقيق الأهداف بنسبة 98% خلال الربع الثالث."

        result = tool.run(
            ctx,
            title=title,
            format="html",
            content=content,
            language="ar",
        )

        doc_id = uuid.UUID(result["document_id"])
        assert result["format"] == "html"
        assert result["file_size"] > 0
        assert result["sha256_hash"] is not None

        # Check physical file exists on disk
        tenant_folder = tmp_path / str(test_tenant.id)
        assert tenant_folder.exists()
        file_path = tenant_folder / result["filename"]
        assert file_path.exists()

        file_text = file_path.read_text(encoding="utf-8")
        assert "dir=\"rtl\"" in file_text
        assert title in file_text
        assert content in file_text

        # Check database record
        record = db_session.scalar(select(GeneratedDocument).where(GeneratedDocument.id == doc_id))
        assert record is not None
        assert record.tenant_id == test_tenant.id
        assert record.title == title

    def test_generate_pdf_document(self, db_session: Session, test_tenant: Tenant, tmp_path: Path):
        tool = DocumentGeneratorTool(db_session, base_storage_dir=tmp_path)
        ctx = ToolExecutionContext(tenant_id=test_tenant.id)

        result = tool.run(
            ctx,
            title="Executive Summary",
            format="pdf",
            content="Summary metrics and operational analysis.",
        )

        file_path = tmp_path / str(test_tenant.id) / result["filename"]
        assert file_path.exists()
        pdf_bytes = file_path.read_bytes()
        assert pdf_bytes.startswith(b"%PDF-1.4")
        assert b"Executive Summary" in pdf_bytes

    def test_prevent_path_traversal(self, db_session: Session, test_tenant: Tenant, tmp_path: Path):
        tool = DocumentGeneratorTool(db_session, base_storage_dir=tmp_path)
        ctx = ToolExecutionContext(tenant_id=test_tenant.id)

        # Attempt path traversal via title
        result = tool.run(
            ctx,
            title="../../../../evil_script",
            format="txt",
            content="malicious payload",
        )

        # Verified that filename was safely sanitized and kept inside tenant directory
        file_path = tmp_path / str(test_tenant.id) / result["filename"]
        assert file_path.exists()
        assert tmp_path / str(test_tenant.id) in file_path.parents


class TestToolRegistry:
    def test_create_default_registry_contracts(self, db_session: Session):
        registry = create_default_registry(db_session)
        contracts = registry.list_contracts()
        slugs = {c.slug for c in contracts}

        expected_slugs = {
            "http_request",
            "customer_search",
            "customer_get",
            "customer_create_or_update",
            "task_query",
            "task_create",
            "business_summary",
            "generate_document",
        }
        assert expected_slugs.issubset(slugs)

    def test_executor_handler_prevents_tenant_parameter_spoofing(self, db_session: Session, test_tenant: Tenant):
        registry = create_default_registry(db_session)
        search_tool = registry.get("customer_search")
        assert search_tool is not None

        # Handler bound to test_tenant
        handler = registry._create_executor_handler(search_tool, default_tenant_id=test_tenant.id)

        # Attacker tries to pass another tenant_id in parameters
        hostile_tenant_id = uuid.uuid4()
        with patch.object(search_tool, "execute") as mock_exec:
            mock_exec.return_value = MagicMock(success=True, data=[])
            handler(tenant_id=hostile_tenant_id, query="Ahmed")

            # Must execute with test_tenant.id, NOT hostile_tenant_id!
            call_ctx = mock_exec.call_args[0][0]
            assert call_ctx.tenant_id == test_tenant.id
