# Existing Capability Inventory — Platform Feature & Defect Matrix

**Document ID:** `EXISTING_CAPABILITY_INVENTORY`  
**Governing Workstream:** Workstream A (Existing Platform Forensic Audit)  
**System Designation:** AI Employee Platform (Local Codebase Forensic Analysis)  
**Target Repository:** `QQYC9/ai-employee-platform` (Local HEAD `86c1abf`)  
**Status:** **AUDITED & VERIFIED**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Summary & Inventory Classification Standard

In accordance with Section 3 of the Master Directive, every capability within the local repository `d:\AI-Employee-Platform` has been classified into one of eight rigorous categories:
1. **Existing and Verified:** Implemented, covered by automated integration tests, and verified in local execution.
2. **Existing but Incompletely Verified:** Implemented in code, but lacks end-to-end multi-tenant concurrency or failure recovery tests.
3. **Partially Implemented:** Scaffolding, partial routers, or incomplete classes present; execution path interrupted.
4. **Documented but Not Implemented:** Specified in architecture notes or comments but absent from executable code.
5. **Proposed:** Candidate design for the next-generation engine rebuild.
6. **Rejected:** Explored or attempted previously (e.g. ad-hoc regex patches, FSM wrappers on legacy engine) and discarded.
7. **Unknown:** Ambiguous code without clear ownership or test assertions.
8. **Requires Empirical Validation:** Hypotheses requiring runtime benchmarking (e.g. pgvector 1M chunk scaling).

---

## 2. Complete Platform Capability Inventory Matrix

| Subsystem / Feature | Exact Code Path | Classification | Verification Method / Evidence | Technical Debt & Failure Vectors | Target Rebuild Disposition |
| :--- | :--- | :---: | :--- | :--- | :---: |
| **Outbound Campaigns & Proactive Notifications** | `packages/services/campaign_service.py`, `apps/agent/api/v1/campaigns.py` | **Existing and Verified** | `tests/test_phase4d_campaigns_and_proactive_notifications.py` (9/9 passed) | Relies on single OutboxWorker; lacks CFS fairness queues. | **PRESERVE & ENHANCE** (Link to Redis CFS queue) |
| **Omni-Channel Connectors (WhatsApp & Telegram)** | `packages/connectors/whatsapp.py`, `packages/connectors/telegram.py` | **Existing and Verified** | `tests/test_connectors.py`, live webhook ingestion tests | Telegram lacks astral emoji UTF-16 code unit chunking. | **PRESERVE & HARDEN** (Add UTF-16 code unit chunking) |
| **Secrets Encryption at Rest (AES-256-GCM)** | `packages/core/crypto.py` | **Existing and Verified** | `tests/test_crypto.py`, authenticated encryption tests | Secrets passed as raw strings in memory; potential log leak. | **PRESERVE & HARDEN** (Wrap with `SecretStr` primitive) |
| **Transactional Outbox Worker (`SKIP LOCKED`)** | `packages/services/outbox_worker.py` | **Existing and Verified** | `tests/test_outbox_worker.py` | Universal idempotency assumption; lacks WhatsApp quarantine. | **PRESERVE & HARDEN** (Integrate 4-Tier Idempotency) |
| **JWT Authentication & Tenant Scope Guard** | `packages/auth/tenant.py`, `packages/auth/jwt.py` | **Existing and Verified** | Auth test suites, RBAC route dependencies | `TenantContext` is mutable dict; risk of thread pollution. | **PRESERVE & HARDEN** (Immutable `Scope` dataclass) |
| **Conversational Agent Engine (Monolithic Loop)**| `packages/services/conversational_agent_engine.py` | **Rejected / Defective** | Failed live Telegram acceptance tests; connection starvation | 1,500-line while-loop, 18 commit points, regex guardrails. | **REMOVE (0% Code Carryover)** (Replace with Pregel StateGraph) |
| **Ad-Hoc Finite State Machine Patch** | `packages/services/conversation_fsm_service.py` | **Rejected** | Untracked patch created to solve regex symptoms | Adds brittle wrapper layer without fixing transactional defects. | **REMOVE (0% Code Carryover)** |
| **Business Fact Service** | `packages/services/fact_service.py` | **Partially Implemented** | Flat string persistence; regex topic classification | Fragile keyword matching ("ساعات", "الرياض"); premature DB commits. | **REPLACE** (Multi-Dimensional Scoped Fact Service) |
| **Owner Inquiry Escalation** | `packages/services/owner_inquiry_service.py` | **Partially Implemented** | Unsigned telegram message polling; fragile number parsing | Vulnerable to digit hijacking; lacks RFC 8785 canonical hash. | **REPLACE** (RFC 8785 HMAC Approval Subsystem) |
| **Multi-Provider AI Fallback Chain** | `packages/ai_providers/factory.py`, `resilient_provider.py` | **Existing and Verified** | Unit tests with Mock, Gemini, and OpenRouter fallbacks | Holds DB connections open during slow LLM streaming calls. | **PRESERVE & REFINE** (Enforce DB connection release) |
| **Tenant Business Profile Configuration** | `apps/agent/api/v1/business_profiles.py` | **Existing but Incompletely Verified** | Basic CRUD tests; lacks dynamic schema generation | Static fields only; cannot dynamically define product catalogs. | **REPLACE** (Hybrid `business_entities` model) |
| **Tenant Dashboard Frontend Routes** | `apps/tenant-dashboard/src/` (8 routes) | **Existing and Verified** | `npm --prefix apps/tenant-dashboard test` (Vitest suites) | Static forms; requires manual React coding for new tools. | **PRESERVE & EXTEND** (`DynamicFormRenderer.tsx`) |
| **Admin Dashboard Frontend Routes** | `apps/admin-dashboard/src/` (7 routes) | **Existing and Verified** | `npm --prefix apps/admin-dashboard test` (Vitest suites) | Lacks Global Capability Catalog and Godfather Telemetry page. | **PRESERVE & EXTEND** (Add Superadmin Capability UI) |
| **Autonomous Dynamic Tool & Module Synthesis** | `packages/self_development/` | **Partially Implemented** | Initial prototype files in `packages/self_development/` | Unsandboxed execution; risks executing unsafe AST in production. | **REPLACE** (Offline Dream Daemon + Memento 6-Gate) |
| **The Godfather Supervisory Guardian** | None (Does not exist in legacy code) | **Documented but Not Implemented** | Formally specified in `docs/PROJECT_VISION.md` | Complete architectural absence in legacy implementation. | **NEW REQUIRED** (`packages/godfather/`) |
| **Declarative UI Schema Compiler** | None (Does not exist in legacy code) | **Documented but Not Implemented** | Specified in `DASHBOARD_GENERATION_ARCHITECTURE.md` | Dashboards currently rely entirely on hardcoded React forms. | **NEW REQUIRED** (`packages/ui_engine/`) |
| **pgvector Scaled Indexing (>1M chunks)** | `packages/memory/` | **Requires Empirical Validation** | Schema exists; unbenchmarked at enterprise volume | Potential index bloat and query latency degradation. | **EMPIRICAL VALIDATION** (Benchmark synthetic load) |
