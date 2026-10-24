# GEMINI.md — AI Employee Platform Coding Agent Guidelines

This document is the authoritative, persistent operational guide and architectural ground truth for the AI coding agent working in this repository. The agent must consult this context and follow the mandatory operating protocol before and during every engineering task.

---

## A. Project Overview

- **Project**: AI Employee Platform
- **Mission**: A multi-tenant enterprise platform hosting autonomous digital employees (AI Agents) that perform business workflows, manage customer communications across omni-channel connectors (WhatsApp, Telegram, Email, Webhooks), execute structured tools, schedule outbound campaigns, and report to business owners and platform administrators.
- **Key Architectures**: Decoupled multi-tenancy, Transactional Outbox pattern for reliable async delivery, Row-Level/Tenant context isolation, Role-Based Access Control (RBAC), and approval-gated tool execution.
- **Current Milestone**: Phase 4D (Outbound Campaigns & Proactive Notifications) fully implemented and verified.

---

## B. Technology Stack

- **Backend**: Python 3.14, FastAPI, Pydantic v2, SQLAlchemy 2.0 ORM, Alembic migrations.
- **Database & Cache**: PostgreSQL 17 with pgvector, Redis 7 (async task coordination and caching).
- **Security & Crypto**: PyJWT (HS256 access & refresh tokens), AES-256-GCM authenticated encryption for tenant integration secrets.
- **Frontend Dashboards**:
  - `apps/tenant-dashboard`: React 18, Vite 5, TypeScript 5, Tailwind CSS, Lucide React, React Router 6.
  - `apps/admin-dashboard`: React 18, Vite 5, TypeScript 5, Tailwind CSS, Lucide React, React Router 6.
- **Testing**:
  - Backend: `pytest`, `pytest-asyncio`, `httpx`, `fastapi.testclient.TestClient`.
  - Frontend: `vitest`, `@testing-library/react`, `jsdom`, `@testing-library/jest-dom`.
- **Infrastructure**: Docker, Docker Compose, Caddy 2 reverse proxy.

---

## C. Repository Map

```text
d:\AI-Employee-Platform\
├── apps/
│   ├── agent/                 # Main FastAPI backend application (/api/v1)
│   ├── tenant-dashboard/      # Tenant business owner portal (React + Vite + TS)
│   └── admin-dashboard/       # Superadmin platform administration portal
├── packages/
│   ├── models/                # SQLAlchemy domain & tenant models (domain.py, tenant.py)
│   ├── auth/                  # JWT tokens, tenant context, security dependencies
│   ├── core/                  # Configuration, database engine/session, crypto AES-GCM
│   ├── services/              # Business logic (campaigns, channels, approvals, outbox, tasks)
│   ├── connectors/            # WhatsApp Cloud, Telegram, Email, Webhook connectors
│   ├── tools/                 # Tool contracts, registry, sandboxed execution
│   ├── memory/                # Conversation & entity memory extraction services
│   ├── context/               # Dynamic context retriever & builder for agent prompts
│   └── ai_providers/          # Model abstraction (Gemini, OpenRouter, Mock)
├── infrastructure/            # Migrations (alembic), Docker configs, Caddy proxy
├── scripts/                   # Autonomous test runners & operations scripts
├── tests/                     # Comprehensive pytest test suites
└── .agents/                   # Coding agent workspace customizations & skills
```

---

## D. Architecture & Data Flow

1. **Request Lifecycle & Tenant Isolation**:
   - Incoming HTTP requests pass through `get_tenant_context` / `get_current_user` dependencies.
   - JWT tokens encode `user_id`, `tenant_id`, and `role`.
   - Every database query for tenant resources must filter by `tenant_id`. Cross-tenant queries are strictly forbidden.
2. **Decoupled Messaging & Outbox Pattern**:
   - Inbound channel messages are ingested idempotently into `conversations` and `messages`.
   - Outbound messages and external actions are written as `OutboxEvent` records inside the business transaction.
   - `OutboxWorker` claims events via `FOR UPDATE SKIP LOCKED`, dispatches via `ChannelService`, handles exponential backoff on transient errors, and records metrics.
3. **Frontend Dashboard Integration**:
   - Dashboards use Axios/Fetch wrappers (`src/api/client.ts`) passing `Authorization: Bearer <token>`.
   - Admin Dashboard communicates with `/api/v1/admin/*`.
   - Tenant Dashboard communicates with `/api/v1/*` (`/campaigns`, `/channels`, `/agents`, `/tasks`, `/me`).

---

## E. Coding Conventions

