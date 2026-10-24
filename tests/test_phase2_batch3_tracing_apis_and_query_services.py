from __future__ import annotations

from datetime import datetime, timezone, timedelta
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.agent.main import app
from packages.auth.jwt_service import create_access_token
from packages.core.database import SessionLocal
from packages.models.domain import (
    Agent,
    Conversation,
    ExecutionStep,
    ExecutionTrace,
    Permission,
    Task,
    User,
)
from packages.models.tenant import Tenant
from packages.services.tracing_query_service import TracingQueryService


client = TestClient(app)


@pytest.fixture
def db():
    session = SessionLocal()
    tenant_ids = []

    def register_tenant(tid: uuid.UUID):
        tenant_ids.append(tid)

    session.register_tenant = register_tenant

    try:
        yield session
    finally:
        for tid in reversed(tenant_ids):
            try:
                t = session.get(Tenant, tid)
                if t:
                    session.delete(t)
                    session.commit()
            except Exception:
                session.rollback()
        session.close()


def create_tenant_and_user(db: Session, role: str = "tenant_admin", prefix: str = "t") -> tuple[Tenant, User, str]:
    uid = uuid.uuid4().hex[:8]
    tenant = Tenant(
        id=uuid.uuid4(),
        name=f"Tenant {prefix} {uid}",
        slug=f"{prefix}-{uid}",
        status="active",
    )
    db.add(tenant)
    db.flush()

    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name=f"User {prefix}",
        email=f"user-{prefix}-{uid}@test.com",
        role=role,
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(tenant)
    db.refresh(user)

    if hasattr(db, "register_tenant"):
        db.register_tenant(tenant.id)

    token = create_access_token(user_id=user.id, tenant_id=tenant.id, role=role)
    return tenant, user, token


def create_trace(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    trigger_type: str = "inbound_message",
    status: str = "completed",
    task_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    duration_ms: int = 150,
    started_at: datetime | None = None,
    error_summary: dict | None = None,
    metadata_json: dict | None = None,
) -> ExecutionTrace:
    trace = ExecutionTrace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        trace_id=uuid.uuid4(),
        trigger_type=trigger_type,
        task_id=task_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
        status=status,
        started_at=started_at or datetime.now(timezone.utc),
        completed_at=(started_at or datetime.now(timezone.utc)) + timedelta(milliseconds=duration_ms),
        duration_ms=duration_ms,
        error_summary=error_summary,
        metadata_json=metadata_json or {},
    )
    db.add(trace)
    db.commit()
    db.refresh(trace)
    return trace


def create_step(
    db: Session,
    tenant_id: uuid.UUID,
    trace_id: uuid.UUID,
    *,
    step_order: int = 1,
    step_type: str = "router",
    step_name: str = "Route Customer Message",
    parent_step_id: uuid.UUID | None = None,
    status: str = "completed",
    duration_ms: int = 45,
    input_summary: dict | None = None,
    output_summary: dict | None = None,
    error_info: dict | None = None,
) -> ExecutionStep:
    step = ExecutionStep(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        trace_id=trace_id,
        parent_step_id=parent_step_id,
        step_order=step_order,
        step_type=step_type,
        step_name=step_name,
        status=status,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc) + timedelta(milliseconds=duration_ms),
        duration_ms=duration_ms,
        input_summary=input_summary or {},
        output_summary=output_summary or {},
        error_info=error_info,
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


# ==============================================================================
# SECTION 1: TRACE LISTING, PAGINATION & SORTING TESTS
# ==============================================================================

