from __future__ import annotations

import os
from datetime import datetime, timezone
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
    Capability,
    CapabilityVersion,
    DevelopmentRequest,
    DevelopmentRun,
    Task,
    Tool,
    User,
)
from packages.models.tenant import Tenant
from packages.self_development.continuous_improvement import ContinuousImprovementService
from packages.self_development.dynamic_tool import DynamicCapabilityTool
from packages.self_development.engine import SelfDevelopmentEngine
from packages.self_development.sandbox import ExecutionSandbox
from packages.self_development.specification import (
    CapabilitySpecification,
    validate_and_classify_specification,
)
from packages.self_development.verifier import CapabilitySecurityVerifier
from packages.tools.registry import ToolRegistry


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


def create_test_tenant(name: str = "SelfDev Tenant") -> Tenant:
    db = SessionLocal()
    tenant = Tenant(
        id=uuid4(),
        name=name,
        slug=f"{name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        status="active",
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    t_id = tenant.id
    t_slug = tenant.slug
    db.close()
    tenant.id = t_id
    tenant.slug = t_slug
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
    u_id = user.id
    u_role = user.role
    u_tenant_id = user.tenant_id
    u_email = user.email
    db.close()

    user.id = u_id
    user.role = u_role
    user.tenant_id = u_tenant_id
    user.email = u_email

    token = create_access_token(user.id, user.tenant_id, user.role)
    return user, token


def create_test_agent(tenant_id, name: str = "Test Agent") -> Agent:
    db = SessionLocal()
    agent = Agent(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        agent_type="main",
        status="active",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    a_id = agent.id
    db.close()
    agent.id = a_id
    return agent



# =============================================================================
# 1. Specification Validation & Risk Escalation
# =============================================================================


def test_specification_validation_valid():
    spec_data = {
        "name": "Currency Converter",
        "slug": "currency-converter",
        "description": "Converts currency amounts between USD, EUR, and SAR.",
        "purpose": "Provide accurate currency conversion rates for finance operations.",
        "inputs": {"amount": "number", "from_cur": "string", "to_cur": "string"},
        "outputs": {"converted_amount": "number"},
        "risk_level": "low",
        "acceptance_tests": [
            {
                "input": {"amount": 100, "from_cur": "USD", "to_cur": "SAR"},
                "expected": {"converted_amount": 375},
            }
        ],
    }
    spec = validate_and_classify_specification(spec_data)
    assert spec.slug == "currency-converter"
    assert spec.risk_level == "low"


def test_specification_validation_invalid_slug():
    spec_data = {
        "name": "Bad Slug Tool",
        "slug": "bad slug with spaces!!",
        "description": "Invalid slug tool.",
        "purpose": "Test invalid slug rejection.",
    }
    with pytest.raises(ValueError):
        validate_and_classify_specification(spec_data)


def test_specification_risk_escalation_secrets():
    spec_data = {
        "name": "Payment Gateway Link",
        "slug": "payment-gateway",
        "description": "Communicates with payment provider using secret key.",
        "purpose": "Integrate third party billing API.",
        "secrets_required": ["PAYMENT_API_SECRET"],
        "risk_level": "low",  # Should be escalated to high!
    }
    spec = validate_and_classify_specification(spec_data)
    assert spec.risk_level == "high"


def test_specification_risk_escalation_keywords():
    spec_data = {
        "name": "Bank Transfer Automator",
        "slug": "bank-transfer",
        "description": "Performs financial transfer of tenant capital to vendor accounts.",
        "purpose": "Execute vendor payouts.",
        "risk_level": "low",  # Contains 'financial' and 'transfer' -> escalate to high
    }
    spec = validate_and_classify_specification(spec_data)
    assert spec.risk_level == "high"


# =============================================================================
# 2. AST Static Security Verifier
# =============================================================================


def test_ast_blocks_forbidden_calls():
    verifier = CapabilitySecurityVerifier()

    code_eval = "def run(inputs):\n    return eval(inputs['expr'])"
    res = verifier.verify_ast(code_eval)
    assert not res["valid"]
    assert any("eval" in v for v in res["violations"])

    code_exec = "def run(inputs):\n    exec('import os')"
    res2 = verifier.verify_ast(code_exec)
    assert not res2["valid"]
    assert any("exec" in v for v in res2["violations"])

    code_open = "def run(inputs):\n    f = open('/etc/passwd')\n    return f.read()"
    res3 = verifier.verify_ast(code_open)
    assert not res3["valid"]
    assert any("open" in v for v in res3["violations"])


def test_ast_blocks_forbidden_modules():
    verifier = CapabilitySecurityVerifier()

    code_socket = "import socket\ndef run(inputs):\n    s = socket.socket()"
    res = verifier.verify_ast(code_socket)
    assert not res["valid"]
    assert any("socket" in v for v in res["violations"])

    code_subprocess = "import subprocess\ndef run(inputs):\n    subprocess.run(['ls'])"
    res2 = verifier.verify_ast(code_subprocess)
    assert not res2["valid"]
    assert any("subprocess" in v for v in res2["violations"])


def test_ast_blocks_dangerous_attributes():
    verifier = CapabilitySecurityVerifier()

    code = "import os\ndef run(inputs):\n    os.system('id')"
    res = verifier.verify_ast(code)
    assert not res["valid"]
    assert any("system" in v or "os" in v for v in res["violations"])


def test_ast_allows_clean_python():
    verifier = CapabilitySecurityVerifier()
    clean_code = (
        "import math\n"
        "import json\n"
        "def run(inputs):\n"
        "    x = inputs.get('x', 0)\n"
        "    return {'result': math.sqrt(x)}\n"
    )
    res = verifier.verify_ast(clean_code)
    assert res["valid"]
    assert len(res["violations"]) == 0


# =============================================================================
# 3. Execution Sandbox Isolation
# =============================================================================


def test_sandbox_executes_safe_code():
    sandbox = ExecutionSandbox(timeout_seconds=5)
    code = (
        "def run(inputs):\n"
        "    a = inputs.get('a', 0)\n"
        "    b = inputs.get('b', 0)\n"
        "    return {'sum': a + b}\n"
    )
    result = sandbox.execute(code, inputs={"a": 10, "b": 25})
    assert result.success
    assert result.output == {"sum": 35}
    assert result.exit_code == 0
    assert not result.timed_out


def test_sandbox_enforces_timeout():
    sandbox = ExecutionSandbox(timeout_seconds=1)
    infinite_loop_code = (
        "def run(inputs):\n"
        "    while True:\n"
        "        pass\n"
    )
    result = sandbox.execute(infinite_loop_code, inputs={})
    assert not result.success
    assert result.timed_out
    assert "timed out" in (result.error or "").lower()


def test_sandbox_strips_host_secrets():
    # Set a sensitive host environment variable
    os.environ["SECRET_TEST_TOKEN"] = "SUPER_SECRET_12345"
    sandbox = ExecutionSandbox(timeout_seconds=5)
    code = (
        "import os\n"
        "def run(inputs):\n"
        "    found = os.getenv('SECRET_TEST_TOKEN', 'not_found')\n"
        "    return {'found': found}\n"
    )
    result = sandbox.execute(code, inputs={})
    assert result.success
    assert result.output == {"found": "not_found"}


# =============================================================================
# 4. Engine: Need Discovery & Duplicate Detection
# =============================================================================


def test_create_development_request_unique():
    tenant = create_test_tenant("Tenant Need")
    db = SessionLocal()
    engine = SelfDevelopmentEngine(db=db)

    req, is_dup = engine.create_development_request(
        tenant_id=tenant.id,
        title="VAT Calculation",
        reason="Agent needs to compute Saudi VAT rate for invoices",
        requirements={"slug": "vat-calculation", "rate": 0.15},
    )
    assert not is_dup
    assert req.status == "requested"
    assert req.title == "VAT Calculation"

    # Verify audit event
    audit = db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.event_type == "self_development.request.created",
        )
    )
    assert audit is not None
    db.close()


