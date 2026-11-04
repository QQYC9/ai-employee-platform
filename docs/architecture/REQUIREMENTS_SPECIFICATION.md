# System Requirements Specification — Functional & Non-Functional Contracts

**Document ID:** `REQUIREMENTS_SPECIFICATION`  
**Governing Standard:** Full-Platform Target Vision (`docs/PROJECT_VISION.md`)  
**Target Repository:** `QQYC9/ai-employee-platform`  
**Status:** **AUTHORITATIVE REQUIREMENTS CONTRACT**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Functional Requirements (FR-01 through FR-25)

### Agent Architecture & Generation
- **FR-01 (Dynamic Employee Provisioning):** The system shall generate digital employees dynamically from declarative specifications, assigning explicit roles, missions, autonomy levels, memory scopes, and tool bindings without relying on hardcoded prompt templates.
- **FR-02 (Triage & Untrusted Input Scoping):** All external user input from messaging channels must enter via the Triage Supervisor and be restricted strictly to `INTENT_SAFE_ROLES` before delegating to specialist employees.
- **FR-03 (Specialist Employee Handoffs):** Inter-agent delegation must follow formal `Handoff` contracts with `input_filter` context sanitization, stripping intermediate reasoning traces and diagnostic payloads.
- **FR-04 (Delegation Cycle Prevention):** The engine shall enforce a configurable hop ceiling (`config.MAX_HANDOFF_HOPS = 5`) and maintain an in-memory delegation trace to detect and abort directed delegation cycles ($A \to B \to A$) without intervening user input.

### Autonomous Capability Generation & Dynamic Modules
- **FR-05 (Capability Gap Analysis):** When an agent identifies a missing tool, data source, or workflow, the system shall emit a formal Capability Gap Specification instead of hallucinating results or passively refusing.
- **FR-06 (6-Gate Sandboxed Synthesis):** Dynamically generated tools must pass the 6-gate verification pipeline (AST syntax $\to$ Pydantic schema $\to$ Security AST scan $\to$ UV unit test $\to$ Integration mock $\to$ Smoke profiling) before being registered.
- **FR-07 (Offline Quarantining):** Tool compilation, testing, and skill evolution must execute strictly in the offline background Dream Daemon and shall never run inside an active customer conversational turn.
- **FR-08 (Dynamic Business Module Provisioning):** The platform shall support provisioning dynamic business modules (products, prices, invoices, inventory) using the hybrid relational/JSONB table (`business_entities`) with mandatory typed decimal columns (`DECIMAL(18, 4)`) for financial integrity.
- **FR-09 (Prohibition of Runtime DDL):** Autonomous agents and background generators are strictly prohibited from generating or executing runtime DDL (`CREATE TABLE`, `ALTER TABLE`, `DROP TABLE`).
- **FR-10 (Empirical Utility Pruning):** Dynamically generated skills must track empirical utility scores; skills falling below threshold (`0.2` over 20 runs) shall be automatically quarantined.

### Memory, Knowledge & Privacy Lifecycle
- **FR-11 (5-Tier Memory Separation):** The platform shall segregate memory into five discrete functional tiers: Working Context Buffer, Task Operation Checkpoints, Persistent Fact Memory, Semantic Document RAG, and Procedural Skill Memory.
- **FR-12 (Multi-Dimensional Scoped Facts):** Business facts must include spatial (branch ID), temporal (regular, holiday, weekend), and audience dimensions, preventing spurious conflicts.
- **FR-13 (Fact Supersession & Audit Provenance):** Updated facts must mark superseded records as `SUPERSEDED`, linking to `superseded_by_fact_id` with full audit history.
- **FR-14 (Contradiction Escalation):** Conflicting facts detected during dialogue must transition to `CONTRADICTION_PENDING` and escalate to the owner, halting automated guessing.
- **FR-15 (Privacy Erasure Lifecycle):** Personal data flagged as `is_pii = True` must support cryptographic shredding or deletion upon statutory right-to-be-forgotten requests, while keeping independent regulatory audit logs intact.

### Declarative Dashboards & User-Input Ownership
- **FR-16 (Declarative UI Schema Generation):** Generated capabilities requiring human input or configuration must register a declarative UI schema rendered automatically by `DynamicFormRenderer.tsx` in the dashboards.
- **FR-17 (Strict Dashboard Ownership Scope):** Platform-level configurations (AI provider keys, quotas) belong exclusively to the Admin Dashboard (`apps/admin-dashboard`); business-level configurations belong exclusively to the Tenant Dashboard (`apps/tenant-dashboard`).
- **FR-18 (Secret Masking in UI):** Sensitive credentials must be masked with `******` in API responses and frontend dashboards, preventing credential exposure over client networks.

