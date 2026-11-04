# Founder Decision Register: Authoritative Strategic & Architectural Choices

**Document ID:** `FOUNDER_DECISION_REGISTER`  
**Governing Standard:** Full-Platform Target Vision (`docs/PROJECT_VISION.md`)  
**Audit Standard:** Explicit Decision Options with Trade-Offs & Reversal Costs  
**Target Repository:** `QQYC9/ai-employee-platform` (Local HEAD `fc94752`)

---

## 1. Executive Summary & Master Decision Ledger

This register presents the platform founder with the 6 pivotal architectural decisions required before proceeding to Phase 2 prototyping. Every decision item details the business and technical context, viable options, trade-offs, the core team's concrete recommendation, and the cost of reversal.

| Decision ID | Decision Topic | Primary Trade-Off | Recommendation | Reversal Cost |
| :---: | :--- | :--- | :--- | :---: |
| **FD-01** | **Execution Engine Paradigm: Dual-Mode vs Pure Pregel** | Turn Latency (<3s) vs Single Execution Model | **Dual-Mode Engine (ReAct for Turns, Pregel for Workflows)** | Moderate (Engine refactor) |
| **FD-02** | **Code Synthesis Sandboxing: Linux Jails vs MicroVMs** | Local Windows Dev Complexity vs Multi-Tenant SaaS Security | **Tiered Sandbox (nsjail/gVisor in Docker; Firecracker for Cloud)** | High (Infra re-architecture) |
| **FD-03** | **Supervisory Architecture: Two-Tier Guardian vs Single Godfather** | Founder Notification Noise vs Unified Intelligence Layer | **Two-Tier Hierarchy (Platform Godfather + Tenant Supervisor)** | Low (Agent persona split) |
| **FD-04** | **Dynamic Business Modules: Pre-Provisioned Relational vs Flat JSONB** | Zero-DDL Flexibility vs Double-Entry Relational Rigor | **Two-Tier Schema (Dormant Archetypes + JSONB Extensions)** | High (Data migration lock) |
| **FD-05** | **Statutory Data Privacy: Envelope Encryption vs DB Erasure** | KMS Complexity vs Saudi PDPL Legal Compliance & Audit Integrity | **Envelope Encryption with Customer DSEK Shredding** | High (Schema & crypto refactor) |
| **FD-06** | **Field Acceptance Protocol: Live Telegram Sessions vs CI Green Tests** | Founder Personal Time vs Production Zero-Regression Guarantee | **Enforce ADR-15: Mandatory Live Founder Telegram Acceptance** | Low (Process enforcement) |

---

## 2. In-Depth Strategic Decision Dossiers

### Decision FD-01: Execution Engine Paradigm — Dual-Mode vs Pure Pregel
- **Context:**
  The blueprint adopted LangGraph's Pregel Bulk Synchronous Parallel (BSP) graph model. Pregel persists checkpoints and synchronizes channels after each superstep. For routine customer inquiries (FAQ, order status, booking), executing 3 database roundtrips and row locks per turn adds 300–600ms overhead, directly threatening the sub-3s SLA.
- **Options:**
  - *Option A (Pure Pregel Monoculture):* Use Pregel for every single turn, message, and workflow.
  - *Option B (Dual-Mode Engine — RECOMMENDED):*
    - *Mode 1 (Sequential ReAct Turn Engine):* Fast, zero-overhead in-memory turn loop for standard customer conversations. Single database commit at turn completion.
    - *Mode 2 (Pregel Workflow Engine):* Asynchronous state graph for background multi-agent workflows, campaigns, and scheduled tasks.
- **Trade-Offs:** Option B introduces two execution loops, but guarantees lightning-fast customer turn latency while preserving robust checkpointing for complex workflows.
- **Architectural Recommendation:** **Adopt Option B (Dual-Mode Engine).**
- **Reversal Cost:** Moderate. If pure Pregel is chosen initially and turns fail the 3-second SLA in production, migrating to Dual-Mode requires rewriting the turn runtime.

---

### Decision FD-02: Code Synthesis Sandboxing — Linux Container Jails vs MicroVMs
- **Context:**
  The platform's Dream Daemon synthesizes Python tools dynamically. The research document proposed executing this untrusted code in an ephemeral `uv venv`. As proven in our audit, an ephemeral virtualenv inherits host environment variables (`DATABASE_URL`, `JWT_SECRET_KEY`) and unshielded host networking, allowing total host takeover.
- **Options:**
  - *Option A (Ephemeral `uv venv`):* Fastest local development (<50ms startup), but ZERO OS-level security in multi-tenant SaaS.
  - *Option B (Linux Container Jails via `nsjail` / `gVisor` — RECOMMENDED FOR DOCKER):* Drops all Linux capabilities (`cap-drop=ALL`), enforces read-only root filesystems, memory limits, and isolated network namespaces in Docker Compose. Cold start ~30ms.
  - *Option C (Hardware MicroVMs via Firecracker):* True hardware-level virtualization boundary (AWS Lambda style). Cold start ~150ms. Requires bare-metal Linux with KVM (not natively runnable on local Windows Docker desktop without nested virtualization).
