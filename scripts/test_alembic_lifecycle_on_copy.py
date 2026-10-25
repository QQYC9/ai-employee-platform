import os
import subprocess
from sqlalchemy import create_engine, text

def run_lifecycle_test():
    base_url = "postgresql+psycopg://ai_employee:change_me_local@127.0.0.1:5433/postgres"
    engine_maint = create_engine(base_url, isolation_level="AUTOCOMMIT")

    scratch_db_name = "ai_employee_lifecycle_scratch"
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
        try:
            print(f"Creating copy database {scratch_db_name} from template ai_employee...")
            conn.execute(text(f"CREATE DATABASE {scratch_db_name} TEMPLATE ai_employee;"))
            print("Copy created successfully via TEMPLATE.")
        except Exception as exc:
            print(f"Template copy failed ({exc}); falling back to standard CREATE DATABASE...")
            conn.execute(text(f"CREATE DATABASE {scratch_db_name};"))

    scratch_url = f"postgresql+psycopg://ai_employee:change_me_local@127.0.0.1:5433/{scratch_db_name}"
    
    scratch_engine = create_engine(scratch_url, isolation_level="AUTOCOMMIT")
    with scratch_engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS facts CASCADE;"))
        conn.execute(text("UPDATE alembic_version SET version_num = 'c4d5e6f7a8b9';"))
        curr_v = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchall()
        print(f"Scratch DB prepared. Current Alembic version: {curr_v}")

    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["DATABASE_URL"] = scratch_url

    # 1. UPGRADE
    print("\n--- 1. RUNNING ALEMBIC UPGRADE ---")
    res_up1 = subprocess.run([".venv\\Scripts\\alembic.exe", "-c", "alembic.ini", "-x", f"data_url={scratch_url}", "upgrade", "head"], env=env, capture_output=True, text=True)
    print("STDOUT:", res_up1.stdout)
    if res_up1.stderr:
        print("STDERR:", res_up1.stderr)
    print("Exit code:", res_up1.returncode)

    with scratch_engine.connect() as conn:
        v1 = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchall()
        facts_exists1 = conn.execute(text("SELECT to_regclass('public.facts');")).scalar()
        print(f"After Upgrade 1: version={v1}, facts_table_exists={facts_exists1 is not None}")

    # 2. DOWNGRADE
    print("\n--- 2. RUNNING ALEMBIC DOWNGRADE ---")
    res_down = subprocess.run([".venv\\Scripts\\alembic.exe", "-c", "alembic.ini", "downgrade", "c4d5e6f7a8b9"], env=env, capture_output=True, text=True)
    print("STDOUT:", res_down.stdout)
    if res_down.stderr:
        print("STDERR:", res_down.stderr)
    print("Exit code:", res_down.returncode)

    with scratch_engine.connect() as conn:
        v2 = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchall()
        facts_exists2 = conn.execute(text("SELECT to_regclass('public.facts');")).scalar()
        print(f"After Downgrade: version={v2}, facts_table_exists={facts_exists2 is not None}")

    # 3. UPGRADE AGAIN
    print("\n--- 3. RUNNING ALEMBIC UPGRADE AGAIN ---")
    res_up2 = subprocess.run([".venv\\Scripts\\alembic.exe", "-c", "alembic.ini", "upgrade", "head"], env=env, capture_output=True, text=True)
    print("STDOUT:", res_up2.stdout)
    if res_up2.stderr:
        print("STDERR:", res_up2.stderr)
    print("Exit code:", res_up2.returncode)

    with scratch_engine.connect() as conn:
        v3 = conn.execute(text("SELECT version_num FROM alembic_version;")).fetchall()
        facts_exists3 = conn.execute(text("SELECT to_regclass('public.facts');")).scalar()
        print(f"After Upgrade 2: version={v3}, facts_table_exists={facts_exists3 is not None}")

if __name__ == "__main__":
    run_lifecycle_test()
