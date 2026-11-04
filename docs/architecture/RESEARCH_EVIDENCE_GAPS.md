# Research Evidence Gaps & Empirical Validation Catalog

**Document ID:** `RESEARCH_EVIDENCE_GAPS`  
**Governing Standard:** Ground-Truth Quality Gate Protocol (`/goal`)  
**Target Repository:** `QQYC9/ai-employee-platform` (Local Path: `d:\AI-Employee-Platform`)  
**Active Branch:** `checkpoint/phase-12-knowledge-base`  
**Verified Commit (HEAD):** `86c1abf609405bf170cd8a97212825acc107feb9`  
**Status:** **AUTHORITATIVE EMPIRICAL GAPS REGISTER**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Summary

A core principle of the Ground-Truth Verification Protocol is intellectual honesty: **never conceal operational uncertainties or empirical hypotheses behind documentation volume or synthetic green tests**.

While the architectural principles, contracts, and threat models of the AI Employee Platform have been thoroughly validated, several high-scale operational parameters, isolation boundaries, and channel constraints cannot be verified by source code reading alone. They require focused empirical benchmarking during Phase 2 prototype development.

This document explicitly catalogs these evidence gaps, their operational risks, and their planned empirical validation procedures.

---

## 2. Catalog of Empirical & Operational Evidence Gaps

### Gap 1: pgvector Multi-Tenant Index Partitioning at Scale
- **Subsystem:** Knowledge & Memory Subsystem (`pgvector`).
- **The Empirical Question:**
  Under high-volume multi-tenant loads (>1,000,000 vector chunks across 500 active tenants), does a single composite HNSW/IVFFlat index on `(tenant_id, embedding)` maintain sub-50ms query latency, or does PostgreSQL require native declarative table partitioning by `tenant_id`?
- **Operational Risk:**
  If a single global HNSW index is used with a tenant WHERE filter, pgvector's graph traversal can experience recall collapse and query latency degradation ($>500\text{ms}$) for smaller tenants whose vectors are sparse in the high-dimensional space.
- **Validation Plan (Phase 2 Prototype):**
  Construct a PostgreSQL 17 benchmark script using `pgvector` with 1,000,000 synthetic 1536-dimensional embeddings partitioned across 100 tenant IDs. Compare query latency and recall between:
  1. Single table with composite HNSW index + `SET LOCAL hnsw.ef_search = 100`.
  2. Declaratively partitioned tables (`knowledge_chunks_tenant_xxx`).

---

### Gap 2: Redis CFS Scheduler Token Bucket Recovery under Node Crash
- **Subsystem:** Concurrency, Queuing & Outbound Campaign Dispatch.
- **The Empirical Question:**
  If the Redis container or node terminates ungracefully during an active outbound marketing campaign (10,000 recipients across multiple tenants), does the Completely Fair Scheduler (CFS) token bucket algorithm reconstruct state from PostgreSQL outbox records without message duplication or tenant starvation?
- **Operational Risk:**
  If token bucket state is stored purely in Redis volatile memory, a restart could either cause all tenants to burst at maximum throughput (exceeding WhatsApp Cloud API rate limits and triggering number suspension) or stall dispatch entirely.
- **Validation Plan (Phase 2 Prototype):**
  Execute a chaos engineering test (`docker kill redis`) during a simulated 10,000-message outbound campaign. Measure token recovery time, ensure zero duplicate webhook dispatches, and verify that rate limit quotas resume smoothly.

---

### Gap 3: Sandbox Isolation Performance: UV Virtualenv vs MicroVM
- **Subsystem:** Autonomous Capability Generation & Sandboxed Tool Execution.
- **The Empirical Question:**
  What is the exact cold-start latency, memory overhead, and security isolation trade-off between ephemeral UV virtual environments (`uv venv`) and microVMs (e.g. Firecracker / gVisor) on local Windows development hosts vs cloud Linux production hosts?
- **Operational Risk:**
  If UV subprocess sandboxing is insufficient against sophisticated escape vectors, a compromised synthesized tool could read host environment variables. Conversely, if microVMs add $>300\text{ms}$ cold-start latency, tool execution becomes sluggish.
- **Validation Plan (Phase 2 Prototype):**
  Benchmark execution startup latency and memory footprint of 100 concurrent tool executions under:
  1. Ephemeral `uv venv` with restricted OS process tokens.
  2. Docker / container-based ephemeral runners.
  3. Linux namespace/cgroup isolation (`nsjail` / `gVisor`).

---

### Gap 4: Founder Telegram Rate-Limit Coalescing during Cascading Outages
- **Subsystem:** The Godfather Supervisory Guardian (`packages/godfather/`).
- **The Empirical Question:**
  What is the optimal aggregation window and deduplication threshold to prevent hitting the Telegram Bot API rate limit (30 messages per second platform-wide; 1 message per second to a single chat) when a cloud provider experiences a major cascading outage?
