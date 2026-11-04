# Independent Adversarial Architecture Review — Failure Modes, Stress Tests & Invariants

**Document ID:** `INDEPENDENT_ADVERSARIAL_REVIEW`  
**Governing Workstream:** Workstream M (Independent Adversarial Architecture Reviewer)  
**Governing Vision:** `docs/PROJECT_VISION.md` & `docs/architecture/MASTER_ARCHITECTURE_BLUEPRINT.md`  
**Status:** **AUDITED & ADOPTED**  
**Date:** 2026-11-04  
**Reviewer:** Independent Adversarial Architecture Review Group  

---

## 1. Executive Adversarial Stance & Mandate

This document serves as the unsparing, independent adversarial audit of the target AI-Employee-Platform architecture. Its purpose is to actively seek out, stress-test, and document edge-case failures, concurrency race conditions, split-brain recovery gaps, and cognitive hallucinations across the entire platform before engineering begins.

---

## 2. The 9 Core Pillar Vulnerability Dissections

### 2.1 Pregel StateGraph Runtime: The Side-Effect Replay Trap
- **Vulnerability:** Checkpointing occurs at superstep completion. If a node makes an external HTTP API call (e.g., calling an ERP API to reserve inventory or dispatching a payment invoice) and the worker process experiences a crash/OOM kill before the PostgreSQL transaction commits, Worker 2 resumes from the previous superstep and re-executes the node from scratch, causing duplicate external side-effects (e.g. reserving double the inventory).
- **Mandatory Mitigation:** **Two-Phase Tool Execution (Staged Intent Pattern)**. External state-modifying tools must first commit an `execution_intent_id` to the database in Superstep $K$. The outbox worker executes the external API call in Superstep $K+1$. If replayed, Worker 2 checks the intent status rather than blindly re-invoking the external API.

### 2.2 Memento-Skills 6-Gate Pipeline: Host Contamination in UV Sandboxes
- **Vulnerability:** Gate 4 executes unit tests inside a local Python `uv` virtual environment. A Python virtualenv provides zero process, network, or filesystem isolation; generated code can read host environment variables (`DATABASE_URL`, `JWT_SECRET`), connect to internal PostgreSQL/Redis sockets (`localhost:5433`), or exhaust host disk space.
- **Mandatory Mitigation:** Dynamic tool tests must execute inside containerized or microVM sandboxes (`--network none`, read-only root filesystems, dropped capabilities, and strict `cgroups` memory/CPU caps). Unrestricted arbitrary Python execution is banned; tools compile into declarative DSL contracts.

### 2.3 The Godfather Supervisory Guardian: Telegram Alarm Flooding & False Cascades
- **Vulnerability:** If The Godfather relies purely on LLM reasoning to evaluate raw telemetry, transient network blips can trigger cognitive hallucinations and emergency alerts at 3:00 AM. During real cascading outages (1,000 tasks failing/minute), sending individual alerts hits Telegram Bot API rate limits (HTTP 429), silencing the supervisor during the worst crisis.
- **Mandatory Mitigation:** Enforce a **Deterministic Alert Aggregator** with a strict rate ceiling (max 1 alert per 15-minute window per failure category). The Godfather alerts only when hard metrics cross thresholds ($> 15\%$ failure rate sustained over 5 minutes), not on raw LLM inferences.

### 2.4 Database Connection Pool Preservation: The 15-Second Lost Update Window
- **Vulnerability:** Closing database sessions before awaiting slow external LLM streaming (15 seconds) creates a window where intervening customer cancellations or status updates are overwritten when the worker re-opens the session and commits based on the stale snapshot.
- **Mandatory Mitigation:** **Optimistic Concurrency Control (OCC)** using a monotonic `version_id`. Re-opening the session validates `WHERE id = :id AND version_id = :expected_version`. If `rows_updated == 0`, the worker triggers a reconciliation branch rather than overwriting state.

### 2.5 Multi-Tenant Isolation: The HNSW Vector Post-Filtering Recall Collapse
- **Vulnerability:** Traversal of a single global HNSW index in PostgreSQL `pgvector` post-filtered by `tenant_id` results in top nearest-neighbor candidates being discarded if they belong to larger tenants, returning empty search results for smaller tenants even when relevant documents exist.
- **Mandatory Mitigation:** Enforce PostgreSQL **Row-Level Security (RLS)** at the database kernel level (`ALTER TABLE knowledges ENABLE ROW LEVEL SECURITY`), and dynamically expand `hnsw.ef_search = 100` during tenant RAG queries.

