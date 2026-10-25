import os
import sys
import subprocess
import re
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.abspath("."))
from packages.core.config import settings

def mask_db_url(url: str) -> str:
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:******@", url)

def execute_live_upgrade():
    print("=" * 80)
    print("STEP A.3: EXECUTING LIVE DATABASE RECONCILIATION & ALEMBIC UPGRADE")
    print("=" * 80)

    live_url = settings.database_url
    print(f"Targeting Live DB: {mask_db_url(live_url)}")

    engine = create_engine(live_url, isolation_level="AUTOCOMMIT")

    tables_to_check = [
        "tenants", "business_brains", "knowledge", "users",
        "channels", "conversations", "messages", "campaigns",
        "campaign_recipients", "outbox_events", "approvals"
    ]

    # 1. Snapshot row counts BEFORE
    print("\n1. SNAPSHOT TABLE ROW COUNTS BEFORE UPGRADE:")
    counts_before = {}
    with engine.connect() as conn:
        for tbl in tables_to_check:
            cnt = conn.execute(text(f"SELECT count(*) FROM {tbl};")).scalar()
            counts_before[tbl] = cnt
            print(f"   - {tbl:22}: {cnt} rows")

        # 2. Re-check facts table
        print("\n2. RE-CHECKING 'facts' TABLE ON LIVE DB:")
        facts_exists = conn.execute(text("SELECT to_regclass('public.facts');")).scalar()
        print(f"   Table 'facts' exists: {facts_exists is not None}")
        if facts_exists:
            facts_count = conn.execute(text("SELECT count(*) FROM facts;")).scalar()
            print(f"   Table 'facts' row count: {facts_count}")
            assert facts_count == 0, f"ABORT: 'facts' table on live DB is NOT empty (count={facts_count})!"

        # 3. Drop empty facts table
        print("\n3. DROPPING EMPTY 'facts' TABLE FROM LIVE DB:")
        conn.execute(text("DROP TABLE IF EXISTS facts CASCADE;"))
        print("   Dropped empty 'facts' table successfully.")

    # 4. Run alembic upgrade head
    print("\n4. RUNNING 'alembic upgrade head' ON LIVE DB:")
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["DATABASE_URL"] = live_url
    res_up = subprocess.run(
        [".venv\\Scripts\\alembic.exe", "-c", "alembic.ini", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    print(res_up.stdout)
    if res_up.stderr:
        print("STDERR:", res_up.stderr)
    print("Exit code:", res_up.returncode)
    assert res_up.returncode == 0, f"Alembic upgrade failed: {res_up.stderr}"

    # 5. Run alembic current
    print("\n5. RUNNING 'alembic current' ON LIVE DB:")
    res_cur = subprocess.run(
        [".venv\\Scripts\\alembic.exe", "-c", "alembic.ini", "current"],
        env=env,
        capture_output=True,
        text=True,
    )
    print(res_cur.stdout)

    # 6. Verify approvals columns and facts table in DB
    print("\n6. VERIFYING SCHEMA UPDATES ON LIVE DB:")
    with engine.connect() as conn:
        app_cols = [r[0] for r in conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'approvals' AND column_name IN ('token', 'expires_at');
        """)).fetchall()]
        print(f"   Approvals new columns : {app_cols}")
        assert 'token' in app_cols and 'expires_at' in app_cols, "Approvals columns not created!"

        facts_now = conn.execute(text("SELECT to_regclass('public.facts');")).scalar()
        print(f"   Table 'facts' in DB   : {facts_now is not None}")
        assert facts_now is not None, "Facts table not created by Alembic!"

        alembic_v = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchall()
        print(f"   Alembic version in DB : {alembic_v}")
        assert ('e6f7a8b9c0d1',) in alembic_v, "Alembic version is not at head!"

    # 7. Compare row counts AFTER upgrade
    print("\n7. VERIFYING ROW COUNTS OF ALL OTHER TABLES ARE UNCHANGED:")
    with engine.connect() as conn:
        all_matched = True
        for tbl in tables_to_check:
            cnt_after = conn.execute(text(f"SELECT count(*) FROM {tbl};")).scalar()
            cnt_before = counts_before[tbl]
            matched = (cnt_after == cnt_before)
            status_str = "MATCHED (UNCHANGED)" if matched else f"MISMATCH! (before={cnt_before}, after={cnt_after})"
            print(f"   - {tbl:22}: {cnt_after:4} rows | {status_str}")
            if not matched:
                all_matched = False
        assert all_matched, "Row count mismatch detected after upgrade!"

    print("\n" + "=" * 80)
    print("LIVE DATABASE ALEMBIC UPGRADE AND RECONCILIATION COMPLETED SUCCESSFULLY")
    print("=" * 80)

if __name__ == "__main__":
    execute_live_upgrade()
