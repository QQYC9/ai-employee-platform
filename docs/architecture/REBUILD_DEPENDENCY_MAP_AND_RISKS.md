# Rebuild Dependency Map, Technical Risks & Mitigation Strategies

**Document ID:** `REBUILD_DEPENDENCY_MAP_AND_RISKS`  
**Governing Standard:** Full-Platform Target Vision (`docs/PROJECT_VISION.md` Sections 18, 19, 20)  
**Target Repository:** `QQYC9/ai-employee-platform`  
**Status:** **AUTHORITATIVE REBUILD ROADMAP**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Phased Rebuild Sequence & Transition Milestones

To ensure zero downtime, preserve data integrity, and eliminate legacy technical debt without regressions, the rebuild is organized into nine sequential phases:

```mermaid
flowchart TD
    P1[Phase 1: Research, Specifications & Blueprint Sign-Off] --> P2[Phase 2: Relational DDL, Models & Fencing Infrastructure]
    P2 --> P3[Phase 3: Pregel StateGraph Runtime Engine]
    P2 --> P4[Phase 4: Declarative UI Engine & Dashboard Renderers]
    P3 --> P5[Phase 5: 5-Tier Memory & Scoped Fact Subsystem]
    P3 --> P6[Phase 6: Capability & Agent Generation Engine / Dream Daemon]
    P3 --> P7[Phase 7: The Godfather Supervisory Guardian & Telegram Link]
    
    P4 --> P8[Phase 8: Legacy Engine Exciser Protocol (Delete engine.py)]
    P5 --> P8
    P6 --> P8
    P7 --> P8
    
    P8 --> P9[Phase 9: Authoritative Ground-Truth Telegram Verification Gate]
```

### Detailed Phase Specifications
1. **Phase 1: Research, Specifications & Blueprint Sign-Off (Current Milestone):**
   - Forensic teardown of 7 reference codebases.
   - Comprehensive architectural specifications, ADRs, matrices, and safety audit reports.
   - Formal founder authorization gate.
2. **Phase 2: Relational DDL, Models & Fencing Infrastructure:**
   - Author Alembic migration creating `execution_tasks`, `execution_checkpoints`, `approval_requests`, `business_entities`, `ui_interface_declarations`, `fact_entities`, and `audit_events`.
   - Implement immutable `Scope` and base repository scoping.
3. **Phase 3: Pregel StateGraph Runtime Engine:**
   - Implement `packages/engine/runtime.py` running bounded superstep iterations.
   - Implement Database Connection Pool Preservation (release session before LLM streaming).
   - Wire monotonic fencing tokens and row-level lease acquisition.
4. **Phase 4: Declarative UI Engine & Dashboard Renderers:**
   - Implement `DynamicFormRenderer.tsx` in `apps/tenant-dashboard` and `apps/admin-dashboard`.
   - Register declarative UI schema API endpoints (`/api/v1/ui-schemas`).
5. **Phase 5: 5-Tier Memory & Scoped Fact Subsystem:**
   - Deploy multi-dimensional scoped facts (spatial, temporal, audience).
   - Deploy fact supersession and contradiction escalation state machine.
   - Deploy PII statutory erasure lifecycle and pgvector hybrid RAG.
6. **Phase 6: Autonomous Capability & Agent Generation Engine:**
   - Deploy the offline **Dream Daemon** running Memento-Skills' 6-Gate verification pipeline in isolated UV sandboxes.
   - Implement hybrid relational/JSONB storage for dynamic business modules (`business_entities`).
7. **Phase 7: The Godfather Supervisory Guardian & Telegram Integration:**
   - Deploy `godfather_daemon` consuming telemetry streams from PostgreSQL/Redis.
   - Implement real-time critical error alerting and the 21:00 Evening Health Digest to founder Telegram.
8. **Phase 8: Legacy Engine Total Exciser Protocol:**
   - Permanently excise `packages/services/conversational_agent_engine.py` (0% code carryover).
   - Update `apps/agent/main.py` router bindings to the Pregel engine.
   - Execute clean-cutover test suites.
9. **Phase 9: Authoritative Ground-Truth Telegram Verification Gate:**
   - Real, live conversational testing between the platform founder and digital employees via Telegram.
   - Final milestone sign-off.

---

## 2. Technical Risk Register & Mitigation Matrix

