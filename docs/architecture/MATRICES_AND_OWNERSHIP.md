# Architectural Matrices & Ownership Specification

**Document ID:** `MATRICES_AND_OWNERSHIP`  
**Governing Standard:** Full-Platform Target Vision (`docs/PROJECT_VISION.md` Sections 2, 3, 9, 10, 14)  
**Target Repository:** `QQYC9/ai-employee-platform`  
**Status:** **AUTHORITATIVE ARCHITECTURAL SPECIFICATION**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Master Platform Capability Matrix (Current vs. Target Architecture)

| Capability Dimension | Legacy Architecture (Phase 4D/5.0) | Target Rebuild Architecture (Next-Gen Engine) | Verified Architectural Source |
| :--- | :--- | :--- | :--- |
| **Execution Paradigm** | 1,500-line monolithic while-loop in `conversational_agent_engine.py` | Stateful Pregel StateGraph with discrete superstep checkpointing | LangGraph (`libs/langgraph/pregel/_loop.py`) |
| **Agent Provisioning** | Static persona templates seeded via migration `3b4c5d6e7f8a` | Autonomous 10-Stage Agent Provisioning Engine with capability gap synthesis | Target Vision (`docs/PROJECT_VISION.md` Section 3) |
| **Capability Synthesis** | Hardcoded tools; experimental `packages/self_development` | Offline Dream Daemon running Memento 6-Gate verification in isolated UV sandboxes | Memento-Skills (`core/skill/evolution/engine.py`) |
| **Business Modules** | Predefined fixed tables; zero dynamic business support | Dynamic Business Module Engine (`business_entities` hybrid SQL/JSONB, `DECIMAL(18, 4)`) | Target Vision (`docs/PROJECT_VISION.md` Section 5) |
| **Dashboard Interfaces** | Manually written React pages for each new feature | Schema-Driven Declarative UI Engine (`DynamicFormRenderer.tsx`) auto-rendering new schemas | Target Vision (`docs/PROJECT_VISION.md` Section 9) |
| **Central Supervisory** | None; uncoordinated logs scattered across console/DB | **The Godfather (الأب الروحي)**: Independent guardian daemon connected to founder Telegram | Target Vision (`docs/PROJECT_VISION.md` Section 10) |
| **Conversational State** | String matching & ad-hoc regex inspection; number hijacking | Discrete Pregel state nodes with strict state locks (`IDLE`, `AWAITING_APPROVAL`) | LangGraph State Loop + Clean State Transitions |
| **Reply Safety Guardrails**| 13-item fragile regex list (`temporal_location_tokens`) | Deterministic pre-inference and post-inference tripwire guardrails + RBAC kernel | OpenAI Agents SDK (`src/agents/guardrails/`) |
| **Inter-Agent Handoff** | None; monolithic single-agent prompt | Declarative `Handoff` contracts with `input_filter` context sanitization & DAG cycle check | OpenAI Agents SDK (`src/agents/handoffs/`) |
| **Database Pool Safety** | Database transaction held open across external LLM streaming | Connection Pool Preservation: DB session committed & closed before LLM streaming | Dify (`api/core/agent/fc_agent_runner.py`) |
| **Distributed Concurrency**| No worker fencing; vulnerable to split-brain zombie workers | Row-level exclusive lock sequencing + monotonic fencing tokens (`fence_token`) | PostgreSQL 17 Explicit Locking + Martin Kleppmann |
| **Human-in-the-Loop** | Unsigned inquiry escalation loop in `owner_inquiry_service.py` | RFC 8785 Canonical JSON + HMAC-SHA256 digest + atomic row-lock state consumption | RagLeap Core Autonomy + n8n `WaitTracker` |
| **Fact Scoping & Lifecycle**| Flat strings with generic `topic`; spurious conflict generation | Multi-dimensional scoped facts (spatial, temporal, audience) with explicit supersession | Target Vision (`docs/PROJECT_VISION.md` Section 6) |
| **Memory Architecture** | Single conversation history buffer | 5-Tier Memory (Working Buffer, Checkpoint, Fact, Semantic RAG, Procedural Skill) | Target Vision (`docs/PROJECT_VISION.md` Section 6) |
| **Data Privacy & Erasure** | Unbounded fact persistence; no PII lifecycle | Configurable purpose retention, `is_pii` flagging, and statutory cryptographic shredding | Enterprise Privacy Standards & GDPR |
| **Outbox Deduplication** | Simple unique constraint on event ID | 6-Layer Deduplication separating internal database invariants from external side-effects | Distributed Systems Consensus Boundaries |
| **Provider Idempotency** | Assumed universal idempotency headers across all providers | Extensible Idempotency Matrix (Tiers 1, 2A, 2B, 3) with timeout quarantine windows | Verified Provider Specs (Stripe, Meta, Twilio) |
| **Tenant Isolation** | Basic SQLAlchemy `tenant_id` query filters | 4-Layer Defense-in-Depth: Immutable `Scope`, BaseRepo, Relational Keys, Tool Sandbox | RagLeap Core (`core/security/scope.py`) |
| **Secret Hardening** | Encryption at rest via AES-256-GCM; potential logging leakage | `SecretStr` redaction wrapper (`[REDACTED]` in logs/repr) + AES-256-GCM + UI masking | RagLeap Core (`core/security/secrets.py`) |
| **Audit Chaining** | Simple database audit table | Tamper-evident SHA-256 HMAC hash chain with hourly root anchoring to external WORM storage | RagLeap Core (`core/audit/hash_chain.py`) |
| **Channel Protocols** | Standard string length calculations for Telegram | Strict UTF-16 code unit measurement + automatic markdown tag balancing | Microsoft Agent Framework (`hosting-telegram/`) |
| **Tenant Fairness** | Shared worker pool; vulnerable to noisy-neighbor starvation | Completely Fair Scheduler (CFS) with segregated queues & Redis token buckets | Operational Queue Architecture |
| **Verification Gate** | Synthetic Pytest/Vitest passes alone ("Green Test Delusion") | **Ground-Truth Protocol**: Real, live Telegram dialogue sessions with platform founder | Target Vision (`docs/PROJECT_VISION.md` Section 17) |