- **Python**: Type annotations (`from __future__ import annotations`), PEP 8, Pydantic v2 schemas for API contracts, SQLAlchemy mapped columns (`Mapped[T] = mapped_column(...)`).
- **TypeScript**: Strict types (`interface`, `type`), no implicit `any`, functional components with hooks, RTL Arabic support with Tailwind CSS.
- **Error Handling**: Custom domain exceptions (`CampaignError`, `ApprovalRequiredError`), sanitized client error responses without leaking tracebacks or credentials.
- **Commitments & Diff Integrity**: Preserve existing comments, docstrings, and uncommitted user files. Never perform blind overwrites.

---

## F. Security & Privacy Rules

1. **Tenant Isolation**: Every database write and read must validate `tenant_id`. Never allow a tenant to address or query another tenant's channels, customers, or campaigns.
2. **Secret Management**:
   - Secrets at rest (bot tokens, API keys) must be encrypted using `SecretsEncryptionService` (AES-256-GCM).
   - Sanitized configs mask secrets with `******` before sending to dashboards or logs.
3. **Action & Tool Authorization**:
   - High-impact operations (bulk marketing campaigns, sensitive database changes, external API triggers) require explicit owner approval via `ApprovalService`.
4. **Credential Safety**:
   - Never commit `.env` or production secrets. Test credentials must use ephemeral test-only strings.

---

## G. Verified Development & Testing Commands

All commands are verified in the local Windows environment:

- **Python Environment**: `.venv\Scripts\python.exe`
- **Run Backend Pytest**: `.venv\Scripts\pytest.exe tests/ -v`
- **Run Targeted Channel Tests**:
  `.venv\Scripts\pytest.exe tests/test_phase4d_campaigns_and_proactive_notifications.py -v`
- **Tenant Dashboard Build**:
  `npm --prefix apps/tenant-dashboard run build`
- **Tenant Dashboard Component/E2E Tests**:
  `npm --prefix apps/tenant-dashboard test`
- **Admin Dashboard Build**:
  `npm --prefix apps/admin-dashboard run build`
- **Admin Dashboard Tests**:
  `npm --prefix apps/admin-dashboard test`
- **Autonomous Dashboard Test Suite**:
  `python scripts/test_dashboard_runner.py --suite all`

> [!IMPORTANT]
> When executing pytest test suites that insert Outbox events, temporarily stop the competing background container with `docker stop ai_employee_agent`, run tests, then restart it with `docker start ai_employee_agent`.

---

## H. Testing Strategy

1. **Backend Integration Tests** (`tests/`):
   - Fast execution using local PostgreSQL (`localhost:5433`).
   - Mocks external API gateways while exercising real database transactions, outbox states, and constraints.
2. **Frontend Dashboard Tests** (`apps/*/src/test/`):
   - Run in jsdom via Vitest + React Testing Library.
   - Tests authentication guard, role redirection, API error handling, empty states, modals, and user interactions.
3. **Autonomous Dashboard Testing Skill** (`.agents/skills/autonomous-page-testing/`):
   - Scripted headless page verification producing structured reports in `artifacts/dashboard-reports/`.

---

## I. Agent Operating Protocol (Mandatory Workflow)

Before starting any programming task, the coding agent MUST execute the following sequence:

1. **Context & State Verification**:
   - Read `GEMINI.md` to confirm architectural rules, conventions, and current milestone.
   - Run `git status` to inspect modified and untracked files. Protect existing uncommitted user changes.
2. **Evidence-Based Code Inspection**:
   - Read the real implementation files before assuming behavior from names or documentation.
   - Check API router registrations in `apps/agent/main.py` before claiming an endpoint exists.
3. **Structured Task Planning**:
   - Formulate a clear, incremental step-by-step plan.
   - For complex changes, propose the plan and identify potential risks before writing code.
4. **Minimal & Safe Code Edits**:
   - Implement focused modifications using file replacement or targeted writes.
   - Preserve unrelated code, comments, and public contracts.
5. **Autonomous Verification**:
   - For backend changes: run relevant pytest suites.
   - For UI/Dashboard changes: execute `npm run build` and run autonomous page tests.
   - Never declare success without real command output evidence.
6. **Context Maintenance**:
   - If durable architectural facts or commands change, update `GEMINI.md`.

---

## J. Current Project State

- **Active Branch**: `checkpoint/phase-12-knowledge-base`
- **Completed & Verified Milestones**:
  - Phase 4C: Omni-channel connectors (Telegram, WhatsApp, Webhooks), message routing, secret encryption (56/56 tests passing).
  - Phase 4D: Outbound Campaigns & Proactive Notifications, Lifecycle management, audience filtering, OutboxWorker dispatch, Campaigns Dashboard UI (`9/9` tests passing, `65/65` total regression passing).
- **Active Constraints**:
  - Docker container `ai_employee_agent` runs on port 8000 with PostgreSQL on port 5433.
  - All tenant operations require authenticated JWT with valid `tenant_id`.