- **Architectural Recommendation:** **Adopt Tiered Sandbox:** Option B (`nsjail` inside worker container) for local development and Docker Compose; Option C (Firecracker) for enterprise multi-tenant cloud deployments.
- **Reversal Cost:** High. Neglecting sandbox isolation now creates catastrophic security liability upon multi-tenant launch.

---

### Decision FD-03: Supervisory Architecture — Two-Tier Guardian vs Single Godfather
- **Context:**
  `PROJECT_VISION.md` introduces The Godfather (الأب الروحي) as the central supervisory intelligence. The research documents conflate platform-level oversight (fleet health, cloud outages) with tenant-level business operations (retail profit margins, customer return disputes). In a 500-tenant platform, notifying the founder about individual tenant operational decisions creates an impossible bottleneck, while tenant business owners have zero supervisory bot.
- **Options:**
  - *Option A (Single Monolithic Godfather):* One bot advising the founder on everything across all tenants.
  - *Option B (Two-Tier Supervisory Model — RECOMMENDED):*
    - *Tier 1: The Central Godfather (الأب الروحي):* Platform infrastructure guardian advising the Founder on fleet health, provider outages, database saturation, and global capacity.
    - *Tier 2: Executive Digital Supervisor (المشرف التنفيذي):* Tenant-scoped executive agent advising the Tenant Business Owner on business KPIs, campaign performance, pending tool approvals, and employee escalations.
- **Architectural Recommendation:** **Adopt Option B.** Cleanly separates platform governance from tenant business operations.
- **Reversal Cost:** Low. Establishes clean role boundaries immediately.

---

### Decision FD-04: Dynamic Business Modules — Pre-Provisioned Relational vs Flat JSONB
- **Context:**
  Vision Section 5 mandates generating complete business modules (sales, invoices, inventory). Blueprint Section 11 strictly prohibits runtime DDL (`CREATE TABLE`), proposing that all dynamic entities live in a single flat JSONB table (`business_entities`). While this prevents runtime migration lockouts, flat JSONB cannot enforce relational integrity, foreign key cascades, or double-entry financial ledger constraints.
- **Options:**
  - *Option A (Flat JSONB Table Only):* High flexibility, but slow queries over 10,000 records, lack of relational constraints, and risk of financial calculation errors.
  - *Option B (Two-Tier Pre-Provisioned Schema Architecture — RECOMMENDED):*
    - *Tier A (Dormant Relational Archetypes):* Pre-migrated, typed relational tables for standard enterprise modules (`sales_invoices`, `inventory_items`, `journal_entries`) with native `DECIMAL(18, 4)` and foreign keys.
    - *Tier B (Dynamic JSONB Extensions):* Pre-provisioned `business_entities` table for unstructured extension attributes.
- **Architectural Recommendation:** **Adopt Option B.** Provides enterprise financial rigor for standard modules while maintaining zero-DDL flexibility for custom tenant extensions.
- **Reversal Cost:** Very High. Storing financial ledgers in unstructured JSONB creates data corruption that is painful and costly to migrate later.

---

### Decision FD-05: Statutory Data Privacy — Envelope Encryption vs Soft Deletion
- **Context:**
  `KNOWLEDGE_AND_MEMORY_ARCHITECTURE.md` relies on soft deletion (`status = 'DELETED'`), leaving customer phone numbers, national IDs, and names in plaintext inside immutable HMAC-SHA256 audit logs and checkpoint payloads. Under Saudi PDPL Article 18 and GDPR Article 17, retaining plaintext PII violates statutory erasure mandates.
- **Options:**
  - *Option A (Soft Deletion Only):* Simple to implement, but non-compliant with Saudi PDPL and subject to heavy regulatory fines.
  - *Option B (Envelope Encryption with Data Subject Keys — RECOMMENDED):* Encrypt all customer PII with an ephemeral Data Subject Key ($K_{subject}$). Audit hashes use the ciphertext. Upon an erasure request, destroy $K_{subject}$ in KMS, rendering the PII permanently unrecoverable while leaving the HMAC audit chain mathematically intact.
- **Architectural Recommendation:** **Adopt Option B.** Solves the regulatory compliance requirement mathematically.
- **Reversal Cost:** High. Implementing envelope encryption retroactively requires re-encrypting the entire historical database.

---

### Decision FD-06: Field Acceptance Protocol — Live Telegram Sessions vs CI Green Tests
- **Context:**
  Vision Section 1 & 17 ("Breaking the Green Test Delusion") and ADR-15 mandate that synthetic unit and integration test passes ("green tests") shall never constitute proof of milestone completion; authoritative acceptance requires real, live conversational testing via Telegram with the platform founder.
- **Options:**
  - *Option A (Synthetic Automated Testing Only):* Fast CI/CD pipelines, but creates false confidence and masks conversational regressions.
  - *Option B (Mandatory Live Founder Telegram Gate — RECOMMENDED):* CI tests are a necessary prerequisite, but the definitive release gate requires the founder interacting with the live bot on Telegram.
- **Architectural Recommendation:** **Reaffirm Option B (ADR-15).** Non-negotiable platform core philosophy.
- **Reversal Cost:** Zero. Preserves absolute quality integrity.

---
*End of Founder Decision Register.*