---

## 2. User-Input Ownership & Access Matrix

| System Domain / Asset | Platform Admin (Superadmin) | Tenant Business Owner | Digital Employee (Agent) | The Godfather (Founder Guardian) | Governing Dashboard |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Global AI Provider Keys** (Gemini, OpenRouter) | **Owner & Author** (CRUD) | No Access | Read-Only (via backend factory) | Read-Only (Health telemetry) | **Admin Dashboard** (`/integrations`) |
| **Tenant Subscription Quota & Rate Limits** | **Owner & Author** (CRUD) | Read-Only (Usage metrics) | Read-Only (Budget guard) | Read-Only (Forensic audit) | **Admin Dashboard** (`/tenants`) |
| **Tenant Business Profile & Identity** | Read-Only (Auditing) | **Owner & Author** (CRUD) | Read-Only (System prompt) | Read-Only | **Tenant Dashboard** (`/settings`) |
| **Multi-Dimensional Operating Hours** | Read-Only | **Owner & Author** (CRUD) | Read-Only (Inquiry replies) | Read-Only | **Tenant Dashboard** (`/settings`) |
| **Channel Credentials** (WhatsApp, Telegram) | Read-Only (Masked) | **Owner & Author** (CRUD) | No Direct Access (Outbox worker) | Read-Only (Status checks) | **Tenant Dashboard** (`/channels`) |
| **Digital Employee Creation & Activation** | Read-Only (Global stats) | **Owner & Author** (CRUD) | Propose Self-Extension | Propose New Profiles | **Tenant Dashboard** (`/agents`) |
| **Autonomy Level Configuration** (`1, 2, 3`) | Set Platform Ceiling | **Owner & Author** (Per Agent) | Strictly Bound by Level | Anomaly Detection | **Tenant Dashboard** (`/agents`) |
| **Level 2 Action Approval Resumption** | No Access | **Sole Authorizer** (Accept/Reject) | Propose & Suspend | Alert on High-Value Delay | **Tenant Dashboard** (`/tasks`, `/approvals`) |
| **Dynamic Product & Price Entities** | No Access | **Owner & Author** (CRUD) | Read & Draft Quotes | Anomaly Detection | **Tenant Dashboard** (`/modules/catalog`) |
| **Declarative UI Schema Registration** | Review System Schemas | Review Business Schemas | Generate Staged Schema | Review Anomaly Flags | Dynamic Route (`/dynamic/:key`) |
| **Platform Telemetry & Error Forensics** | Full Inspection | View Tenant-Only Traces | Emits Telemetry | Primary Consumer & Digest Sender| **Admin Dashboard** (`/monitoring`) |

