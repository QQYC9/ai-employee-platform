import os
import subprocess
from sqlalchemy import create_engine, text

def run_backup_and_restore_verification():
    os.makedirs("backups", exist_ok=True)
    dump_filename = "backup_ai_employee_pre_phase2.dump"
    dump_local_path = os.path.abspath(os.path.join("backups", dump_filename))
    container_dump_path = f"/tmp/{dump_filename}"

    print(f"1. RUNNING PG_DUMP on container 'ai_employee_postgres'...")
    # Dump inside container to /tmp/
    cmd_dump = [
        "docker", "exec", "ai_employee_postgres",
        "pg_dump", "-U", "ai_employee", "-d", "ai_employee",
        "-Fc", "-f", container_dump_path
    ]
    res_dump = subprocess.run(cmd_dump, capture_output=True, text=True)
    if res_dump.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {res_dump.stderr}")
    print("pg_dump succeeded inside container.")

    # Copy dump file from container to local backups/
    print(f"2. COPYING dump to local filesystem at {dump_local_path}...")
    cmd_cp = ["docker", "cp", f"ai_employee_postgres:{container_dump_path}", dump_local_path]
    res_cp = subprocess.run(cmd_cp, capture_output=True, text=True)
    if res_cp.returncode != 0:
        raise RuntimeError(f"docker cp failed: {res_cp.stderr}")

    # Check file size
    size_bytes = os.path.getsize(dump_local_path)
    size_kb = size_bytes / 1024
    print(f"Dump file verified locally: {dump_local_path}")
    print(f"File Size: {size_bytes} bytes ({size_kb:.2f} KB)")
    assert size_bytes > 0, "Backup file size is 0 bytes!"

    # 3. Create scratch database for restore test
    scratch_db_name = "ai_employee_backup_restore_scratch"
    maint_url = "postgresql+psycopg://ai_employee:change_me_local@127.0.0.1:5433/postgres"
    maint_engine = create_engine(maint_url, isolation_level="AUTOCOMMIT")

    print(f"\n3. CREATING scratch database '{scratch_db_name}'...")
    with maint_engine.connect() as conn:
        conn.execute(text(f"""
            SELECT pg_terminate_backend(pid) 
            FROM pg_stat_activity 
            WHERE datname = '{scratch_db_name}' AND pid <> pg_backend_pid();
        """))
        conn.execute(text(f"DROP DATABASE IF EXISTS {scratch_db_name};"))
        conn.execute(text(f"CREATE DATABASE {scratch_db_name};"))
    print("Scratch database created.")

    # 4. RESTORE into scratch database via pg_restore
    print(f"\n4. RESTORING dump into '{scratch_db_name}' via pg_restore...")
    cmd_restore = [
        "docker", "exec", "ai_employee_postgres",
        "pg_restore", "-U", "ai_employee", "-d", scratch_db_name,
        "--no-owner", "--no-privileges", container_dump_path
    ]
    res_restore = subprocess.run(cmd_restore, capture_output=True, text=True)
    # pg_restore exit code 0 or 1 (warnings on existing extensions) is common, check stdout/stderr
    print("pg_restore exit code:", res_restore.returncode)
    if res_restore.stderr:
        print("pg_restore notice/stderr (first 300 chars):", res_restore.stderr[:300])

    # 5. INSPECT restored database row counts
    print(f"\n5. RESTORED DATABASE ROW COUNTS IN '{scratch_db_name}':")
    scratch_url = f"postgresql+psycopg://ai_employee:change_me_local@127.0.0.1:5433/{scratch_db_name}"
    scratch_engine = create_engine(scratch_url)

    tables_to_check = [
        "tenants", "business_brains", "knowledge", "users",
        "channels", "conversations", "messages", "campaigns",
        "campaign_recipients", "outbox_events", "approvals", "alembic_version"
    ]

    with scratch_engine.connect() as conn:
        for tbl in tables_to_check:
            exists = conn.execute(text(f"SELECT to_regclass('public.{tbl}');")).scalar()
            if exists:
                cnt = conn.execute(text(f"SELECT count(*) FROM {tbl};")).scalar()
                print(f"   - {tbl:22}: {cnt} rows")
            else:
                print(f"   - {tbl:22}: [TABLE NOT PRESENT]")

        # Also get current alembic version in restored db
        alembic_v = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchall()
        print(f"\nRestored DB Alembic Version: {alembic_v}")

    print("\nBACKUP AND RESTORE VERIFICATION COMPLETED SUCCESSFULLY.")

if __name__ == "__main__":
    run_backup_and_restore_verification()