### 2.6 Dynamic Business Modules: Untyped Financial Math in JSONB
- **Vulnerability:** Storing financial numbers in JSONB exposes calculations to IEEE-754 floating-point rounding errors (`100.10 - 20.00 + 15.00 = 95.10000000000001`), violating financial reporting laws.
- **Mandatory Mitigation:** Prohibit numeric floats in JSONB. All monetary values in `dynamic_attributes` must be packed as ISO string decimals and parsed using Python `decimal.Decimal`. The schema must feature a `schema_version` column with migration decoders.

### 2.7 Declarative UI Engine: The Masked Secret Overwrite Vulnerability
- **Vulnerability:** When a tenant edits channel settings, the backend returns masked secrets (`"******"`). Submitting the form writes the literal string `"******"` back to the database, corrupting the encrypted token.
- **Mandatory Mitigation:** The backend returns `{"api_token_configured": true}` without returning any value. Empty input preserves the existing secret; new non-empty input re-encrypts and overwrites.

### 2.8 Omni-Channel Delivery: WhatsApp Quarantine Freezing & Surrogate Splitting
- **Vulnerability:** Placing a WhatsApp turn into a 15-minute quarantine on timeout blocks the customer session, causing new customer inquiries to be dropped. Naive text slicing at 4,096 characters splits high/low surrogate pairs, triggering Telegram `HTTP 400 Bad Request`.
- **Mandatory Mitigation:** Implement **Speculative Forking** (quarantined turns do not freeze new customer messages) and **Surrogate-Aware UTF-16 Chunking** that never splits surrogate pairs.

### 2.9 Distributed Concurrency: Inter-Table Deadlock Inversion
- **Vulnerability:** Locking `execution_tasks` then `outbox_events` while the outbox sweeper locks `outbox_events` then checks `execution_tasks` causes PostgreSQL deadlocks (`40P01`).
- **Mandatory Mitigation:** Enforce an immutable global lock acquisition hierarchy:
  $$\text{execution\_tasks} \longrightarrow \text{execution\_checkpoints} \longrightarrow \text{outbox\_events}$$

---

## 3. The 12 Non-Negotiable Engineering Invariants for Implementation

1. **Pure Function Node Invariant:** No Pregel node may execute irreversible external side-effects directly; external actions must be staged as outbox intents.
2. **Atomic Superstep Invariant:** A superstep is either fully committed (state delta + checkpoint + outbox events) or fully rolled back.
3. **Lost-Update Rejection Invariant:** Any DB write following an LLM streaming gap must verify optimistic concurrency versioning (`version_id`).
4. **Physical RLS Invariant:** Multi-tenancy must be enforced at the PostgreSQL database kernel via Row-Level Security, never solely in application Python code.
5. **Memory Purge Invariant:** PII and business facts must have explicit lifecycle states (`ACTIVE`, `SUPERSEDED`, `DELETED`), strictly separated from immutable regulatory audit logs.
6. **Sandbox Isolation Invariant:** Generated dynamic capabilities must never execute in un-sandboxed host processes or virtualenvs; they must run in network-isolated microVMs/containers.
7. **Secret Blindness Invariant:** Cleartext secrets must never enter logs, client responses, or unmasked frontend payloads.
8. **Surrogate-Safe UTF-16 Invariant:** Text chunking for messaging channels must respect UTF-16 code units and never split high/low surrogate pairs.
9. **Idempotency Spectrum Invariant:** Outbound dispatchers must strictly enforce the provider capability tier (Tier 1 retry, Tier 2B quarantine, Tier 3 manual reconciliation).
10. **Alert Threshold Invariant:** The Godfather must never page the founder based solely on un-aggregated raw LLM inferences.
11. **Relational Financial Invariant:** No monetary calculation may ever be performed using floating-point numbers in JSONB.
12. **Ground-Truth Acceptance Invariant:** No release is complete until verified through live, interactive Telegram conversations with the platform founder.