---

## 3. Dashboard Requirements Matrix

### 3.1 Admin Dashboard (`apps/admin-dashboard`)
| Route / View | Primary Components | Required Authorization | Declarative UI Integration | Verification Criteria |
| :--- | :--- | :--- | :--- | :--- |
| `/login` | `LoginForm.tsx`, `AuthContext.tsx` | Public | None | Redirects to `/` upon valid superadmin JWT. |
| `/` | `StatsGrid.tsx`, `TenantOverviewCard.tsx` | `SUPERADMIN` | None | Displays aggregate platform throughput and active tenant count. |
| `/tenants` | `TenantTable.tsx`, `CreateTenantModal.tsx` | `SUPERADMIN` | `DynamicFormRenderer` for custom tenant contract attributes. | Autonomous page testing asserts tenant creation and quota updates. |
| `/agents-tasks` | `CrossTenantTaskMonitor.tsx`, `ZombieSweeper.tsx` | `SUPERADMIN` | None | Displays active Pregel tasks, leases, and fencing tokens across all tenants. |
| `/monitoring` | `AuditLogViewer.tsx`, `ProviderLatencyChart.tsx` | `SUPERADMIN` | None | Real-time telemetry, audit hash chain validation, error log inspect. |
| `/integrations` | `ProviderKeyForm.tsx`, `HealthPingButton.tsx` | `SUPERADMIN` | `DynamicFormRenderer` for new provider adapters. | Validates provider keys via test ping; masks values with `******`. |
| `/settings` | `GlobalSecuritySettings.tsx`, `FounderBotConfig.tsx` | `SUPERADMIN` | `DynamicFormRenderer` for global platform policies. | Sets rate-limiting token bucket defaults and founder Telegram chat ID. |

### 3.2 Tenant Dashboard (`apps/tenant-dashboard`)
| Route / View | Primary Components | Required Authorization | Declarative UI Integration | Verification Criteria |
| :--- | :--- | :--- | :--- | :--- |
| `/login` | `LoginForm.tsx`, `AuthContext.tsx` | Public | None | Redirects to `/` upon valid tenant JWT. |
| `/` | `DashboardKPIs.tsx`, `PendingApprovalsBanner.tsx` | `TENANT_USER` | None | Displays active digital employees, conversation stats, pending Level 2 actions. |
| `/agents` | `AgentGrid.tsx`, `AgentDetailModal.tsx` | `TENANT_OWNER` | `DynamicFormRenderer` for agent-specific parameter profiles. | Displays Capabilities Disclosure; configures autonomy tiers (`1, 2, 3`). |
| `/tasks` | `TaskHistoryTable.tsx`, `ApprovalModal.tsx` | `TENANT_OWNER` | None | Approves/rejects Level 2 requests; triggers atomic state consumption. |
| `/channels` | `WhatsAppSetupCard.tsx`, `TelegramSetupCard.tsx` | `TENANT_OWNER` | `DynamicFormRenderer` for custom webhook connector settings. | Verifies channel handshakes; stores secrets encrypted with AES-256-GCM. |
| `/campaigns` | `CampaignList.tsx`, `AudienceFilterModal.tsx` | `TENANT_OWNER` | None | Schedules outbound proactive notifications (Phase 4D verified). |
| `/usage` | `UsageChart.tsx`, `QuotaAlertBanner.tsx` | `TENANT_USER` | None | Renders token consumption trends and budget limit warnings. |
| `/settings` | `BusinessProfileForm.tsx`, `OperatingHoursGrid.tsx` | `TENANT_OWNER` | `DynamicFormRenderer` for custom business facts and holiday schedules. | Updates scoped facts with explicit supersession and cache invalidation. |
| `/dynamic/:interface_key` | `DynamicFormRenderer.tsx`, `ErrorBoundary.tsx` | `TENANT_OWNER` | **Primary Host** for all generated capability interfaces. | Dynamically compiles and renders form fields from backend schema contracts. |