- **Operational Risk:**
  During an external outage (e.g. Gemini API returning HTTP 503 across 200 simultaneous customer conversations), an un-throttled Godfather could attempt to send hundreds of alerts to the founder's Telegram, triggering HTTP 429 rate limit blocks and leaving the founder blind to the incident.
- **Validation Plan (Phase 2 Prototype):**
  Implement an in-memory alert coalescing queue with a 5-second sliding window that collapses identical error signatures into a single summarized digest (e.g. *"P0 Alert: Provider Gemini 503 Outage affecting 142 turns in past 5s"*).

---

### Gap 5: AST Node Whitelist Boundaries for Python Code Synthesis
- **Subsystem:** Self-Development Verification Pipeline (Gate 1 AST Validator).
- **The Empirical Question:**
  What is the exact minimal AST whitelist that allows LLM-synthesized tools to perform necessary arithmetic, string formatting, dictionary lookups, and Pydantic model validation while mathematically guaranteeing that dynamic attribute access (`getattr`/`setattr`), `eval`, `exec`, `__import__`, `open`, `os`, and `socket` are strictly rejected?
- **Operational Risk:**
  An overly strict whitelist will cause the Dream Daemon to reject valid business calculation tools. An overly loose whitelist risks arbitrary code execution.
- **Validation Plan (Phase 2 Prototype):**
  Subject the Gate 1 AST parser to an automated adversarial fuzzing suite with 200 malicious and 200 benign synthetic Python tools to verify 100% true-negative rejection and $>95\%$ true-positive acceptance.

---

### Gap 6: WhatsApp 24-Hour Customer Service Window Expiration Flow
- **Subsystem:** Omni-Channel Connectors (`packages/connectors/whatsapp.py`).
- **The Empirical Question:**
  How does the conversation state graph handle inbound customer turns that arrive after Meta's 24-hour free-form customer service window has expired, where free-form replies return Meta Graph API error `#131047`?
- **Operational Risk:**
  If the agent attempts to reply with a standard free-form text message, Meta rejects the POST request, the OutboxWorker retries indefinitely, and the customer receives no response.
- **Validation Plan (Phase 2 Prototype):**
  Integrate an explicit window-expiry check in `WhatsAppConnector`. If `last_customer_message_timestamp > 24 hours`, route the response through an approved Meta Utility/Marketing Template Message asking the customer to re-open the session.

---

### Gap 7: High-Precision Decimal Serialization across ASGI and Frontend UI
- **Subsystem:** Dynamic Business Modules & Declarative Dashboards.
- **The Empirical Question:**
  How should 18-digit financial decimals (`DECIMAL(18, 4)`) be serialized over JSON HTTP boundaries so that standard JavaScript `JSON.parse()` on client browsers does not silently truncate significant digits due to IEEE 754 floating-point limitations?
- **Operational Risk:**
  JavaScript's `Number.MAX_SAFE_INTEGER` ($9,007,199,254,740,991$) causes large transaction totals or inventory balances to suffer rounding errors on tenant dashboards.
- **Validation Plan (Phase 2 Prototype):**
  Enforce ISO string decimal serialization in Pydantic v2 schemas (`field: Decimal = Field(..., decimal_places=4)` serialized as string `"1250000.5000"`). The frontend `DynamicFormRenderer` and data tables parse string decimals using `decimal.js` or `BigInt`.

---

## 3. Summary of Gap Resolution Timeline

| Evidence Gap | Resolution Phase | Verification Owner | Blocking Implementation? |
| :--- | :---: | :---: | :---: |
| **Gap 1: pgvector Partitioning** | Phase 2 Blueprint | Database Architect | No (Informs schema indexing) |
| **Gap 2: Redis CFS Recovery** | Phase 2 Prototype | Concurrency Specialist | No (Informs worker recovery logic) |
| **Gap 3: Sandbox MicroVM vs UV** | Phase 2 Benchmark | Security Engineer | No (UV used for Phase 2; MicroVM for Cloud) |
| **Gap 4: Telegram Rate Limiting** | Phase 2 Blueprint | Godfather Lead | No (Standard coalescing buffer pattern) |
| **Gap 5: AST Whitelist Fuzzing** | Phase 2 Prototype | Self-Development Lead | Yes (Blocks activating Dream Daemon in Prod) |
| **Gap 6: WhatsApp 24h Window** | Phase 2 Blueprint | Channel Specialist | No (Standard Meta Template Flow) |
| **Gap 7: Decimal Serialization** | Phase 2 Blueprint | Frontend Architect | Yes (Blocks financial module UI) |