def test_create_development_request_duplicate_capability():
    tenant = create_test_tenant("Tenant Dup Cap")
    db = SessionLocal()

    # Create active capability
    cap = Capability(
        id=uuid4(),
        tenant_id=tenant.id,
        name="Invoice Parser",
        slug="invoice-parser",
        description="Extracts data from invoices",
        config={},
        is_active=True,
    )
    db.add(cap)
    db.commit()

    engine = SelfDevelopmentEngine(db=db)
    req, is_dup = engine.create_development_request(
        tenant_id=tenant.id,
        title="Invoice Parser",
        reason="Agent needs to parse invoice documents",
        requirements={"slug": "invoice-parser"},
    )
    assert is_dup
    assert req.status == "already_satisfied"
    assert req.requirements.get("already_satisfied_by") == "capability:invoice-parser"
    db.close()


def test_create_development_request_duplicate_tool():
    tenant = create_test_tenant("Tenant Dup Tool")
    db = SessionLocal()

    # Create active Tool record
    tool = Tool(
        id=uuid4(),
        tenant_id=tenant.id,
        name="PDF Generator",
        slug="generate_document",
        tool_type="system",
        description="Generates documents",
        is_active=True,
    )
    db.add(tool)

    db.commit()

    engine = SelfDevelopmentEngine(db=db)
    req, is_dup = engine.create_development_request(
        tenant_id=tenant.id,
        title="Generate Document",
        reason="Generate documents for customers",
        requirements={"slug": "generate_document"},
    )
    assert is_dup
    assert req.status == "already_satisfied"
    assert req.requirements.get("already_satisfied_by") == "tool:generate_document"
    db.close()


