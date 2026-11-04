# Repository Coverage Ledger — Codebase Inventory & Rebuild Disposition

**Document ID:** `REPOSITORY_COVERAGE_LEDGER`  
**Governing Workstream:** Workstream A & Workstream I  
**Target Repository:** `QQYC9/ai-employee-platform`  
**Status:** **AUDITED & DISPOSITIONED**  
**Date:** 2026-11-04  
**Auditor / Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Summary & Inventory Scope

This document provides a forensic inventory of all packages, modules, models, and service layers within `d:\AI-Employee-Platform`. Each existing component has been evaluated against the target platform vision defined in `docs/PROJECT_VISION.md` and the master blueprint in `docs/architecture/MASTER_ARCHITECTURE_BLUEPRINT.md`.

Components are categorized into four authoritative architectural dispositions:
1. **PRESERVE:** Core domain assets, multi-tenant isolation foundations, cryptographic utilities, channel connectors, and stable relational schemas to be carried forward into the next-generation engine.
2. **REPLACE:** Functionally necessary business capabilities whose current implementations suffer from structural defects (e.g., monolithic loops, lack of state machines, connection leaks, regex-based guards).
3. **REMOVE:** Symptomatic workarounds, brittle ad-hoc patches, and dead code that must be excised completely (0% code carryover).
4. **NEW REQUIRED:** Novel architectural components required by the target vision (The Godfather supervisor, dynamic business module provisioning, schema-driven declarative UI engine, Pregel state loop, UV sandbox evolution).

---

## 2. Package-Level Architectural Inventory & Disposition Matrix