| # | Technical Risk Description | Severity | Likelihood | Impact on System | Engineering Mitigation Strategy |
| :-: | :--- | :---: | :---: | :--- | :--- |
| **R1** | **Distributed Concurrency Split-Brain / Stale Worker Commit** | High | Medium | Corrupt execution checkpoints; duplicate outbox events. | **Enforced in ADR-04 & Section 5.3:** Monotonic fencing tokens (`fence_token`) verified inside atomic commit transactions; row-level exclusive lock on `execution_tasks` with `statement_timeout = '5s'` and `lock_timeout = '2s'`. |
| **R2** | **Dynamic Code Synthesis Security Vulnerabilities (RCE)** | Critical | Low | Synthesized tool attempts unauthorized filesystem, network, or OS access. | **Enforced in ADR-07 & Section 10:** Memento-Skills 6-Gate pipeline: AST static import scanning (prohibiting os, sys, subprocess, socket), isolated UV sandboxing, and mandatory human authorization gate before production activation. |
| **R3** | **External API Ambiguity Window (Network Timeouts)** | High | High | Blind retries cause duplicate credit card charges or duplicate customer messages. | **Enforced in ADR-13 & Section 5.5:** 4-Tier Idempotency Spectrum. Strict prohibition of blind retries on Tier 3 endpoints; 15-minute status webhook quarantine window for WhatsApp outbound messages. |
| **R4** | **Database Connection Pool Exhaustion under Heavy Load** | High | High | Inbound webhooks rejected with `QueuePool limit exceeded`. | **Enforced in ADR-03 & Section 12.1:** Dify connection pool preservation pattern: commit and close SQLAlchemy sessions immediately before awaiting LLM streaming chunks. |
| **R5** | **Memory Retrieval Volatility & Hallucinated Conflicts** | Medium | Medium | Agent hallucinates conflicting facts or forgets business operating hours. | **Enforced in Section 9:** Multi-dimensional scoped facts (spatial, temporal, audience) with explicit `SUPERSEDED` status linking and automatic escalation to owner for unresolved contradictions. |
| **R6** | **Third-Party Open-Source License Contamination** | High | Low | Legal liability or multi-tenant commercial SaaS distribution restrictions. | **Enforced in ADR-08:** Zero-dependency policy on Dify (Modified Apache 2.0) and n8n (SUL 1.0) source code and packages; clean native Python re-implementation. |
| **R7** | **Noisy-Neighbor Queue Starvation** | Medium | Medium | Large tenant outbound marketing campaigns starve interactive customer chat. | **Enforced in Section 12.2:** Segregated worker queues (`interactive_queue` prioritized over `campaign_queue`) + Completely Fair Scheduler (CFS) with Redis token buckets per tenant. |
| **R8** | **Synthetic Green Test Delusion / Real Runtime Regression** | Critical | High | Platform passes automated unit tests but fails catastrophically during live customer conversation. | **Enforced in ADR-15 & Section 17:** The Ground-Truth Protocol: mandatory real, live Telegram conversational sessions with the founder as the authoritative release acceptance gate. |

---

## 3. Unresolved Questions & Empirical Calibration Register

The following parameters are designated as **`HYPOTHESIS`** or **`OPEN`** in the architecture, scheduled for empirical calibration during Phase 2:

| Parameter / Question | Current Baseline Value | Methodological Status | Calibration Target & Measurement Plan |
| :--- | :---: | :---: | :--- |
| `config.WORKER_LEASE_DURATION` | `30s` | **`HYPOTHESIS`** | Measure worker GC pauses and network latency in staging under 100 concurrent turns. |
| `config.WORKER_HEARTBEAT_INTERVAL` | `10s` | **`HYPOTHESIS`** | Verify that 10s heartbeats prevent false-positive lease expirations without database lock contention. |
| `config.MAX_HANDOFF_HOPS` | `5` | **`HYPOTHESIS`** | Benchmark 10 complex multi-department business scenarios to evaluate truncation risk. |
| `config.MEMORY_LEARNING_DELTA` | `0.05` | **`HYPOTHESIS`** | Run 20 positive and negative simulated dialogue cycles to measure retrieval stability. |
| `config.SKILL_UTILITY_THRESHOLD` | `0.2` | **`HYPOTHESIS`** | Evaluate error frequency and repair triggers across 50 generated skills. |
| `config.SKILL_MIN_EVAL_RUNS` | `20` | **`HYPOTHESIS`** | Verify statistical significance before triggering automated deprecation. |
| `config.TOOL_DEFAULT_TIMEOUT` | `10s` | **`HYPOTHESIS`** | Profile 95th percentile latency of external API integrations. |
| `config.TOOL_HEAVY_QUERY_TIMEOUT`| `30s` | **`HYPOTHESIS`** | Measure PostgreSQL analytical query latency across 100,000 records. |
| `config.REDIS_CHECKPOINT_SWITCH` | `50ms` | **`OPEN`** | Profile PostgreSQL direct checkpoint insert latency; introduce Redis write-back buffer only if write latency exceeds 50ms. |