### Execution Engine, Security & Resilience
- **FR-19 (Pregel StateGraph Supersteps):** The core engine must execute turns as discrete supersteps, committing checkpoints atomically to PostgreSQL.
- **FR-20 (Monotonic Fencing Tokens):** Checkpoint commits and lease updates must verify a monotonic `fence_token` to neutralize zombie worker write attempts.
- **FR-21 (Database Connection Pool Preservation):** Workers must explicitly commit and close SQLAlchemy database sessions immediately before awaiting streaming LLM inference.
- **FR-22 (Three-Tier Autonomy Gating):** State-modifying actions must enforce explicit autonomy levels (Level 1: Assistant Only, Level 2: Approval-Gated, Level 3: Autonomous within Bounds).
- **FR-23 (Context-Bound Approvals & Replay Protection):** Level 2 approvals must enforce RFC 8785 canonical JSON HMAC digests and consume status atomically via `SELECT ... FOR UPDATE`.
- **FR-24 (Extensible Provider Idempotency):** Outbound actions must enforce the 4-tier idempotency spectrum (Tiers 1, 2A, 2B, 3), prohibiting blind retries on non-idempotent endpoints.
- **FR-25 (The Godfather Supervisory Oversight):** The central Godfather daemon must ingest platform telemetry, dispatch emergency alerts to founder Telegram, and deliver an analytical evening executive digest daily at 21:00.

---

## 2. Non-Functional Requirements (NFR-01 through NFR-15)

### Performance & Latency SLAs
- **NFR-01 (Interactive Turn Latency):** 95% of interactive customer conversational turns (non-approval-gated) must complete and stage outbox delivery in $\le 3000\text{ms}$.
- **NFR-02 (Database Connection Lock Duration):** Active database transactions held by worker threads must not exceed $50\text{ms}$ per superstep commit.
- **NFR-03 (Worker Sweeper Lock Timeout):** Takeover sweeper queries must enforce `SET LOCAL lock_timeout = '2s'` to prevent lock contention storms.
- **NFR-04 (Worker Commit Statement Timeout):** Commit transactions must enforce `SET LOCAL statement_timeout = '5s'` to prevent stalled backend locks.

### Tenant Isolation & Security
- **NFR-05 (Cryptographic Tenant Isolation):** Zero cross-tenant data leakage across all relational queries, vector searches, tool executions, and cached Redis keys, verified via automated cross-tenant penetration test suites.
- **NFR-06 (Secrets Hardening):** Zero plaintext logging of sensitive values, enforced via the `SecretStr` primitive and AES-256-GCM encryption at rest.
- **NFR-07 (Tamper-Evident Audit Chaining):** Audit log rows must form an unbroken HMAC-SHA256 hash chain with root hashes anchored hourly to external WORM storage.
- **NFR-08 (Zero Autonomous Production Code Modification):** Autonomous agents and The Godfather must have zero write permissions to modify core platform codebase files.

### Reliability, Concurrency & Recovery
- **NFR-09 (Zero Data Loss on Committed Supersteps):** Any worker crash occurring after a superstep commit must be recoverable from the last committed checkpoint with zero corruption.
- **NFR-10 (Zombie Worker Protection):** Stale workers waking up after lease expiration must be completely blocked from mutating task state via monotonic fencing token mismatch.
- **NFR-11 (Telegram UTF-16 Code Unit Conformance):** All outbound Telegram messages must strictly calculate message length and entity offsets in UTF-16 code units (respecting the 4096 ceiling).
- **NFR-12 (Noisy Neighbor Protection):** The Completely Fair Scheduler (CFS) must enforce Redis token bucket rate limits per tenant, preventing bulk marketing campaigns from degrading interactive customer chat latency.

### Operational Verification & Ground Truth
- **NFR-13 (Ground Truth Verification Gate):** No release or architectural phase is declared complete based on synthetic automated unit tests alone; formal acceptance requires verified, live conversational sessions via Telegram with the platform founder.
- **NFR-14 (Zero Third-Party Commercial License Liability):** The codebase must contain zero package imports or direct code embeddings from Dify (Modified Apache 2.0) or n8n (Sustainable Use License 1.0).
- **NFR-15 (Graceful Degradation):** Under external AI provider outages, the resilient provider fallback chain must automatically failover across configured providers (OpenRouter $\to$ Gemini $\to$ Groq) within $2000\text{ms}$.
