# Architectural Decision Records (ADR) Register — Master Governance

**Document ID:** `ARCHITECTURAL_DECISION_RECORDS`  
**Governing Standard:** Full-Platform Target Vision (`docs/PROJECT_VISION.md`)  
**Target Repository:** `QQYC9/ai-employee-platform`  
**Status:** **AUTHORITATIVE ARCHITECTURAL GOVERNANCE**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Summary & Lifecycle Schema

Every architectural decision governing the rebuild of the AI-Employee-Platform is codified below with complete lifecycle metadata, empirical evidence, trade-offs, and verification criteria:

```text
ADR Classification Status:
- ARCHITECTURAL DECISION: Verified, authoritatively accepted, binding on all implementation phases.
- HYPOTHESIS: Configurable parameter or heuristic subject to empirical calibration during Phase 2.
- OPEN: Architectural alternative under evaluation pending operational benchmarks.
```

---

## 2. Master ADR Ledger (ADR-01 through ADR-15)

### ADR-01: Execution Engine Paradigm
- **Decision:** Adopt LangGraph-style Pregel state graph iteration loop combined with OpenAI Agents SDK declarative Handoffs.
- **Scope:** Core digital employee turn runtime (`packages/engine/runtime.py`).
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** Verified in `D:\AI-Employee-Platform-Research\langgraph\libs\langgraph\langgraph\pregel\_loop.py` and `openai-agents-python\src\agents\handoffs\`.
- **Trade-offs:** Higher upfront engineering complexity than a simple while-loop; yields deterministic superstep checkpointing, crash resilience, and multi-agent isolation.
- **Reversal Criteria:** If Pregel graph execution overhead exceeds $100\text{ms}$ per turn under low concurrency.
- **Decision Gate:** Phase 1 Approval Gate.

### ADR-02: Total Replacement of Legacy Conversation Engine
- **Decision:** Permanently delete and replace `conversational_agent_engine.py` without dual-track running or fallback bridges (0% code carryover).
- **Scope:** Entire platform conversational backend.
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** Mandated by founder strategic reset in `docs/PROJECT_VISION.md` Section 1 ("The Core Problem").
- **Trade-offs:** Requires thorough pre-cutover testing; permanently eliminates legacy technical debt and regression loops.
- **Reversal Criteria:** Irreversible strategic commitment per founder charter.
- **Decision Gate:** Phase 1 Approval Gate.

### ADR-03: Database Connection Pool Lifecycle
- **Decision:** Explicitly commit and close SQLAlchemy database sessions before initiating external LLM streaming calls, re-opening a fresh transaction upon stream completion.
- **Scope:** All conversational agent inference execution paths.
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** Verified in Dify source code `api/core/agent/fc_agent_runner.py:165-167`.
- **Trade-offs:** Requires converting ORM entities to Pydantic models before closing session to avoid `DetachedInstanceError`; completely eliminates connection pool starvation.
- **Reversal Criteria:** If provider streaming latency drops below $50\text{ms}$ across all models.
- **Decision Gate:** Phase 1 Approval Gate.

### ADR-04: Distributed Zombie Worker Fencing
- **Decision:** Enforce monotonic integer fencing tokens on all checkpoint writes and task updates to prevent zombie workers from corrupting state.
- **Scope:** Task execution, lease acquisition, and checkpoint persistence (`execution_tasks`).
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** Distributed systems consensus theory (Martin Kleppmann fencing tokens) and PostgreSQL optimistic locking.
- **Trade-offs:** Requires tracking a 64-bit integer counter in task metadata.
- **Reversal Criteria:** If deployment moves to single-process synchronous architecture (not applicable for enterprise scale).
- **Decision Gate:** Phase 1 Approval Gate.

### ADR-05: Handoff Hop Ceiling & Ping-Pong Prevention
- **Decision:** Implement a DAG-based cycle detection algorithm on delegation chains; initial hop ceiling set as an uncalibrated hypothesis (`config.MAX_HANDOFF_HOPS = 5`).
- **Scope:** Multi-agent handoff orchestration.
- **Status:** **`HYPOTHESIS`**
- **Evidence:** OpenAI Agents SDK delegation patterns.
- **Trade-offs:** A strict cap of 5 might prematurely abort deeply nested complex business workflows.
- **Calibration Criteria:** Benchmark complex multi-department business scenarios to evaluate truncation risk.
- **Decision Gate:** Phase 2 Engine Verification Gate.

### ADR-06: Memory Outcome Reinforcement Delta
- **Decision:** Initial outcome reinforcement weight set as an uncalibrated hypothesis (`config.MEMORY_LEARNING_DELTA = 0.05`).
- **Scope:** Long-term memory retrieval scoring.
- **Status:** **`HYPOTHESIS`**
- **Evidence:** RagLeap Core source code `core/employees/learning.py:10`.
- **Trade-offs:** Improper calibration risks memory retrieval volatility or catastrophic forgetting.
- **Calibration Criteria:** Run 20 positive and negative simulated dialogue cycles to measure retrieval stability.
- **Decision Gate:** Phase 2 Memory Subsystem Gate.

### ADR-07: Skill Evolution Quarantining
- **Decision:** Restrict Memento-Skills 6-gate evolution pipeline exclusively to offline background daemons (Dream Daemon).
- **Scope:** Autonomous skill generation and code synthesis.
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** Memento-Skills execution benchmark (10–60s compilation/sandbox latency).
- **Trade-offs:** Digital employees cannot instantly acquire a completely new tool mid-conversation; guarantees customer response SLA $< 3000\text{ms}$.
- **Reversal Criteria:** If LLM compilation and sandbox verification drops below $200\text{ms}$.
- **Decision Gate:** Phase 1 Approval Gate.

### ADR-08: Third-Party License Risk Avoidance
- **Decision:** Enforce a strict zero-dependency policy on Dify and n8n source code and packages as a conservative engineering risk-avoidance strategy. Re-implement architectural concepts cleanly in native Python/FastAPI.
- **Scope:** Entire codebase dependencies and package imports.
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** Dify Modified Apache 2.0 (Clause 1.a multi-tenant restriction) and n8n Sustainable Use License 1.0 (Clause 3.2 non-commercial restriction).
- **Trade-offs:** Requires writing native Python implementation of workflow patterns; eliminates legal ambiguity and multi-tenant SaaS licensing liabilities.
- **Reversal Criteria:** If commercial enterprise licenses are formally executed with LangGenius and n8n GmbH.
- **Decision Gate:** Phase 1 Approval Gate.

### ADR-09: Dynamic Business Modules Storage Architecture
- **Decision:** Provision dynamic business modules (products, invoices, inventory) using the hybrid relational/JSONB table (`business_entities`) with mandatory typed decimal columns (`DECIMAL(18, 4)`) and strictly prohibit runtime DDL.
- **Scope:** Autonomous capability generation and dynamic tenant data models.
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** PostgreSQL 17 JSONB indexing boundaries and financial decimal precision requirements.
- **Trade-offs:** Complex multi-table relational joins require transitioning entities > 10,000 rows to dedicated relational migrations.
- **Reversal Criteria:** None; runtime DDL is categorically banned to prevent production lockouts.
- **Decision Gate:** Phase 1 Approval Gate.

### ADR-10: Declarative UI Schema Engine for Dashboard Generation
- **Decision:** Implement a schema-driven declarative UI engine where backend capabilities register Pydantic UI contracts rendered automatically by `DynamicFormRenderer.tsx` in both dashboards.
- **Scope:** Tenant and Platform Admin Dashboards (`apps/*-dashboard`).
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** Full-Platform Target Vision (`docs/PROJECT_VISION.md` Section 9).
- **Trade-offs:** Slightly more complex initial frontend component architecture; permanently eliminates the need for manual React page authoring for new tools.
- **Reversal Criteria:** If user experience requirements demand highly custom bespoke Canvas graphics.
- **Decision Gate:** Phase 1 Approval Gate.

### ADR-11: The Godfather Authority Boundary
- **Decision:** The Godfather operates strictly as an out-of-band supervisory guardian connected to founder Telegram; it possesses **ZERO autonomous write authority** on production codebase files or database schemas.
- **Scope:** Platform supervisory plane (`packages/godfather/`).
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** Master Platform Vision (`docs/PROJECT_VISION.md` Sections 10, 14).
- **Trade-offs:** Architectural modifications require manual founder confirmation (`YES <proposal_id>`); guarantees absolute defense-in-depth safety.
- **Reversal Criteria:** Categorically non-reversable per platform founding charter.
- **Decision Gate:** Phase 1 Approval Gate.

### ADR-12: Context-Bound Approvals & Replay Protection
- **Decision:** Bind Level 2 approvals to RFC 8785 Canonical JSON HMAC-SHA256 digests (`inputs_digest`) and consume state atomically via `SELECT ... FOR UPDATE` row locks.
- **Scope:** Approval service and Human-in-the-Loop subsystem.
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** RFC 8785, NIST SP 800-107, and distributed consensus security.
- **Trade-offs:** Requires storing a secret HMAC key in KMS/environment and serializing arguments deterministically.
- **Reversal Criteria:** None; parameters must be tamper-proof.
- **Decision Gate:** Phase 1 Approval Gate.

### ADR-13: Extensible Provider Idempotency Spectrum
- **Decision:** Enforce the 4-tier provider idempotency spectrum (Tier 1: Native, Tier 2A: Queryable, Tier 2B: Asynchronously Correlatable with Quarantine, Tier 3: Blind); strictly ban automated retries on Tier 3 endpoints.
- **Scope:** Transactional outbox worker and external channel connectors.
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** Verified Meta Graph API, Stripe API, and Twilio API specifications.
- **Trade-offs:** Requires quarantine timeout state machines for WhatsApp outbound failures.
- **Reversal Criteria:** If Meta or Twilio introduces native `Idempotency-Key` headers on message dispatch.
- **Decision Gate:** Phase 1 Approval Gate.

### ADR-14: Tamper-Evident Audit Chain & WORM Storage Anchoring
- **Decision:** Construct an HMAC-SHA256 audit hash chain over all administrative and tool actions, anchoring hourly root hashes to external Write-Once-Read-Many (WORM) storage.
- **Scope:** Platform compliance and security audit logs (`audit_events`).
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** RagLeap Core audit architecture and regulatory enterprise compliance standards.
- **Trade-offs:** Incurs nominal AWS S3 Object Lock / signed Git repository operational costs.
- **Reversal Criteria:** None; enterprise compliance requires tamper-evident auditability.
- **Decision Gate:** Phase 1 Approval Gate.

### ADR-15: Authoritative Field Acceptance Ground Truth
- **Decision:** Synthetic unit and integration test passes alone ("green tests") shall never constitute proof of milestone completion; the authoritative acceptance gate requires real, live conversational sessions via Telegram with the platform founder.
- **Scope:** Entire platform quality assurance and release engineering.
- **Status:** **`ARCHITECTURAL DECISION`**
- **Evidence:** Mandated by founder founding vision in `docs/PROJECT_VISION.md` Sections 1 & 17 ("Breaking the Green Test Delusion").
- **Trade-offs:** Requires interactive human testing time; eliminates catastrophic production regressions and false-positive deployments.
- **Reversal Criteria:** Non-negotiable platform core philosophy.
- **Decision Gate:** Phase 1 Approval Gate.