def test_list_traces_empty(db: Session):
    tenant, user, token = create_tenant_and_user(db, role="tenant_admin", prefix="empty")
    resp = client.get("/api/v1/traces", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["limit"] == 20
    assert data["offset"] == 0
    assert data["has_more"] is False


def test_list_traces_pagination_and_sorting(db: Session):
    tenant, user, token = create_tenant_and_user(db, role="tenant_admin", prefix="pagi")
    base_time = datetime.now(timezone.utc)

    created_traces = []
    for i in range(15):
        t = create_trace(
            db,
            tenant.id,
            trigger_type="task_execution",
            started_at=base_time + timedelta(minutes=i),
            duration_ms=100 + i * 10,
        )
        created_traces.append(t)

    # First page: limit 5, offset 0 (default desc: newest first)
    resp = client.get(
        "/api/v1/traces?limit=5&offset=0&sort_order=desc",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 5
    assert data["total"] == 15
    assert data["limit"] == 5
    assert data["offset"] == 0
    assert data["has_more"] is True
    # Newest trace should be created_traces[-1]
    assert data["items"][0]["id"] == str(created_traces[-1].id)

    # Second page: limit 5, offset 5
    resp2 = client.get(
        "/api/v1/traces?limit=5&offset=5&sort_order=desc",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["items"]) == 5
    assert data2["has_more"] is True

    # Third page: limit 5, offset 10 (last 5)
    resp3 = client.get(
        "/api/v1/traces?limit=5&offset=10&sort_order=desc",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert len(data3["items"]) == 5
    assert data3["has_more"] is False

    # Ascending sort (oldest first)
    resp_asc = client.get(
        "/api/v1/traces?limit=5&offset=0&sort_order=asc",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_asc.status_code == 200
    data_asc = resp_asc.json()
    assert data_asc["items"][0]["id"] == str(created_traces[0].id)

    # Boundary test: limit > 100 clamped to 100
    resp_large = client.get(
        "/api/v1/traces?limit=500",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_large.status_code == 200
    assert resp_large.json()["limit"] == 100


# ==============================================================================
# SECTION 2: FILTERING TESTS
# ==============================================================================

def test_list_traces_filters(db: Session):
    tenant, user, token = create_tenant_and_user(db, role="tenant_admin", prefix="filt")

    # Create real referenced entities to respect composite foreign key constraints
    conv = Conversation(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        status="open",
    )
    task = Task(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        title="Filter Test Task",
        objective="Testing trace filters",
    )
    agent = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Filter Test Agent",
        agent_type="worker",
        status="active",
    )
    db.add_all([conv, task, agent])
    db.commit()

    task_id_target = task.id
    agent_id_target = agent.id
    conv_id_target = conv.id

    t_now = datetime.now(timezone.utc)
    t1 = create_trace(
        db,
        tenant.id,
        trigger_type="inbound_message",
        status="completed",
        conversation_id=conv_id_target,
        started_at=t_now - timedelta(hours=2),
    )
    t2 = create_trace(
        db,
        tenant.id,
        trigger_type="task_execution",
        status="failed",
        task_id=task_id_target,
        started_at=t_now - timedelta(hours=1),
    )
    t3 = create_trace(
        db,
        tenant.id,
        trigger_type="scheduled_task",
        status="running",
        agent_id=agent_id_target,
        started_at=t_now,
    )

    # 1. Filter by status
    resp_status = client.get("/api/v1/traces?status=failed", headers={"Authorization": f"Bearer {token}"})
    assert resp_status.status_code == 200
    items = resp_status.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(t2.id)

    # 2. Filter by trigger_type
    resp_trig = client.get("/api/v1/traces?trigger_type=inbound_message", headers={"Authorization": f"Bearer {token}"})
    assert resp_trig.status_code == 200
    items = resp_trig.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(t1.id)

    # 3. Filter by task_id
    resp_task = client.get(f"/api/v1/traces?task_id={task_id_target}", headers={"Authorization": f"Bearer {token}"})
    assert resp_task.status_code == 200
    items = resp_task.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(t2.id)

    # 4. Filter by agent_id
    resp_agent = client.get(f"/api/v1/traces?agent_id={agent_id_target}", headers={"Authorization": f"Bearer {token}"})
    assert resp_agent.status_code == 200
    items = resp_agent.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(t3.id)

    # 5. Filter by conversation_id
    resp_conv = client.get(f"/api/v1/traces?conversation_id={conv_id_target}", headers={"Authorization": f"Bearer {token}"})
    assert resp_conv.status_code == 200
    items = resp_conv.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(t1.id)

    # 6. Filter by time range
    t_after = (t_now - timedelta(minutes=30)).isoformat()
    resp_time = client.get(f"/api/v1/traces?started_after={t_after}", headers={"Authorization": f"Bearer {token}"})
    assert resp_time.status_code == 200
    items = resp_time.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(t3.id)


# ==============================================================================
# SECTION 3: TRACE DETAILS & SUMMARY METRICS
# ==============================================================================

def test_get_trace_details_and_summary(db: Session):
    tenant, user, token = create_tenant_and_user(db, role="tenant_admin", prefix="det")
    trace = create_trace(db, tenant.id, trigger_type="inbound_message", status="completed", duration_ms=250)

    # Add 3 steps
    s1 = create_step(db, tenant.id, trace.id, step_order=1, step_type="router", status="completed")
    s2 = create_step(db, tenant.id, trace.id, step_order=2, step_type="ai_generation", status="completed")
    s3 = create_step(db, tenant.id, trace.id, step_order=3, step_type="tool", status="completed")

    # Get by PK id
    resp = client.get(f"/api/v1/traces/{trace.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(trace.id)
    assert data["status"] == "completed"
    assert data["step_count"] == 3
    assert data["duration_ms"] == 250

    # Get by business trace_id
    resp_tid = client.get(f"/api/v1/traces/{trace.trace_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp_tid.status_code == 200
    assert resp_tid.json()["id"] == str(trace.id)

    # Get summary
    resp_sum = client.get(f"/api/v1/traces/{trace.id}/summary", headers={"Authorization": f"Bearer {token}"})
    assert resp_sum.status_code == 200
    sum_data = resp_sum.json()
    assert sum_data["total_steps"] == 3
    assert sum_data["status_breakdown"]["completed"] == 3
    assert sum_data["step_type_breakdown"]["router"] == 1
    assert sum_data["step_type_breakdown"]["ai_generation"] == 1
    assert sum_data["step_type_breakdown"]["tool"] == 1


def test_trace_with_no_steps(db: Session):
    tenant, user, token = create_tenant_and_user(db, role="tenant_admin", prefix="nostep")
    trace = create_trace(db, tenant.id, trigger_type="scheduled_task", status="running")

    # Trace details
    resp = client.get(f"/api/v1/traces/{trace.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["step_count"] == 0

    # Steps tree
    resp_steps = client.get(f"/api/v1/traces/{trace.id}/steps", headers={"Authorization": f"Bearer {token}"})
    assert resp_steps.status_code == 200
    assert resp_steps.json()["steps"] == []

    # Summary
    resp_sum = client.get(f"/api/v1/traces/{trace.id}/summary", headers={"Authorization": f"Bearer {token}"})
    assert resp_sum.status_code == 200
    assert resp_sum.json()["total_steps"] == 0
    assert resp_sum.json()["status_breakdown"] == {}


def test_failed_trace_sanitized_error(db: Session):
    tenant, user, token = create_tenant_and_user(db, role="tenant_admin", prefix="fail")
    secret_key = "AIzaSyD-FailedTraceSecretKey123456"
    raw_error = {
        "error": f"Connection failed using {secret_key}",
        "apiKey": "plain_secret_apiKey_val",
        "nested": {"token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"},
    }
    trace = create_trace(
        db,
        tenant.id,
        status="failed",
        error_summary=raw_error,
        duration_ms=120,
    )

    resp = client.get(f"/api/v1/traces/{trace.id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    err = resp.json()["error_summary"]
    assert secret_key not in str(err)
    assert "[REDACTED_API_KEY]" in err["error"]
    assert err["apiKey"] == "[REDACTED]"
    assert err["nested"]["token"] == "[REDACTED]"


# ==============================================================================
# SECTION 4: STEP TREE HIERARCHY & MULTI-LEVEL NESTING
# ==============================================================================

def test_step_tree_hierarchy_multi_level(db: Session):
    tenant, user, token = create_tenant_and_user(db, role="tenant_admin", prefix="tree")
    trace = create_trace(db, tenant.id, status="completed")

    # Step 1: Root orchestrator step
    s1 = create_step(db, tenant.id, trace.id, step_order=1, step_type="orchestrator", step_name="Root Step")

    # Step 2: Child of Step 1 (tool execution)
    s2 = create_step(
        db,
        tenant.id,
        trace.id,
        step_order=2,
        step_type="tool",
        step_name="Child Step",
        parent_step_id=s1.id,
    )

    # Step 3: Grandchild (child of Step 2, e.g. sub-action or verification)
    s3 = create_step(
        db,
        tenant.id,
        trace.id,
        step_order=3,
        step_type="verification",
        step_name="Grandchild Step",
        parent_step_id=s2.id,
    )

    # Step 4: Another independent root step
    s4 = create_step(db, tenant.id, trace.id, step_order=4, step_type="ai_generation", step_name="Second Root")

    # 1. Test Hierarchical Tree Format (default)
    resp_tree = client.get(f"/api/v1/traces/{trace.id}/steps?format=tree", headers={"Authorization": f"Bearer {token}"})
    assert resp_tree.status_code == 200
    tree_data = resp_tree.json()
    assert tree_data["format"] == "tree"
    roots = tree_data["steps"]

    # There should be exactly 2 root steps
    assert len(roots) == 2
    assert roots[0]["id"] == str(s1.id)
    assert roots[1]["id"] == str(s4.id)

    # Check Step 1 children: has Step 2
    assert len(roots[0]["children"]) == 1
    child_node = roots[0]["children"][0]
    assert child_node["id"] == str(s2.id)

    # Check Step 2 children: has Step 3 (Grandchild)
    assert len(child_node["children"]) == 1
    grandchild_node = child_node["children"][0]
    assert grandchild_node["id"] == str(s3.id)
    assert grandchild_node["children"] == []

    # Step 4 has no children
    assert roots[1]["children"] == []

    # 2. Test Flat Format
    resp_flat = client.get(f"/api/v1/traces/{trace.id}/steps?format=flat", headers={"Authorization": f"Bearer {token}"})
    assert resp_flat.status_code == 200
    flat_data = resp_flat.json()
    assert flat_data["format"] == "flat"
    flat_steps = flat_data["steps"]
    assert len(flat_steps) == 4
    assert [s["id"] for s in flat_steps] == [str(s1.id), str(s2.id), str(s3.id), str(s4.id)]


def test_orphan_step_handling_in_query_service(db: Session):
    """
    Test that TracingQueryService._build_step_tree gracefully attaches
    orphan steps to root when their parent is not present in the step list.
    """
    service = TracingQueryService(db)
    orphan_step = ExecutionStep(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        parent_step_id=uuid.uuid4(),  # Missing from the list
        step_order=1,
        step_type="router",
        step_name="Orphan Router Step",
        status="completed",
        started_at=datetime.now(timezone.utc),
    )

    tree = service._build_step_tree([orphan_step])
    assert len(tree) == 1
    assert tree[0]["id"] == str(orphan_step.id)
    assert tree[0]["children"] == []


# ==============================================================================
# SECTION 5: SENSITIVE DATA SANITIZATION IN STEP PAYLOADS
# ==============================================================================

def test_step_sanitization_input_output_error(db: Session):
    tenant, user, token = create_tenant_and_user(db, role="tenant_admin", prefix="sanstep")
    trace = create_trace(db, tenant.id)

    google_api_key = "AIzaSyD-RealSecretGoogleAPIKey987654"
    openai_key = "sk-123456789012345678"

    step = create_step(
        db,
        tenant.id,
        trace.id,
        input_summary={
            "apiKey": "super_secret_apiKey",
            "API-KEY": "plain_secret_API_KEY",
            "access_token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "clientSecret": "plain_clientSecret_val",
            "private-key": "plain_private-key_val",
            "password": "plain_password_val",
            "credentials": "plain_credentials_val",
            "authorization": "Bearer token123",
            "primary_key": 1001,
            "token_count": 45,
            "prompt_tokens": 30,
            "completion_tokens": 15,
            "system_instruction": "Confidential AI instructions",
        },
        output_summary={
            "result": f"Generated via {google_api_key} and {openai_key}",
            "full_prompt": "Secret prompt template",
        },
        error_info={
            "message": f"Exception connecting to service with key {google_api_key}",
        },
    )

    resp = client.get(f"/api/v1/traces/{trace.id}/steps?format=flat", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    step_data = resp.json()["steps"][0]

    # Verify input_summary sanitization
    in_sum = step_data["input_summary"]
    assert in_sum["apiKey"] == "[REDACTED]"
    assert in_sum["API-KEY"] == "[REDACTED]"
    assert in_sum["access_token"] == "[REDACTED]"
    assert in_sum["clientSecret"] == "[REDACTED]"
    assert in_sum["private-key"] == "[REDACTED]"
    assert in_sum["password"] == "[REDACTED]"
    assert in_sum["credentials"] == "[REDACTED]"
    assert in_sum["authorization"] == "[REDACTED]"
    assert in_sum["system_instruction"] == "[REDACTED_SYSTEM_PROMPT]"

    # Non-sensitive keys remain intact
    assert in_sum["primary_key"] == 1001
    assert in_sum["token_count"] == 45
    assert in_sum["prompt_tokens"] == 30
    assert in_sum["completion_tokens"] == 15

    # Verify output_summary sanitization
    out_sum = step_data["output_summary"]
    assert google_api_key not in out_sum["result"]
    assert openai_key not in out_sum["result"]
    assert "[REDACTED_API_KEY]" in out_sum["result"]
    assert out_sum["full_prompt"] == "[REDACTED_SYSTEM_PROMPT]"

    # Verify error_info sanitization
    err_inf = step_data["error_info"]
    assert google_api_key not in err_inf["message"]
    assert "[REDACTED_API_KEY]" in err_inf["message"]


# ==============================================================================
# SECTION 6: STRICT TENANT ISOLATION TESTS
# ==============================================================================

def test_strict_tenant_isolation_cross_tenant_rejection(db: Session):
    tenant_a, user_a, token_a = create_tenant_and_user(db, role="tenant_admin", prefix="iso_a")
    tenant_b, user_b, token_b = create_tenant_and_user(db, role="tenant_admin", prefix="iso_b")

    # Tenant A creates trace and step
    trace_a = create_trace(db, tenant_a.id, trigger_type="inbound_message")
    step_a = create_step(db, tenant_a.id, trace_a.id, step_name="Step Tenant A")

    # Tenant B creates trace
    trace_b = create_trace(db, tenant_b.id, trigger_type="task_execution")

    # 1. Tenant B tries to get Tenant A's trace -> 404 NOT FOUND
    resp_cross_trace = client.get(
        f"/api/v1/traces/{trace_a.id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_cross_trace.status_code == 404
    assert resp_cross_trace.json()["detail"] == "Execution trace not found"

    # 2. Tenant B tries to get Tenant A's steps -> 404 NOT FOUND
    resp_cross_steps = client.get(
        f"/api/v1/traces/{trace_a.id}/steps",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_cross_steps.status_code == 404

    # 3. Tenant B tries to get Tenant A's summary -> 404 NOT FOUND
    resp_cross_sum = client.get(
        f"/api/v1/traces/{trace_a.id}/summary",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_cross_sum.status_code == 404

    # 4. Tenant B lists traces: sees ONLY trace_b, NEVER trace_a
    resp_list_b = client.get(
        "/api/v1/traces",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_list_b.status_code == 200
    items_b = resp_list_b.json()["items"]
    assert len(items_b) == 1
    assert items_b[0]["id"] == str(trace_b.id)
    assert str(trace_a.id) not in [item["id"] for item in items_b]


# ==============================================================================
# SECTION 7: RBAC ROLE PERMISSIONS & ACCESS CONTROL
# ==============================================================================

def test_rbac_role_permissions(db: Session):
    tenant = Tenant(
        id=uuid.uuid4(),
        name="RBAC Tracing Tenant",
        slug=f"rbac-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    if hasattr(db, "register_tenant"):
        db.register_tenant(tenant.id)

    trace = create_trace(db, tenant.id)

    # 1. Allowed roles
    allowed_roles = ["tenant_admin", "admin", "tenant_owner", "owner", "operator", "auditor", "developer", "superadmin"]
    for role in allowed_roles:
        u = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name=f"User {role}",
            email=f"{role}-{uuid.uuid4().hex[:6]}@test.com",
            role=role,
            status="active",
        )
        db.add(u)
        db.commit()
        token = create_access_token(user_id=u.id, tenant_id=tenant.id, role=role)

        resp = client.get("/api/v1/traces", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, f"Role '{role}' should be allowed to read traces"

    # 2. Denied roles (e.g. guest, customer, restricted_user)
    denied_roles = ["guest", "customer", "restricted_user"]
    for role in denied_roles:
        u_denied = User(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name=f"Denied User {role}",
            email=f"{role}-{uuid.uuid4().hex[:6]}@test.com",
            role=role,
            status="active",
        )
        db.add(u_denied)
        db.commit()
        token_denied = create_access_token(user_id=u_denied.id, tenant_id=tenant.id, role=role)

        resp_denied = client.get("/api/v1/traces", headers={"Authorization": f"Bearer {token_denied}"})
        assert resp_denied.status_code == 403, f"Role '{role}' must be denied access to traces"
        assert "lacks tracing read permissions" in resp_denied.json()["detail"]

    # 3. Dynamic permission override:
    # A user with denied role ("customer") is explicitly granted permission "traces:read"
    perm = Permission(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        action="traces:read",
        resource="traces",
        effect="allow",
    )
    db.add(perm)
    db.commit()

    u_override = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Customer With Perm",
        email=f"cust-perm-{uuid.uuid4().hex[:6]}@test.com",
        role="customer",
        status="active",
    )
    db.add(u_override)
    db.commit()
    token_override = create_access_token(user_id=u_override.id, tenant_id=tenant.id, role="customer")

    resp_override = client.get("/api/v1/traces", headers={"Authorization": f"Bearer {token_override}"})
    assert resp_override.status_code == 200, "User with explicit 'traces:read' permission should be permitted"

    # 4. Unauthenticated request: missing header
    resp_unauth = client.get("/api/v1/traces")
    assert resp_unauth.status_code == 401