# =============================================================================
# 5. Full Lifecycle: Spec -> Develop -> Approve -> Activate -> Rollback
# =============================================================================


def test_full_self_development_lifecycle():
    tenant = create_test_tenant("Lifecycle Tenant")
    admin_user, _ = create_test_user(role="tenant_admin", tenant_id=tenant.id)
    agent_user, _ = create_test_user(role="agent", tenant_id=tenant.id)
    agent = create_test_agent(tenant_id=tenant.id, name="Sales Bot")

    db = SessionLocal()
    registry = ToolRegistry()
    engine = SelfDevelopmentEngine(db=db, tool_registry=registry)

    # 1. Need Discovery from agent
    req, is_dup = engine.create_development_request(
        tenant_id=tenant.id,
        title="Discount Calculator",
        reason="Needs dynamic discount computation for VIP customers",
        requirements={"slug": "discount-calculator"},
        requested_from="agent",
        agent_id=agent.id,
    )

    assert not is_dup
    assert req.status == "requested"

    # 2. Prepare specification
    spec_dict = {
        "name": "Discount Calculator",
        "slug": "discount-calculator",
        "description": "Calculates percentage discount for cart totals.",
        "purpose": "VIP cart discounting.",
        "inputs": {"subtotal": "number", "discount_pct": "number"},
        "outputs": {"discount": "number", "total": "number"},
        "risk_level": "medium",
        "acceptance_tests": [
            {
                "input": {"subtotal": 200, "discount_pct": 10},
                "expected": {"discount": 20, "total": 180},
            }
        ],
    }
    version_1 = engine.prepare_specification(
        tenant_id=tenant.id,
        request_id=req.id,
        spec_data=spec_dict,
        user=admin_user,
    )
    assert version_1.status == "specified"
    assert version_1.version_number == 1

    # 3. Develop & Test (Passing implementation)
    code_v1 = (
        "def run(inputs):\n"
        "    subtotal = inputs.get('subtotal', 0)\n"
        "    pct = inputs.get('discount_pct', 0)\n"
        "    discount = subtotal * (pct / 100)\n"
        "    return {'discount': discount, 'total': subtotal - discount}\n"
    )
    version_1, run_1 = engine.develop_and_test(
        tenant_id=tenant.id,
        version_id=version_1.id,
        implementation_code=code_v1,
    )
    assert run_1.status == "passed"
    assert version_1.status == "awaiting_approval"
    assert version_1.approval_id is not None

    # 4. Review & Approval (Agent cannot self-approve!)
    with pytest.raises(PermissionError) as exc_info:
        engine.review_and_approve(
            tenant_id=tenant.id,
            version_id=version_1.id,
            user=agent_user,  # The agent that requested it!
            approved=True,
        )
    assert "Agents cannot approve their own self-development requests" in str(exc_info.value)

    # Human admin approves
    version_1 = engine.review_and_approve(
        tenant_id=tenant.id,
        version_id=version_1.id,
        user=admin_user,
        approved=True,
        reason="Looks well-tested and verified",
    )
    assert version_1.status == "approved"

    # 5. Activation & Dynamic Tool Registry Binding
    version_1 = engine.activate_version(
        tenant_id=tenant.id,
        version_id=version_1.id,
        user=admin_user,
    )
    assert version_1.status == "active"
    assert registry.get("discount-calculator") is not None

    # Verify tool execution via ToolRegistry
    dyn_tool = registry.get("discount-calculator")
    exec_result = dyn_tool.execute({"subtotal": 100, "discount_pct": 15})
    assert exec_result.success
    assert exec_result.data == {"discount": 15, "total": 85}

    # 6. Develop version 2 with updated discount formula
    version_2 = engine.prepare_specification(
        tenant_id=tenant.id,
        request_id=req.id,
        spec_data=spec_dict,
        user=admin_user,
    )
    assert version_2.version_number == 2

    code_v2 = (
        "def run(inputs):\n"
        "    subtotal = inputs.get('subtotal', 0)\n"
        "    pct = inputs.get('discount_pct', 0)\n"
        "    discount = subtotal * (pct / 100)\n"
        "    # Added bonus logic\n"
        "    return {'discount': discount, 'total': subtotal - discount}\n"
    )
    version_2, run_2 = engine.develop_and_test(
        tenant_id=tenant.id,
        version_id=version_2.id,
        implementation_code=code_v2,
    )
    assert run_2.status == "passed"
    engine.review_and_approve(
        tenant_id=tenant.id,
        version_id=version_2.id,
        user=admin_user,
        approved=True,
    )
    version_2 = engine.activate_version(
        tenant_id=tenant.id,
        version_id=version_2.id,
        user=admin_user,
    )
    assert version_2.status == "active"

    # Verify v1 is now disabled
    db.refresh(version_1)
    assert version_1.status == "disabled"

    # 7. Rollback to version 1
    rolled_back = engine.disable_or_rollback(
        tenant_id=tenant.id,
        slug="discount-calculator",
        user=admin_user,
        reason="Need to revert to original v1 logic",
        rollback_to_version_number=1,
    )
    assert rolled_back.status == "active"
    assert rolled_back.version_number == 1

    db.refresh(version_2)
    assert version_2.status == "rolled_back"
    assert version_2.rollback_reason == "Need to revert to original v1 logic"

    db.close()


