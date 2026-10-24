---
name: autonomous-page-testing
description: >-
  Autonomously tests, verifies, and audits web dashboard pages, route navigation,
  authentication guards, and user interactions across the AI Employee Platform
  dashboards without manual human intervention.
---

# Autonomous Dashboard & Page Testing Skill

This skill defines the standard procedure for the AI coding agent to autonomously test, verify, and report on the health, functionality, rendering, and security isolation of the platform's frontend dashboard interfaces (`apps/tenant-dashboard` and `apps/admin-dashboard`).

## When to Invoke This Skill

The agent must invoke this skill whenever:
1. A new dashboard page or modal is created (e.g. `CampaignsPage`, `TenantsPage`, `PlatformIntegrationsPage`).
2. An existing dashboard component, route, or layout is modified (`App.tsx`, `Sidebar`, `Topbar`).
3. Authentication or role authorization logic changes (`AuthContext.tsx`, `ProtectedRoute`, `client.ts`).
4. API contracts between frontend and backend are updated.
5. Performing end-of-milestone regression verification.

---

## Supported Dashboards & Discovered Route Inventory

### 1. Tenant Dashboard (`apps/tenant-dashboard`)
- `/login`: Public authentication page (email/password).
- `/`: Protected tenant business overview (KPI cards, active agents, tasks summary, budget status).
- `/agents`: Digital employees list, operational statuses, agent configurations.
- `/tasks`: Execution tasks list, failure inspection, and retry action triggers.
- `/channels`: Omni-channel integrations (WhatsApp, Telegram, Webhooks).
- `/campaigns`: Outbound marketing campaigns, recipient metrics, and proactive notifications.
- `/usage`: Real-time AI token usage trends, model consumption, and budget limit warnings.
- `/settings`: Company Business Brain profile, identity, services, and operational policies.

### 2. Platform Admin Dashboard (`apps/admin-dashboard`)
- `/login`: Platform administrator login.
- `/`: Platform-wide overview, active tenants count, aggregate request volumes.
- `/tenants`: Tenant provisioning, activation, deactivation, and isolation boundaries.
- `/agents-tasks`: Cross-tenant agents and tasks overview.
- `/monitoring`: System health, audit logs, AI provider error rates, execution traces.
- `/integrations`: Global AI model provider configuration (OpenRouter, Gemini, Groq).
- `/settings`: Platform security, global quotas, and administrative controls.

---

## Verification Architecture & Test Layers

Testing runs completely unattended using three deterministic layers:

### Layer 1: Static Type & Build Compilation (Vite + TypeScript)
- **Command**: `npm run build` in each dashboard directory.
- **Verification**: Detects broken imports, missing types, invalid JSX/TSX syntax, bundle failures.

### Layer 2: Headless Component & User Interaction Tests (Vitest + JSDOM)
- **Engine**: Vitest with `@testing-library/react` and `@testing-library/jest-dom`.
- **Scope**:
  - Simulates user interactions: clicking buttons, submitting forms, opening/closing modals.
  - Verifies state transitions: loading spinners, error alerts, empty states, and success toasts.
  - Tests authentication redirects: unauthenticated visits redirected to `/login`, role-restricted routes blocked.
  - Verifies RTL layout and Arabic text rendering integrity.

### Layer 3: End-to-End Route & Manifest Verification
- **Engine**: Python Test Runner (`scripts/test_dashboard_runner.py`).
- **Scope**: Validates all registered routes, confirms auth guards exist, logs execution timings, and generates structured reports.

---

## Execution Commands

The agent should execute tests using the verified automated runner:

```bash
# 1. Quick Smoke Test (Verifies route manifest and builds)
python scripts/test_dashboard_runner.py --suite smoke

# 2. Route Inventory & Protection Guard Check
python scripts/test_dashboard_runner.py --suite routes

# 3. Authentication & Role Boundary Check
python scripts/test_dashboard_runner.py --suite auth

# 4. Full Component & Interaction Page Tests
python scripts/test_dashboard_runner.py --suite pages

# 5. Complete Suite & Artifact Report Generation
python scripts/test_dashboard_runner.py --suite all
```

Or via direct npm commands:
```bash
# Tenant Dashboard
npm --prefix apps/tenant-dashboard run build
npm --prefix apps/tenant-dashboard test

# Admin Dashboard
npm --prefix apps/admin-dashboard run build
npm --prefix apps/admin-dashboard test
```

---

## Artifacts & Failure Reports

All test runs automatically output diagnostic artifacts to:
- `artifacts/dashboard-reports/dashboard_report_<timestamp>.json`: Machine-readable summary with timing, pass/fail counts, and errors.
- `artifacts/dashboard-reports/latest_dashboard_report.md`: Formatted human-readable markdown report.

### Error Classification Protocol:
When a test fails, the agent must:
1. Identify whether the failure is a **TypeScript compilation error**, a **missing route registration**, or an **interaction failure**.
2. Examine the captured error stack trace.
3. Fix the underlying root cause in the component or API client.
4. Re-run the test to confirm resolution before reporting completion.

---

## Security & Safety Rules

- **Zero Production Credentials**: Never use real API keys or production passwords in tests.
- **Tenant Isolation**: Always verify that client-side storage (`localStorage` / cookies) is cleared between simulated tenant sessions.
- **Non-Destructive**: Never invoke state-changing APIs against production environments during automated tests.
