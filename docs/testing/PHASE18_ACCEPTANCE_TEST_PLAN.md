# Phase 18 — Staging Functional Acceptance Test Plan

**Target Environment:** Local Staging (`ai-employee-platform-staging`)  
**Base URL:** `http://127.0.0.1:8001`  
**Target Database:** `ai_employee_staging` (isolated container `ai_employee_staging_postgres`)  
**Git Branch:** `checkpoint/phase-12-knowledge-base`  
**Execution Date:** 2026-10-18  

---

## 1. Objective and Scope

The objective of this plan is to conduct an end-to-end functional and security acceptance audit of the AI Employee Platform running in the local Staging environment. This testing validates platform readiness for subsequent staging and VPS deployment without modifying application code, restarting running containers, or altering development data.

### Environment Safety Constraints
1. **Target Exclusivity:** All HTTP requests must target `http://127.0.0.1:8001`. The development environment on port `8000` / `5433` must remain completely untouched.
2. **Database Guard:** All database inspections and synthetic test data seeding must be verified against `ai_employee_staging`. If the connection string or database name is not `ai_employee_staging`, execution must immediately halt.
3. **No External Dispatches:** No real emails, WhatsApp messages, or billable LLM API requests may be triggered. Synthetic fixtures, mocks, and local test payloads are used exclusively.
4. **Data Isolation:** All seeded records must use the distinct prefix `staging-test-*` and domains `@staging.local` to allow safe, targeted verification and teardown.

---

## 2. Test Architecture and Prerequisites

```
[Test Runner / Host]
       |
       +---> HTTP Requests (127.0.0.1:8001) ---> [ai_employee_staging_agent]
       |                                                    |
       +---> docker compose exec agent                      +---> [ai_employee_staging_postgres:5432]
             (Read-only DB verifications & seeding)         |     (Database: ai_employee_staging)
                                                            +---> [ai_employee_staging_redis:6379]
```

### Pre-execution Checklist
- [x] Staging containers active: `ai_employee_staging_agent`, `ai_employee_staging_postgres`, `ai_employee_staging_redis`.
- [x] Development containers active and unaffected: `ai_employee_agent`, `ai_employee_postgres`, `ai_employee_redis`.
- [x] Staging database migrated to Alembic head `f6a7b8c9d0e1` (42 tables present).
- [x] API port verified: `127.0.0.1:8001` listening and responsive.

---

## 3. Acceptance Test Matrix

| ID | Domain | Test Name | Method | Type | Risk Level | Expected Result |
| :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| **TC-A1** | Health | API Health Check | `GET /health` | Read-only | High | HTTP 200, `{"status":"healthy"}` |
| **TC-A2** | Health | Root Status Check | `GET /` | Read-only | Medium | HTTP 200, `status: "ok"`, `version: "0.1.0"` |
| **TC-A3** | Health | OpenAPI Schema | `GET /openapi.json` | Read-only | High | HTTP 200, valid JSON schema with 120 paths |
| **TC-A4** | Config | Staging Environment Guard | Container inspect | Read-only | Critical | `ENVIRONMENT=staging`, `is_dev_auth_allowed=False` |
| **TC-A5** | Config | Database Isolation Guard | DB query | Read-only | Critical | Connected DB is `ai_employee_staging`, zero overlap with dev |
| **TC-B1** | Auth | Unauthenticated Rejection | `GET /api/v1/me` | Read-only | High | HTTP 401 Unauthorized, `WWW-Authenticate: Bearer` |
| **TC-B2** | Auth | Dev Header Rejection | `GET /api/v1/me` (`X-User-ID`) | Read-only | Critical | HTTP 401 `strictly forbidden in this environment` |
| **TC-B3** | Auth | Invalid Login Rejection | `POST /api/v1/auth/login` | Read-only | High | HTTP 401 Unauthorized, `Invalid email or password` |
| **TC-B4** | Auth | Test User Login | `POST /api/v1/auth/login` | Write (Seed) | Critical | HTTP 200 with signed JWT access and refresh tokens |
| **TC-B5** | Auth | Authenticated User Identity | `GET /api/v1/me` (Bearer) | Read-only | High | HTTP 200, returns authenticated user_id and tenant_id |
| **TC-B6** | Auth | Token Refresh Cycle | `POST /api/v1/auth/refresh` | Read-only | Medium | HTTP 200, returns new access token |
| **TC-C1** | Multi-Tenancy | Cross-Tenant Task Isolation | `GET /api/v1/tasks/{id_beta}` | Write (Seed) | Critical | HTTP 404 Not Found (no cross-tenant leakage) |
| **TC-C2** | Multi-Tenancy | Cross-Tenant Admin Scoping | `GET /api/v1/admin/tenant/dashboard` | Write (Seed) | Critical | HTTP 403 Forbidden for cross-tenant access |
| **TC-C3** | Multi-Tenancy | Cross-Tenant Brain Scoping | `GET /api/v1/me/brain` | Read-only | Critical | HTTP 200, returns caller's brain only |
| **TC-D1** | Tasks | Task Creation Flow | `POST /api/v1/tasks` | Write | High | HTTP 201 Created with status `pending` |
| **TC-D2** | Tasks | Tenant-Scoped Task List | `GET /api/v1/tasks` | Read-only | High | HTTP 200, returns only tasks belonging to caller |
| **TC-D3** | Tasks | Invalid Task Transition | Task lifecycle call | Write | Medium | Rejects invalid state transitions with appropriate error |
| **TC-E1** | Outbox | Outbox Event Enqueueing | Service enqueue | Write | High | Outbox event created with status `PENDING` |
| **TC-E2** | Outbox | Worker Event Claim & Process | Embedded worker | Write | High | Outbox event transitions to `PROCESSED` via row lock |
| **TC-E3** | Outbox | Idempotency Key Handling | Idempotent POST | Write | High | Duplicate request with same key returns cached response |
| **TC-F1** | Workflows | Proactive Workflow Creation | `POST /api/v1/workflows` | Write | Medium | HTTP 201 Created with status `active` |
| **TC-F2** | Workflows | Workflow Event Trigger | `POST /api/v1/workflows/events` | Write | Medium | HTTP 200/201, event recorded and matched |
| **TC-F3** | Workflows | Self-Dev Request Creation | `POST /api/v1/self-development/requests` | Write | Medium | HTTP 201 Created with problem statement |
| **TC-G1** | Security | No Stack Trace Leakage | Malformed JSON / 404 | Read-only | High | Clean JSON error response, zero internal trace |
| **TC-G2** | Security | Pydantic Schema Validation | `POST /api/v1/tasks` (empty) | Read-only | High | HTTP 422 Unprocessable Content with field errors |
| **TC-G3** | Security | Rate Limiting Enforcement | Rapid login attempts | Read-only | High | HTTP 429 Too Many Requests upon threshold breach |

---

## 4. Test Data Strategy & Isolation

### Synthetic Fixtures
- **Tenant Alpha:**
  - Name: `Staging Acceptance Alpha`
  - Slug: `staging-test-alpha`
  - Owner Email: `owner-alpha@staging.local`
- **Tenant Beta:**
  - Name: `Staging Acceptance Beta`
  - Slug: `staging-test-beta`
  - Owner Email: `owner-beta@staging.local`

### Teardown and Cleanup
All synthetic entities are tagged with `slug LIKE 'staging-test-%'` and emails `@staging.local`. A dedicated cleanup procedure purges only records matching this explicit filter from `ai_employee_staging` upon test completion, ensuring the database returns to a pristine state.
