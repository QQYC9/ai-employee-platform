# Existing Execution Paths & Bottleneck Analysis

**Document ID:** `EXISTING_EXECUTION_PATHS`  
**Governing Workstream:** Workstream A & Workstream L (Execution Paths & Operations)  
**Target Repository:** `QQYC9/ai-employee-platform` (Local HEAD `86c1abf`)  
**Status:** **AUDITED & VERIFIED**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Summary & Flow Trace

This document forensically traces the complete lifecycle of an incoming customer message through the current codebase, mapping every handoff, state transition, database interaction, and asynchronous dispatch point.

It identifies the exact architectural points of failure that cause conversation corruption, database connection exhaustion, and infinite inquiry escalation loops in the legacy engine.

---

## 2. Forensic Step-by-Step Execution Trace (The Legacy Path)

```mermaid
sequenceDiagram
    autonumber
    participant Client as Telegram / WhatsApp API
    participant Caddy as Caddy 2 Reverse Proxy
    participant Webhook as apps/agent/api/v1/webhooks.py
    participant DB as PostgreSQL 17 Session
    participant LegacyEngine as conversational_agent_engine.py
    participant FactSvc as fact_service.py
    participant LLM as External AI Gateway (Gemini/OpenRouter)
    participant Outbox as packages/services/outbox_worker.py

    Client->>Caddy: POST /api/v1/webhooks/{channel}/{tenant_id}
    Caddy->>Webhook: Forward Request with Headers
    Webhook->>DB: Ingest Message & Create/Update Conversation
    Webhook->>LegacyEngine: Invoke process_inbound_message() (SYNCHRONOUS)
    Note over Webhook,LegacyEngine: CRITICAL BOTTLENECK 1: Webhook thread blocked; holds DB session
    LegacyEngine->>FactSvc: Query Facts via Regex Keyword Matching
    LegacyEngine->>LegacyEngine: Evaluate Regex Guardrails (_evaluate_reply_guardrails)
    Note over LegacyEngine: CRITICAL BOTTLENECK 2: False-positive regex triggers trigger inquiry loop
    LegacyEngine->>LLM: Stream Response via generate_response_stream()
    Note over LegacyEngine,LLM: CRITICAL BOTTLENECK 3: DB session held open for 5-15s during streaming
    LegacyEngine->>DB: Intermittent self.db.commit() (18 disparate points)
    LegacyEngine->>DB: Insert OutboxEvent (Status: PENDING)
    LegacyEngine-->>Webhook: Return Response
    Webhook-->>Client: 200 OK
    Outbox->>DB: Poll outbox_events via FOR UPDATE SKIP LOCKED
    Outbox->>Client: Dispatch Outbound Message to Channel API
```

---

## 3. The Three Catastrophic Failure Vectors in the Legacy Path

### 3.1 Failure Vector 1: Synchronous Webhook Ingress & Connection Starvation
- **Source Location:** `apps/agent/api/v1/webhooks.py` lines 85–140; `packages/services/conversational_agent_engine.py` line 210.
- **Observed Behavior:** Instead of decoupling inbound message ingestion from LLM turn execution via an in-memory or Redis task queue, the webhook endpoint calls `await engine.process_inbound_message()` inline.
- **Consequence:** The ASGI worker thread and the SQLAlchemy database connection remain checked out of the pool for the entire duration of the LLM round-trip (often 10+ seconds). Under 20 concurrent customer chats, the default PostgreSQL connection pool (`pool_size=20`) is 100% starved, causing incoming webhooks to time out and external providers (WhatsApp/Telegram) to aggressively retry, exacerbating the outage.

### 3.2 Failure Vector 2: Regex False-Positive Traps & Inquiry Hijacking
- **Source Location:** `packages/services/conversational_agent_engine.py` methods `_evaluate_reply_guardrails` and `_process_owner_message`.
- **Observed Behavior:** Guardrails attempt to evaluate whether an agent's planned response mentions working hours, cities, or pricing using crude regular expressions (e.g. searching for Arabic digits, `ساعة`, `الرياض`, `فروع`).
- **Consequence:** When an agent attempts to say "أهلاً بك، تفضل كيف أساعدك اليوم؟", the keyword `اليوم` or temporal terms trigger the working hours guardrail. The engine immediately intercepts the turn, creates an `OwnerInquiry`, and sends an escalation to the business owner asking for hours that are already documented! When the owner replies with "نعم" or "تمام", the regex parser misinterprets the text as an inquiry ID, entering an infinite loop.

### 3.3 Failure Vector 3: Fragmented Transactional Commits (Non-Atomic Execution)
- **Source Location:** Over 18 disparate `self.db.commit()` statements distributed across `conversational_agent_engine.py`, `fact_service.py`, and `owner_inquiry_service.py`.
- **Observed Behavior:** If an error occurs midway through a turn (e.g. a network timeout during tool execution), earlier database commits (such as saving partial memory facts or updating conversation states) remain permanently committed.
- **Consequence:** Conversation state becomes corrupt and desynchronized. The conversation cannot be rolled back to the start of the turn or retried cleanly.

---

## 4. The Target Decoupled Execution Path (Phase 5 Rebuild)

In the target Pregel StateGraph architecture:
1. **Instant Webhook Ingress (Sub-50ms):** Webhook verifies HMAC signature, writes message to DB, emits task ID to Redis CFS queue, and returns `HTTP 200 OK` in < 30ms.
2. **Worker Pool Decoupling:** Separate async worker processes claim tasks from Redis.
3. **Database Connection Release:** Worker claims task, loads memory/checkpoint, commits, and explicitly **closes the database session** before initiating the slow LLM streaming call (ADR-03 / Dify pattern).
4. **Deterministic Turn Execution:** Turns execute through a bounded Pregel state graph (`MAX_SUPERSTEPS=10`). State transitions are formal graph edges, not regex string matches.
5. **Atomic Final Commit:** Upon turn completion, a fresh database transaction commits the execution checkpoint and outbox event in a single atomic ACID block.
