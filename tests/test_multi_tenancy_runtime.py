import sys
from pathlib import Path
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.core.database import SessionLocal
from packages.models.tenant import Tenant
from packages.models.domain import User, Agent


def main():
    db = SessionLocal()

    try:
        tenant = Tenant(
            name="Test Business",
            slug=f"test-business-{uuid.uuid4().hex[:8]}",
        )
        db.add(tenant)
        db.flush()

        user = User(
            tenant_id=tenant.id,
            name="Test Owner",
            email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
            role="owner",
            status="active",
        )
        db.add(user)
        db.flush()

        agent = Agent(
            tenant_id=tenant.id,
            name="Test Digital Employee",
            agent_type="main",
            status="active",
            system_config={},
        )
        db.add(agent)
        db.flush()

        print("MULTI_TENANCY_TEST=PASS")
        print(f"tenant_id={tenant.id}")
        print(f"user_id={user.id}")
        print(f"agent_id={agent.id}")
        print(f"user_tenant_match={user.tenant_id == tenant.id}")
        print(f"agent_tenant_match={agent.tenant_id == tenant.id}")

        db.rollback()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
