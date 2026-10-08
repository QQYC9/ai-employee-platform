import uuid

from fastapi.testclient import TestClient

from apps.agent.main import app
from packages.core.database import SessionLocal
from packages.models.domain import Task, User
from packages.models.tenant import Tenant


client = TestClient(app)


def create_test_user():
    db = SessionLocal()

    tenant = Tenant(
        name="Task API Test",
        slug=f"task-api-{uuid.uuid4().hex[:8]}",
    )

    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        name="Task API User",
        email=f"task-{uuid.uuid4().hex[:8]}@example.com",
        role="owner",
        status="active",
    )

    db.add(user)
    db.commit()

    user_id = user.id
    tenant_id = tenant.id

    db.close()

    return user_id, tenant_id


def delete_test_tenant(tenant_id):
    db = SessionLocal()

    try:
        tenant = db.get(Tenant, tenant_id)

        if tenant is not None:
            db.delete(tenant)
            db.commit()
    finally:
        db.close()


def test_create_task_api():
    user_id, tenant_id = create_test_user()

    try:
        response = client.post(
            "/api/v1/tasks",
            headers={
                "X-User-ID": str(user_id),
            },
            json={
                "title": "Research competitors",
                "objective": "Research our main competitors",
                "priority": "high",
            },
        )

        assert response.status_code == 201

        data = response.json()

        assert data["title"] == "Research competitors"
        assert data["objective"] == "Research our main competitors"
        assert data["status"] == "pending"
        assert data["priority"] == "high"

    finally:
        delete_test_tenant(tenant_id)


def test_agent_request_creates_task():
    user_id, tenant_id = create_test_user()

    try:
        response = client.post(
            "/api/v1/tasks/request",
            headers={
                "X-User-ID": str(user_id),
            },
            json={
                "request": "Research our main competitors and prepare a report",
            },
        )

        assert response.status_code == 201

        data = response.json()

        assert data["status"] == "pending"
        assert data["objective"] == (
            "Research our main competitors and prepare a report"
        )

    finally:
        delete_test_tenant(tenant_id)


def test_tasks_are_tenant_scoped():
    user_id_a, tenant_id_a = create_test_user()
    user_id_b, tenant_id_b = create_test_user()

    db = SessionLocal()

    try:
        task = Task(
            tenant_id=tenant_id_a,
            title="Private task",
            objective="Private objective",
            status="pending",
            priority="normal",
            plan={},
            result={},
        )

        db.add(task)
        db.commit()

        response = client.get(
            f"/api/v1/tasks/{task.id}",
            headers={
                "X-User-ID": str(user_id_b),
            },
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Task not found"

    finally:
        db.close()
        delete_test_tenant(tenant_id_a)
        delete_test_tenant(tenant_id_b)


def test_list_tasks():
    user_id, tenant_id = create_test_user()

    db = SessionLocal()

    try:
        task = Task(
            tenant_id=tenant_id,
            title="List task",
            objective="List objective",
            status="pending",
            priority="normal",
            plan={},
            result={},
        )

        db.add(task)
        db.commit()

        response = client.get(
            "/api/v1/tasks",
            headers={
                "X-User-ID": str(user_id),
            },
        )

        assert response.status_code == 200

        data = response.json()

        assert len(data) == 1
        assert data[0]["title"] == "List task"

    finally:
        db.close()
        delete_test_tenant(tenant_id)
