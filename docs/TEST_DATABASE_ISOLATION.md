# Test Database Isolation & Safety Architecture

This document describes the architectural isolation separating the live application database (`ai_employee`) from the automated test database (`ai_employee_test`).

---

## 1. Architecture Overview

```mermaid
flowchart LR
    subgraph Host["Host Environment (Developer / Pytest / CI)"]
        direction TB
        AppProc["FastAPI Application & Dashboards"]
        TestProc["Pytest Test Runner"]
    end

    subgraph Postgres["PostgreSQL Server (127.0.0.1:5433)"]
        direction TB
        AppDB[("ai_employee\n[PROTECTED APPLICATION DB]\n- Production & Dev Business Data\n- Protected by Safety Guard\n- Zero DDL drop tests allowed")]
        TestDB[("ai_employee_test\n[ISOLATED TEST DB]\n- Ephemeral Pytest Fixtures\n- Alembic Upgrade & Downgrade\n- Zero application impact")]
    end

    AppProc -->|"DATABASE_URL\n(defaults to ai_employee)"| AppDB
    TestProc -->|"TEST_DATABASE_URL\n(isolated ai_employee_test via conftest.py)"| TestDB
```

---

## 2. Protected Application Database vs Isolated Test Database

| Attribute | Application Database (`ai_employee`) | Isolated Test Database (`ai_employee_test`) |
| :--- | :--- | :--- |
| **Purpose** | Business data, multi-tenant records, development server | Automated Pytest suites, Alembic schema/migration cycles |
| **Port / Host** | `127.0.0.1:5433` (Docker: `postgres:5432`) | `127.0.0.1:5433` (Docker: `postgres:5432`) |
| **Owner** | `ai_employee` | `ai_employee` |
| **Protection** | **Protected by runtime Safety Guard**. DDL drops prohibited | Sandboxed; safe for `command.downgrade()` cycles |

---

## 3. The Runtime Safety Guard (`packages/core/safety_guard.py`)

To prevent accidental execution of tests or destructive migration cycles against `ai_employee`, the platform enforces a **live SQL query check** before executing any test or migration:

```python
actual_db = verify_test_database_isolation(engine)
```

- **Live Server Query**: Executes `SELECT current_database()` on the active connection.
- **Immediate Abort**: If the active database is `ai_employee`, `ai_employee_prod`, or lacks a `_test` suffix, a `RuntimeError` is raised immediately before any DDL or query execution.

---

## 4. Configuration & Usage

### A. Automatic Resolution (Default)
When executing Pytest:
1. `tests/conftest.py` automatically detects the connection topology from `settings.database_url`.
2. It substitutes the database name with `ai_employee_test` via `settings.effective_test_database_url`.
3. It rebinds the SQLAlchemy `engine` and `SessionLocal` to `ai_employee_test`.
4. It executes the live Safety Guard query to guarantee isolation before running any test.

### B. Custom Override (Optional)
To point to an external or custom test instance:
```bash
# In your local environment (never commit real credentials to Git)
export TEST_DATABASE_URL="postgresql+psycopg://ai_employee:your_password@127.0.0.1:5433/ai_employee_test"
```

### C. Running Tests Safely
```bash
# Run isolated unit tests and safety guard verification
.venv\Scripts\pytest.exe tests/test_database_isolation_guard.py -v

# Run schema and migration tests in isolation
.venv\Scripts\pytest.exe tests/test_phase2_batch1_execution_tracing_schema.py -v
```
