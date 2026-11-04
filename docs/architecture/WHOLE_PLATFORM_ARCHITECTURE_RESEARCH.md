# Whole-Platform Architecture Research — Enterprise Digital Employee Operating System

**Document ID:** `WHOLE_PLATFORM_ARCHITECTURE_RESEARCH`  
**Governing Workstream:** Master Platform Synthesis (Workstreams A through M)  
**Governing Vision:** `docs/PROJECT_VISION.md` (November 2026 Platform Vision Charter)  
**System Designation:** AI Employee Platform (Next-Generation Unified Architecture)  
**Target Repository:** `QQYC9/ai-employee-platform` (Local HEAD `86c1abf`)  
**Status:** **AUDITED & VERIFIED**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Charter: The Platform is the Product

The AI-Employee-Platform is fundamentally **not** a conversational chatbot engine, nor is it an LLM prompt wrapper. It is an **Enterprise Multi-Tenant Digital Employee Operating System**.

Its mission is to empower businesses to autonomously provision, configure, operate, supervise, and continuously evolve specialized digital employees that perform real business workflows, maintain long-term institutional memory, interact across omni-channel connectors, and execute sensitive tools under strict human-in-the-loop governance.

---

## 2. Platform Subsystem Decomposition & Interaction Topology

The platform architecture is structured into 7 decoupled, interoperating subsystems:

```mermaid
flowchart TD
    subgraph S1["Subsystem 1: Edge Ingress & Channel Layer"]
        CADDY["Caddy 2 Reverse Proxy (Auto SSL, Rate Limiting)"]
        CONNECTORS["Omni-Channel Adapters (Telegram, WhatsApp, Webhooks, Email)"]
        CADDY --> CONNECTORS
    end

    subgraph S2["Subsystem 2: API Gateway & Dynamic UI Engine"]
        FASTAPI["FastAPI ASGI Core (/api/v1)"]
        AUTH_SCOPE["JWT Auth & Immutable Scope Injector"]
        UI_ENGINE["Declarative Dynamic UI Schema Compiler"]
        DASHBOARDS["Tenant & Admin React Dashboards"]
        FASTAPI --> AUTH_SCOPE
        FASTAPI --> UI_ENGINE
        UI_ENGINE --> DASHBOARDS
    end

    subgraph S3["Subsystem 3: Deterministic Pregel Runtime Engine"]
        DISPATCHER["Task Dispatcher & Concurrency Fencer"]
        STATEGRAPH["Pregel StateGraph Turn Loop (MAX_SUPERSTEPS=10)"]
        HANDOFF_ROUTER["Handoff Router (input_filter, DAG Cycle Prevention)"]
        CHECKPOINTER["Superstep Checkpointer (Atomic PostgreSQL Commits)"]
        DISPATCHER --> STATEGRAPH
        STATEGRAPH --> HANDOFF_ROUTER
        STATEGRAPH --> CHECKPOINTER
    end

    subgraph S4["Subsystem 4: Knowledge, Memory & Tool Sandboxing"]
        MEMORY_5TIER["5-Tier Memory (Buffer, Checkpoint, Scoped Fact, Semantic, Skill)"]
        TOOL_WRAPPER["Tool Execution Wrapper (Pydantic extra='forbid')"]
        UV_SANDBOX["UV Virtualenv Isolated Process Sandbox"]
        TOOL_WRAPPER --> UV_SANDBOX
    end

    subgraph S5["Subsystem 5: Autonomous Platform Self-Development"]
        DREAM_DAEMON["Offline Dream Daemon (Idle Cycle Orchestrator)"]
        MEMENTO_6GATE["Memento-Skills 6-Gate Verification Pipeline"]
        CAPABILITY_CATALOG["Global & Tenant Capability Catalog"]
        DREAM_DAEMON --> MEMENTO_6GATE
        MEMENTO_6GATE --> CAPABILITY_CATALOG
    end

    subgraph S6["Subsystem 6: The Godfather Supervisory Guardian"]
        GUARDIAN_DAEMON["Out-of-Band Telemetry & Audit Stream Consumer"]
        ROOT_CAUSE_ENGINE["Cross-Correlation & Anomaly Classifier"]
        FOUNDER_TELEGRAM["Dedicated Founder Telegram Bot (Emergency Paging & 21:00 Digest)"]
        GUARDIAN_DAEMON --> ROOT_CAUSE_ENGINE
        ROOT_CAUSE_ENGINE --> FOUNDER_TELEGRAM
    end

    subgraph S7["Subsystem 7: Storage, Scheduling & Async Outbox Tier"]
        PG_DB[("PostgreSQL 17 + pgvector (Hybrid business_entities)")]
        REDIS_CFS[("Redis 7 (Completely Fair Scheduler & Rate Limits)")]
        OUTBOX_WORKER["Transactional OutboxWorker (SKIP LOCKED, 4-Tier Idempotency)"]
        WAIT_TRACKER["n8n-Style WaitTracker (Level 2 Approval Suspension)"]
    end

    S1 --> S2
    S2 --> S7
    S7 --> S3
    S3 --> S4
    S4 --> S7
    S3 --> S7
    S7 --> S1
    S7 --> S6
    S7 --> S5
    S5 --> S7
```

---

## 3. Core Architectural Guarantees

### 3.1 Zero-Starvation Database Connection Preservation (ADR-03)
- Discovered and verified in Dify (`fc_agent_runner.py`).
- Workers claim tasks and load context, then explicitly **commit and close the SQLAlchemy session** before awaiting external streaming LLM responses.
- Eliminates the connection starvation failure mode where 20 simultaneous conversations exhaust the pool for 15+ seconds.

### 3.2 Monotonic Concurrency Fencing & Distributed Leases (ADR-04)
- Implements Martin Kleppmann's distributed locking standard (`REF-DIST-FENCE`).
- Every worker claim increments `fence_token = fence_token + 1` with row-level locking (`UPDATE execution_tasks ... FOR UPDATE SKIP LOCKED`).
- If a slow worker awakens after its lease expires (`locked_until < NOW()`), its delayed commit is rejected because its fence token is stale.

### 3.3 Four-Tier Tenant Defense-in-Depth (ADR-01)
- Tier 1: Immutable `Scope(tenant=..., agent=..., session=...)` passed across all async worker threads.
- Tier 2: `BaseRepository` automatically injects `WHERE tenant_id = scope.tenant` into every SQL statement.
- Tier 3: Relational composite primary keys `PRIMARY KEY (tenant_id, id)` ensure cross-tenant queries fail at the PostgreSQL engine level.
- Tier 4: Dynamically generated tools execute in isolated UV virtual environments with stripped parent environment variables.

### 3.4 Hybrid Dynamic Entity Storage (ADR-06)
- Digital employees can provision custom business modules (sales, invoices, inventory, stock) without dangerous runtime DDL.
- Persisted in the unified `business_entities` table featuring typed native financial decimals (`DECIMAL(18, 4)`) and GIN-indexed `dynamic_attributes JSONB`.

### 3.5 The Ground-Truth Protocol (ADR-10)
- Explicitly rejects the "Green Test Delusion" where synthetic pytest passes mask live conversational failures.
- Automated unit, integration, and security tests are necessary gates, but live conversation and task execution via **Telegram** with the platform founder is the sole authoritative acceptance standard.
