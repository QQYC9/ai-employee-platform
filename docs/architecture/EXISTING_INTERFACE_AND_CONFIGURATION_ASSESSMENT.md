# Existing Interface & Configuration Assessment — Frontend Portals & Dynamic Schema Architecture

**Document ID:** `EXISTING_INTERFACE_AND_CONFIGURATION_ASSESSMENT`  
**Governing Workstream:** Workstream A & Workstream J (Dashboards & Human Configuration)  
**Target Repository:** `QQYC9/ai-employee-platform` (Local HEAD `86c1abf`)  
**Status:** **AUDITED & VERIFIED**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Summary & Interface Scope

The human-facing interface of the AI-Employee-Platform consists of two decoupled React single-page applications (SPAs) sharing design principles, authentication tokens, and API client conventions:
1. **Tenant Dashboard (`apps/tenant-dashboard`):** Designed for tenant business owners to configure business profiles, oversee digital employees, monitor conversations, review approvals, and launch marketing campaigns.
2. **Platform Admin Dashboard (`apps/admin-dashboard`):** Designed for platform superadministrators to provision tenants, manage global subscriptions, monitor infrastructure health, and configure global API credentials.

---

## 2. Forensic Route & Component Audit

### 2.1 Tenant Dashboard (`apps/tenant-dashboard/src/`)
- **Technology Stack:** React 18, Vite 5, TypeScript 5, Tailwind CSS, Lucide React, React Router 6.
- **Route Manifest:**
  - `/login`: Tenant user authentication; issues JWT containing `user_id`, `tenant_id`, and `role`.
  - `/`: Operational KPI overview (message volume, active channels, pending tasks).
  - `/agents`: List of digital employees; static view of system persona and prompt instructions.
  - `/tasks`: List of execution tasks; modal for resolving Level 2 owner inquiries.
  - `/channels`: Omni-channel connector setup (Telegram bot tokens, WhatsApp Cloud Phone IDs, Webhook secrets).
  - `/campaigns`: Phase 4D verified outbound marketing campaigns (audience segmentation, status tracking).
  - `/usage`: AI token consumption, model costs, and tenant budget progress bars.
  - `/settings`: Business profile (operating hours, company name, contact info).
- **Architectural Bottleneck:**  
  Every configuration form is statically hardcoded in TSX components (`apps/tenant-dashboard/src/pages/Channels.tsx`, `Settings.tsx`). When an agent discovers a missing business tool (e.g., custom discount rules, inventory stock alerts) and synthesizes it, the tenant owner has no UI to configure or supply necessary parameters without manual React engineering and redeployment.

### 2.2 Admin Dashboard (`apps/admin-dashboard/src/`)
- **Technology Stack:** React 18, Vite 5, TypeScript 5, Tailwind CSS, Lucide React, React Router 6.
- **Route Manifest:**
  - `/login`: Superadmin authentication; validates `role == "superadmin"`.
  - `/`: Platform-wide multi-tenant aggregation metrics.
  - `/tenants`: Tenant provisioning, suspension, quota allocation, and plan tiers (`FREE`, `PRO`, `ENTERPRISE`).
  - `/agents-tasks`: Cross-tenant execution task monitoring.
  - `/monitoring`: System container health, PostgreSQL pool status, Redis memory usage.
  - `/integrations`: Global provider API keys (OpenAI, Gemini, Anthropic, Twilio, Stripe).
  - `/settings`: Platform-wide security parameters and session timeouts.
- **Architectural Defect:**  
  The Admin Dashboard currently lacks visibility into:
  1. The Global Capability Catalog (reusable tools and skills across tenants).
  2. The Godfather Supervisory Telemetry Stream (real-time anomalies, audit digests, and capability health).

---

## 3. Configuration Ownership & Access Boundary Matrix

| Configuration Item | Data Owner | Input Provider | Read Access | Write Access | Storage Location & Encryption | Consumption Subsystem |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Tenant Business Profile** | Tenant Owner | Tenant Owner | Tenant Users | Tenant Owner | `business_profiles` (Plaintext) | FactService, Dynamic Prompts |
| **Channel Credentials (Bot Tokens)** | Tenant Owner | Tenant Owner | Masked (`******`) | Tenant Owner | `channels.config` (AES-256-GCM) | Omni-Connectors, OutboxWorker |
| **Global LLM Provider Keys** | Superadmin | Superadmin | Masked (`******`) | Superadmin | `credentials` (AES-256-GCM) | `ai_providers/factory.py` |
| **Dynamic Tool Parameters** | Tenant Owner | Tenant Owner | Tenant Users | Tenant Owner | `business_entities.dynamic_attributes` | Generated Pydantic Tools |
| **Level 2 Action Approvals** | Tenant Owner | Tenant Owner | Tenant Users | Tenant Owner | `approvals` (Signed JCS HMAC) | Pregel `WaitTracker` Resume |
| **Godfather Escalations** | Platform Founder | The Godfather | Founder Only | Founder Only | Telegram Bot Callback State | Supervisory Guardian Daemon |

---

## 4. Target Architecture: Declarative Dynamic UI Engine

To solve the configuration bottleneck, the platform introduces the **Declarative Dynamic UI Engine**:
1. **Backend Schema Export:** Newly generated tools and modules register Pydantic v2 UI models with field metadata (type, title, description, validation regex, default, secret flag).
2. **REST Schema Endpoint:** Served via `GET /api/v1/ui-schemas/:module_id` with RBAC authorization.
3. **Shared Dynamic Form Renderer:** Both dashboards incorporate a shared, high-performance component (`DynamicFormRenderer.tsx`) that compiles declarative JSON schemas into interactive React forms.
4. **Zero-Recompilation Agility:** Business owners can configure new agents, tools, and business entities immediately upon activation without modifying frontend source code.
5. **Ergonomic Standards:** Native client-side validation via Zod, automatic secret masking, and comprehensive RTL Arabic layout support (`dir="rtl"`).
