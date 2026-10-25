import os
import sys
import subprocess
import re
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.abspath("."))
from packages.core.config import settings

def mask_db_url(url: str) -> str:
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:******@", url)

def run_lifecycle_test():
    print("=" * 80)
    print("ALEMBIC LIFECYCLE VERIFICATION ON FRESH COPY OF LIVE DB")
    print("=" * 80)

    # Base URL for maintenance
    live_url = settings.database_url
    maint_url = re.sub(r"/ai_employee$", "/postgres", live_url)
    engine_maint = create_engine(maint_url, isolation_level="AUTOCOMMIT")

    scratch_db_name = "ai_employee_lifecycle_scratch"
    print(f"Creating fresh scratch copy '{scratch_db_name}' from template 'ai_employee'...")
    with engine_maint.connect() as conn:
        conn.execute(text(f"""
            SELECT pg_terminate_backend(pid) 
            FROM pg_stat_activity 
            WHERE datname = '{scratch_db_name}' AND pid <> pg_backend_pid();
        """))
        conn.execute(text(f"DROP DATABASE IF EXISTS {scratch_db_name};"))
        
        conn.execute(text("""
            SELECT pg_terminate_backend(pid) 
            FROM pg_stat_activity 
            WHERE datname = 'ai_employee' AND pid <> pg_backend_pid();
        """))
        conn.execute(text(f"CREATE DATABASE {scratch_db_name} TEMPLATE ai_employee;"))
    print("Fresh copy created successfully via TEMPLATE.")

    scratch_url = re.sub(r"/ai_employee$", f"/{scratch_db_name}", live_url)
    scratch_engine = create_engine(scratch_url, isolation_level="AUTOCOMMIT")

    # Inspect initial state of the copy (matching live state)
    print("\n--- INITIAL STATE OF SCRATCH COPY (MATCHING LIVE DB) ---")
    with scratch_engine.connect() as conn:
        curr_v = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchall()
        facts_exists = conn.execute(text("SELECT to_regclass('public.facts');")).scalar()
        facts_cnt = conn.execute(text("SELECT count(*) FROM facts;")).scalar() if facts_exists else None
        app_cols = [r[0] for r in conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'approvals' AND column_name IN ('token', 'expires_at');
        """)).fetchall()]
        print(f"Current Alembic version : {curr_v}")
        print(f"Table 'facts' exists     : {facts_exists is not None}")
        print(f"Table 'facts' row count  : {facts_cnt}")
        print(f"Approvals new columns   : {app_cols}")

    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["DATABASE_URL"] = scratch_url

    # Step 1A: Show how upgrade behaves WITHOUT dropping the pre-existing empty facts table
    print("\n--- STEP 1A: ATTEMPTING UPGRADE WITHOUT PRE-DROPPING 'facts' ---")
    res_direct = subprocess.run(
        [".venv\\Scripts\\alembic.exe", "-c", "alembic.ini", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    print("Exit code:", res_direct.returncode)
    if "already exists" in res_direct.stderr or "DuplicateTable" in res_direct.stderr:
        print("Observed Expected Error: Table 'facts' already exists before e6f7a8b9c0d1 could create it.")
        # Check what got applied: d5e6f7a8b9c0 applied, halted at e6f7a8b9c0d1
        with scratch_engine.connect() as conn:
            v_mid = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchall()
            print(f"Version after partial upgrade: {v_mid}")
    else:
        print("Output:", res_direct.stdout, res_direct.stderr)

    # Step 1B: Real Procedure: verify count=0, drop empty facts table, complete upgrade
    print("\n--- STEP 1B: REAL PROCEDURE (VERIFY COUNT=0, DROP, UPGRADE) ---")
    with scratch_engine.connect() as conn:
        f_count = conn.execute(text("SELECT count(*) FROM facts;")).scalar()
        assert f_count == 0, f"Cannot drop facts table: row count is {f_count} (must be 0)"
        print(f"Verified 'facts' row count is {f_count}. Safely dropping empty table...")
        conn.execute(text("DROP TABLE facts CASCADE;"))
        print("Empty 'facts' table dropped.")

    res_proc_up = subprocess.run(
        [".venv\\Scripts\\alembic.exe", "-c", "alembic.ini", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    print("Exit code:", res_proc_up.returncode)
    assert res_proc_up.returncode == 0, f"Upgrade failed: {res_proc_up.stderr}"

    with scratch_engine.connect() as conn:
        v_head = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchall()
        facts_ok = conn.execute(text("SELECT to_regclass('public.facts');")).scalar()
        app_cols_ok = [r[0] for r in conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'approvals' AND column_name IN ('token', 'expires_at');
        """)).fetchall()]
        print(f"After Real Upgrade : version={v_head}")
        print(f"Table 'facts'      : {facts_ok is not None}")
        print(f"Approvals columns  : {app_cols_ok}")
        assert ('e6f7a8b9c0d1',) in v_head, "Version must be at head e6f7a8b9c0d1"
        assert 'token' in app_cols_ok and 'expires_at' in app_cols_ok, "Approvals columns missing"

    # Step 2: DOWNGRADE back to c4d5e6f7a8b9
    print("\n--- STEP 2: DOWNGRADE TO c4d5e6f7a8b9 ---")
    res_down = subprocess.run(
        [".venv\\Scripts\\alembic.exe", "-c", "alembic.ini", "downgrade", "c4d5e6f7a8b9"],
        env=env,
        capture_output=True,
        text=True,
    )
    print("Exit code:", res_down.returncode)
    assert res_down.returncode == 0, f"Downgrade failed: {res_down.stderr}"

    with scratch_engine.connect() as conn:
        v_down = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchall()
        facts_down = conn.execute(text("SELECT to_regclass('public.facts');")).scalar()
        app_cols_down = [r[0] for r in conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'approvals' AND column_name IN ('token', 'expires_at');
        """)).fetchall()]
        print(f"After Downgrade   : version={v_down}")
        print(f"Table 'facts'     : {facts_down is not None} (expected False)")
        print(f"Approvals columns : {app_cols_down} (expected empty)")
        assert ('c4d5e6f7a8b9',) in v_down
        assert facts_down is None
        assert len(app_cols_down) == 0

    # Step 3: UPGRADE AGAIN to head
    print("\n--- STEP 3: RE-UPGRADE TO HEAD ---")
    res_up_again = subprocess.run(
        [".venv\\Scripts\\alembic.exe", "-c", "alembic.ini", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    print("Exit code:", res_up_again.returncode)
    assert res_up_again.returncode == 0, f"Re-upgrade failed: {res_up_again.stderr}"

    with scratch_engine.connect() as conn:
        v_final = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchall()
        facts_final = conn.execute(text("SELECT to_regclass('public.facts');")).scalar()
        app_cols_final = [r[0] for r in conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'approvals' AND column_name IN ('token', 'expires_at');
        """)).fetchall()]
        print(f"After Re-Upgrade  : version={v_final}")
        print(f"Table 'facts'     : {facts_final is not None}")
        print(f"Approvals columns : {app_cols_final}")
        assert ('e6f7a8b9c0d1',) in v_final
        assert facts_final is not None
        assert 'token' in app_cols_final and 'expires_at' in app_cols_final

    print("\n" + "=" * 80)
    print("LIFECYCLE TEST COMPLETED SUCCESSFULLY ON COPY")
    print("=" * 80)

if __name__ == "__main__":
    run_lifecycle_test()