| Subsystem / Path | Primary Files & Responsibilities | Current Implementation Analysis | Target Disposition | Rationale & Migration Strategy |
| :--- | :--- | :--- | :---: | :--- |
| **`apps/agent/main.py`** | FastAPI app initialization, middleware, `/api/v1` router mount. | Standard FastAPI entry point. Mounts routers cleanly. | **PRESERVE (Update)** | Update router bindings to point to the new Pregel StateGraph engine; preserve CORS and error handlers. |
| **`apps/agent/api/v1/`** | 28 endpoint routers (`agents.py`, `channels.py`, `campaigns.py`, `auth.py`, `tasks.py`, `webhooks.py`, `self_development.py`, etc.) | Well-structured REST contracts using Pydantic v2. | **PRESERVE (Extend)** | Retain API contracts; add endpoints for declarative UI schema generation (`/ui-schemas`) and Godfather telemetry (`/godfather/telemetry`). |
| **`packages/models/`** | SQLAlchemy domain models (`tenant.py`, `domain.py`, `customer.py`, `campaign.py`, `outbox.py`) | Solid relational schema with UUIDv7, tenant foreign keys, and JSONB fields. | **PRESERVE (Extend)** | Extend with `execution_tasks`, `execution_checkpoints`, `approval_requests`, `business_entities`, and `ui_declarations`. |
| **`packages/auth/`** | JWT authentication, RBAC dependencies, `get_tenant_context`, `get_current_user`. | Enforces HS256 JWT tokens and tenant isolation on incoming requests. | **PRESERVE** | Keep auth contracts intact; extend `Scope` to enforce immutable dataclass propagation across all worker threads. |
| **`packages/core/`** | Configuration (`config.py`), database session engine (`database.py`), AES-256-GCM crypto (`crypto.py`). | Robust authenticated encryption for tenant integration secrets. | **PRESERVE** | Retain AES-256-GCM secrets management; add RFC 8785 canonical JSON serializer and HMAC approval signing keys. |
| **`packages/connectors/`** | WhatsApp Cloud API, Telegram Bot, Email (SMTP), Generic Webhooks. | Functional omni-channel connectors; message normalization. | **PRESERVE (Refine)** | Integrate Microsoft Agent Framework UTF-16 code unit chunking for Telegram; integrate WhatsApp `biz_opaque_callback_data`. |
| **`packages/tools/`** | Tool registry, Pydantic schemas, sandboxed execution wrapper. | Initial tool registry structure. | **PRESERVE (Extend)** | Adopt strict Pydantic v2 contracts (`extra="forbid"`) and integrate with Memento-Skills 6-gate evolution pipeline. |
| **`packages/memory/`** | Entity memory extraction, vector embeddings. | Initial memory extraction service. | **REPLACE** | Replace with 5-Tier Memory Architecture (Working Buffer, Execution Checkpoint, Fact Memory, Semantic RAG, Skill Memory). |
| **`packages/context/`** | Prompt construction, context retriever. | Assembles monolithic system prompts. | **REPLACE** | Replace with dynamic context assembly that enforces boundary filtering (`input_filter`) and untrusted input scoping (`<untrusted_input>`). |
| **`packages/ai_providers/`** | `factory.py`, `resilient_provider.py`, Gemini, OpenRouter, Mock providers. | Multi-provider fallback chain with retry logic. | **PRESERVE** | Provider abstraction is functional; ensure all streaming calls release database sessions immediately before awaiting HTTP chunks. |
| **`packages/services/conversational_agent_engine.py`** | Monolithic while-loop conversational engine (1,500+ lines). | Suffers from point-fixing ("whack-a-mole" regex patching), state corruption, and connection starvation. | **REMOVE / REPLACE** | **Total Exciser Protocol (0% code carryover).** Replaced by Pregel StateGraph Runtime (`packages/engine/runtime.py`). |
| **`packages/services/conversation_fsm_service.py`** | Untracked finite state machine draft. | Initial state machine attempting to patch regex conflicts. | **REMOVE** | Excised; state transitions are modeled natively within the Pregel turn resolution graph. |
| **`packages/services/fact_service.py`** | Business facts persistence and conflict resolution. | Relies on regex keyword mapping for working hours and cities; premature DB commits. | **REPLACE** | Replace with Scoped Fact Service enforcing dimensional metadata, supersession tracking, and contradiction escalation. |
| **`packages/services/owner_inquiry_service.py`** | Escalation loop for business owner inquiries. | Mixes conversational regex parsing with inquiry resolution; vulnerable to number hijacking. | **REPLACE** | Replace with Approval and Inquiry Subsystem bound to cryptographic approval requests and FSM states. |
| **`packages/services/outbox_worker.py`** | Transactional outbox worker polling `outbox_events` with `FOR UPDATE SKIP LOCKED`. | Proven reliable async delivery pattern. | **PRESERVE (Harden)** | Retain `SKIP LOCKED` polling; integrate the Extensible Provider Idempotency Matrix (Tiers 1, 2A, 2B, 3). |
| **`packages/services/campaign_service.py`** | Outbound marketing campaign lifecycle and audience filtering. | Fully verified in Phase 4D (`9/9` tests passing). | **PRESERVE** | Retain campaign lifecycle; link to CFS rate-limited worker queue. |
| **`packages/self_development/`** | Tool verification, sandbox, external knowledge, learning engine. | Early prototype of dynamic tool generation. | **REPLACE (Upgrade)** | Re-architect into the offline **Dream Daemon** utilizing Memento-Skills' 6-Gate verification pipeline in isolated UV virtualenvs. |
| **`apps/tenant-dashboard/`** | React 18, Vite 5, TS 5 portal for tenant business owners. | 8 functional routes (`/`, `/agents`, `/tasks`, `/channels`, `/campaigns`, `/usage`, `/settings`, `/login`). | **PRESERVE (Extend)** | Extend with the Declarative Schema Form Renderer (`DynamicFormRenderer.tsx`) to auto-render generated capability interfaces. |
| **`apps/admin-dashboard/`** | React 18, Vite 5, TS 5 portal for platform administrators. | 7 functional routes (`/`, `/tenants`, `/agents-tasks`, `/monitoring`, `/integrations`, `/settings`, `/login`). | **PRESERVE (Extend)** | Extend with Global Capability Registry, Godfather Telemetry Monitor, and System-Level Declarative Form Renderer. |
| **`NEW: packages/engine/`** | Next-generation Pregel StateGraph runtime. | Does not exist in legacy code. | **NEW REQUIRED** | Implements bounded turn resolution, multi-agent handoffs, superstep checkpoints, and monotonic fencing tokens. |
| **`NEW: packages/godfather/`** | The Godfather (Guardian) supervisory daemon. | Does not exist in legacy code. | **NEW REQUIRED** | Out-of-band telemetry consumer, anomaly detector, evening health digest generator, connected to founder Telegram. |
| **`NEW: packages/ui_engine/`** | Declarative configuration-interface registry & compiler. | Does not exist in legacy code. | **NEW REQUIRED** | Validates and serves declarative UI schemas for generated capabilities and tools across both dashboards. |

---

## 3. Detailed Component Retirement Plan

### 3.1 The Legacy Conversational Engine Exciser Protocol
The legacy engine (`packages/services/conversational_agent_engine.py`) and its associated ad-hoc patches represent the architectural root cause of the platform's stability crisis. As established in `docs/PROJECT_VISION.md` Section 1, attempting to patch this file has created an endless regression loop:
1. Regex-based reply guardrails (`_evaluate_reply_guardrails`) attempt to parse natural language rules using string matching, leading to catastrophic false-positives (e.g. treating "يوم" or "الساعة 10" as cities or inquiry IDs).
2. The turn execution loop holds database transactions open across external LLM network calls, creating connection pool starvation under concurrent load.
3. Multiple sub-services call `self.db.commit()` unpredictably (over 18 disparate commit points across `engine.py`, `fact_service.py`, and `owner_inquiry_service.py`), destroying transactional atomicity.

**Retirement Action:**  
- The file will be marked `DEPRECATED` during Phase 1.
- In Phase 3/4, the file will be deleted entirely (0% code carryover).
- Zero backward-compatibility shims will be maintained.
