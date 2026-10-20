# Phase 19 — Super Admin Dashboard Architecture & Implementation

## 1. Overview
The **AI Employee Platform Super Admin Dashboard** is an enterprise-grade, responsive, RTL-native single-page web application designed for monitoring, governance, and operational management of multi-tenant digital employees, tasks, outbox reliability, and AI consumption.

Built with **React 18**, **TypeScript 5**, **Vite 5**, and **Tailwind CSS 3**, it adheres strictly to backend security constraints and operational contracts.

---

## 2. Architecture & File Structure

```
apps/admin-dashboard/
├── index.html                           # Entry HTML with Cairo Arabic typography & RTL
├── package.json                         # Scripts & runtime dependencies
├── tsconfig.json                        # Strict TypeScript compiler options
├── tsconfig.node.json                   # Node environment types for Vite
├── vite.config.ts                       # Vite bundler, proxy to Staging (8001), Vitest config
├── tailwind.config.js                   # Custom design system with emerald & navy themes
├── postcss.config.js                    # PostCSS autoprefixer & tailwind plugins
├── dist/                                # Production optimized bundle
└── src/
    ├── main.tsx                         # React 18 createRoot bootstrap
    ├── App.tsx                          # Router, AuthProvider, protected routes
    ├── index.css                        # Tailwind directives, custom scrollbar
    ├── api/
    │   ├── types.ts                     # TypeScript definitions for all domain entities
    │   ├── client.ts                    # Centralized fetch client, JWT attach, 401 refresh
    │   ├── auth.ts                      # Authentication API calls (/auth/login, /me)
    │   ├── admin.ts                     # Platform overview, tenants, metrics, audit logs
    │   └── tasks.ts                     # Tasks listing, retry, cancel, and agents API
    ├── context/
    │   └── AuthContext.tsx              # Global authentication context & state
    ├── components/
    │   ├── layout/
    │   │   ├── AdminLayout.tsx          # Shell with Sidebar, Topbar, Content area
    │   │   ├── Sidebar.tsx              # Collapsible RTL navigation bar with Lucide icons
    │   │   └── Topbar.tsx               # Server connection badge, user info, logout
    │   └── common/
    │       ├── Badge.tsx                # Status badges (healthy, active, degraded, etc.)
    │       ├── StatCard.tsx             # Metric KPI card with trends and icons
    │       ├── Modal.tsx                # Accessible modal dialog with ESC & backdrop handling
    │       ├── LoadingState.tsx         # Animated loading spinner with Arabic caption
    │       ├── ErrorState.tsx           # Error alert box with retry button
    │       └── EmptyState.tsx           # Contextual empty state card
    ├── pages/
    │   ├── LoginPage.tsx                # Secure JWT login with validation & error handling
    │   ├── DashboardPage.tsx            # Live KPI cards, service diagnostics, visual distributions
    │   ├── TenantsPage.tsx              # Tenants directory, search, status modal, budget modal, provisioning
    │   ├── AgentsTasksPage.tsx          # Agents & tasks dual-view, task details modal, retry/cancel
    │   ├── MonitoringPage.tsx           # Outbox diagnostics, stalled tasks, AI providers, audit logs
    │   └── SettingsPage.tsx             # Platform security posture, runtime, and worker config
    └── test/
        ├── setup.ts                     # Test setup with localStorage mock & jest-dom
        ├── client.test.ts               # Unit tests for API client & auth headers
        ├── Badge.test.tsx               # Unit tests for status badge variants
        ├── StatCard.test.tsx            # Unit tests for KPI cards & trends
        └── LoginPage.test.tsx           # Unit tests for login form & validation
```

---

## 3. Pages & Connected Backend Endpoints

| Page | Route | Backend API Endpoints | Supported Operations |
| :--- | :--- | :--- | :--- |
| **تسجيل الدخول (Login)** | `/login` | `POST /api/v1/auth/login`<br>`GET /api/v1/me` | JWT login, token persistence, role extraction |
| **لوحة المعلومات (Dashboard)** | `/` | `GET /api/v1/admin/platform/overview`<br>`GET /api/v1/admin/monitoring/health` | KPI aggregations, service health, visual task/AI distributions |
| **المستأجرون والعملاء (Tenants)** | `/tenants` | `GET /api/v1/admin/platform/tenants`<br>`PATCH /api/v1/admin/platform/tenants/{id}/status`<br>`PATCH /api/v1/admin/platform/tenants/{id}/budget`<br>`POST /api/v1/tenants/provision` | List tenants, search/filter, change status (active/suspended), update AI token budgets, atomic tenant provisioning |
| **الوكلاء والمهام (Agents & Tasks)** | `/agents-tasks` | `GET /api/v1/tasks`<br>`GET /api/v1/tasks/{id}`<br>`POST /api/v1/tasks/{id}/retry`<br>`POST /api/v1/tasks/{id}/cancel`<br>`GET /api/v1/agents` | View agents, list tasks, filter by status, view plan/result/error, execute manual retry or task cancellation |
| **مراقبة النظام (Monitoring)** | `/monitoring` | `GET /api/v1/admin/monitoring/health`<br>`GET /api/v1/admin/platform/metrics`<br>`GET /api/v1/admin/platform/audit-logs` | Outbox queue metrics (dead letter, stuck processing), stalled tasks detection, AI model consumption trends, immutable audit logs |
| **إعدادات المنصة (Settings)** | `/settings` | N/A (Client governance inspection) | Displays active security protocols, rate limiters, worker intervals; masks all secrets |

---

## 4. Verification & Testing Results

- **TypeScript Compilation (`tsc`):** Clean, 0 errors.
- **Production Build (`vite build`):**
  - `dist/index.html` (0.92 kB)
  - `dist/assets/index-CdggXoQd.css` (28.69 kB)
  - `dist/assets/index-DIEVqRUg.js` (263.55 kB)
  - Duration: 12.52 seconds.
- **Unit Test Suite (`vitest run`):**
  - `client.test.ts`: 2 passed
  - `Badge.test.tsx`: 5 passed
  - `StatCard.test.tsx`: 2 passed
  - `LoginPage.test.tsx`: 2 passed
  - **Total: 11 passed (100%), 0 failed.**

---

## 5. Local Execution Instructions

To start the development server connected to Staging (`http://127.0.0.1:8001`):

```bash
cd apps/admin-dashboard
npm run dev
```

To run the automated tests:
```bash
cd apps/admin-dashboard
npm run test
```

To build for production:
```bash
cd apps/admin-dashboard
npm run build
```