# =============================================================================
# 6. Multi-Tenant Isolation
# =============================================================================


def test_tenant_isolation_on_requests():
    tenant_a = create_test_tenant("Tenant A")
    tenant_b = create_test_tenant("Tenant B")
    user_a, token_a = create_test_user(role="tenant_admin", tenant_id=tenant_a.id)

    db = SessionLocal()
    engine = SelfDevelopmentEngine(db=db)
    req_b, _ = engine.create_development_request(
        tenant_id=tenant_b.id,
        title="Tenant B Private Tool",
        reason="Secret calculation",
    )
    req_b_id = req_b.id
    db.close()

    client = TestClient(app)
    # Tenant A attempts to access Tenant B's request
    resp = client.get(
        f"/api/v1/self-development/requests/{req_b_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Development request not found"


# =============================================================================
# 7. Continuous Improvement Reporting
# =============================================================================


def test_continuous_improvement_reports():
    tenant = create_test_tenant("Continuous Improvement Tenant")
    admin_user, admin_token = create_test_user(role="platform_admin", tenant_id=None)
    tenant_user, tenant_token = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    db = SessionLocal()
    # Create some failed tasks and requests
    task = Task(
        id=uuid4(),
        tenant_id=tenant.id,
        title="Failed PDF render",
        objective="Render Arabic PDF document",
        status="failed",
        error="Missing capability: arabic_pdf_stamping",
    )
    db.add(task)


    run = DevelopmentRun(
        id=uuid4(),
        tenant_id=tenant.id,
        run_type="sandbox_test",
        status="failed",
        error_message="Timeout in test suite",
        test_summary={"error": "Infinite loop detected"},
    )
    db.add(run)
    db.commit()
    db.close()

    client = TestClient(app)

    # Tenant-scoped report
    resp_tenant = client.get(
        "/api/v1/self-development/reports/continuous-improvement?days=30",
        headers={"Authorization": f"Bearer {tenant_token}"},
    )
    assert resp_tenant.status_code == 200
    tenant_data = resp_tenant.json()
    assert tenant_data["report_type"] == "tenant_scoped"
    assert tenant_data["metrics"]["failed_tasks_count"] >= 1
    assert tenant_data["metrics"]["failed_development_runs"] >= 1
    assert len(tenant_data["recommendations"]) >= 1

    # Platform-wide report by normal tenant admin must be forbidden
    resp_forbidden = client.get(
        "/api/v1/self-development/reports/continuous-improvement?platform_wide=true",
        headers={"Authorization": f"Bearer {tenant_token}"},
    )
    assert resp_forbidden.status_code == 403

    # Platform-wide report by platform admin
    resp_platform = client.get(
        "/api/v1/self-development/reports/continuous-improvement?platform_wide=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_platform.status_code == 200
    platform_data = resp_platform.json()
    assert platform_data["report_type"] == "platform_wide"
    assert "cross_tenant_failure_patterns" in platform_data


# =============================================================================
# 8. REST API Integration Tests
# =============================================================================


def test_api_self_development_endpoints():
    tenant = create_test_tenant("API Tenant")
    admin_user, admin_token = create_test_user(role="tenant_admin", tenant_id=tenant.id)
    headers = {"Authorization": f"Bearer {admin_token}"}
    client = TestClient(app)

    # 1. Create request
    resp = client.post(
        "/api/v1/self-development/requests",
        headers=headers,
        json={
            "problem_statement": "Need custom hash calculation for files",
            "desired_capability": "Checksum Verifier",
            "slug": "checksum-verifier",
            "priority": "normal",
        },
    )
    assert resp.status_code == 201
    req_data = resp.json()["request"]
    request_id = req_data["id"]

    # 2. List requests
    list_resp = client.get("/api/v1/self-development/requests", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["count"] >= 1

    # 3. Prepare spec
    spec_resp = client.post(
        f"/api/v1/self-development/requests/{request_id}/spec",
        headers=headers,
        json={
            "specification": {
                "name": "Checksum Verifier",
                "slug": "checksum-verifier",
                "description": "Calculates simple string length checksum.",
                "purpose": "Verify payload size.",
                "inputs": {"text": "string"},
                "outputs": {"length": "integer"},
                "risk_level": "low",
                "acceptance_tests": [
                    {"input": {"text": "hello"}, "expected": {"length": 5}}
                ],
            }
        },
    )
    assert spec_resp.status_code == 201
    version_id = spec_resp.json()["version"]["id"]

    # 4. Run develop & test
    dev_resp = client.post(
        f"/api/v1/self-development/versions/{version_id}/develop",
        headers=headers,
        json={
            "implementation_code": "def run(inputs):\n    return {'length': len(inputs.get('text', ''))}\n"
        },
    )
    assert dev_resp.status_code == 200
    assert dev_resp.json()["run"]["status"] == "passed"
    assert dev_resp.json()["version"]["status"] == "awaiting_approval"

    # 5. List runs
    runs_resp = client.get(
        f"/api/v1/self-development/versions/{version_id}/runs",
        headers=headers,
    )
    assert runs_resp.status_code == 200
    assert runs_resp.json()["count"] >= 1

    # 6. Approve
    approve_resp = client.post(
        f"/api/v1/self-development/versions/{version_id}/approve",
        headers=headers,
        json={"approved": True, "reason": "Tested and passed"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["version"]["status"] == "approved"

    # 7. Activate
    activate_resp = client.post(
        f"/api/v1/self-development/versions/{version_id}/activate",
        headers=headers,
    )
    assert activate_resp.status_code == 200
    assert activate_resp.json()["version"]["status"] == "active"

    # 8. List versions for slug
    versions_resp = client.get(
        "/api/v1/self-development/capabilities/checksum-verifier/versions",
        headers=headers,
    )
    assert versions_resp.status_code == 200
    assert versions_resp.json()["count"] >= 1

    # 9. Rollback / Disable
    disable_resp = client.post(
        "/api/v1/self-development/capabilities/checksum-verifier/rollback",
        headers=headers,
        json={"reason": "Temporary deprecation"},
    )
    assert disable_resp.status_code == 200
    assert disable_resp.json()["version"]["status"] == "disabled"
