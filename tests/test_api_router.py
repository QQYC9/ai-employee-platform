import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from apps.agent.main import app


client = TestClient(app)


def test_api_router_is_registered():
    endpoints = [
        "/api/v1/auth/status",
        "/api/v1/tenants/status",
        "/api/v1/agents/status",
        "/api/v1/tasks/status",
        "/api/v1/customers/status",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 200


def test_auth_router():
    response = client.get("/api/v1/auth/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "authentication",
    }


def test_tenants_router():
    response = client.get("/api/v1/tenants/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "tenants",
    }


def test_agents_router():
    response = client.get("/api/v1/agents/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "agents",
    }


def test_tasks_router():
    response = client.get("/api/v1/tasks/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "tasks",
    }


def test_customers_router():
    response = client.get("/api/v1/customers/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "customers",
    }
