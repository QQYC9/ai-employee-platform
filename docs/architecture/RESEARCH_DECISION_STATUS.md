# Research Decision Status Register — Formal ADR Classification

**Document ID:** `RESEARCH_DECISION_STATUS`  
**Governing Standard:** Architectural Decision Governance Protocol (`/goal`)  
**Target Repository:** `QQYC9/ai-employee-platform` (Local Path: `d:\AI-Employee-Platform`)  
**Active Branch:** `checkpoint/phase-12-knowledge-base`  
**Verified Commit (HEAD):** `86c1abf609405bf170cd8a97212825acc107feb9`  
**Status:** **AUTHORITATIVE CLASSIFICATION AUDITED**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Summary & Governance Schema

This register documents the formal architectural status of all 15 Architectural Decision Records (ADR-01 through ADR-15) and five explicitly rejected design alternatives.

### Decision Classification Taxonomy
- **`APPROVED`**: Authoritatively accepted; backed by verified empirical evidence; binding on Phase 2 blueprinting.
- **`CONDITIONAL`**: Approved in principle; activation is strictly conditional upon satisfying defined operational prerequisites.
- **`PROPOSAL`**: Architectural recommendation under detailed design review.
- **`REJECTED`**: Formally evaluated and permanently discarded with recorded forensic rationale.

---

## 2. Master Status Matrix: ADR-01 through ADR-15

| Decision ID | Title | Status | Primary Evidence / Reference | Binding Conditions / Prerequisites |
| :--- | :--- | :---: | :--- | :--- |
| **`ADR-01`** | **Pregel StateGraph Runtime** | **`APPROVED`** | LangGraph Pregel (`langgraph/pregel/_loop.py`) | Max superstep ceiling (`MAX_SUPERSTEPS = 10`); strict channel isolation. |
| **`ADR-02`** | **Total Legacy Engine Replacement** | **`APPROVED`** | Forensic audit of `conversational_agent_engine.py` | 0% code carryover; complete deprecation of 5,291-line monolithic file. |
| **`ADR-03`** | **DB Connection Pool Release** | **`APPROVED`** | Dify source (`api/core/agent/fc_agent_runner.py`) | Serialize entities to Pydantic before closing DB session; re-open for commit. |
| **`ADR-04`** | **Distributed Fencing Tokens** | **`APPROVED`** | Distributed systems theory (Martin Kleppmann) | Two-Phase Staged Intent Pattern for external tools with side-effects. |
| **`ADR-05`** | **Handoff Hop Ceiling & Cycle Check** | **`CONDITIONAL`** | OpenAI Agents SDK (`openai-agents-python`) | Cap set to 5; subject to empirical calibration during Phase 2 multi-agent tests. |
| **`ADR-06`** | **Memory Learning Outcome Delta** | **`CONDITIONAL`** | RagLeap Core (`core/employees/learning.py`) | Learning delta $\Delta = 0.05$ requires retrieval stability validation across 20 turns. |
| **`ADR-07`** | **Skill Evolution Quarantining** | **`APPROVED`** | Memento-Skills 6-Gate Engine | Offline Dream Daemon execution only; strict quarantine until owner approval. |
| **`ADR-08`** | **Zero-Dependency License Policy** | **`APPROVED`** | Dify Modified Apache 2.0 & n8n SUL 1.0 audit | Clean-room implementation in Python 3.14/FastAPI; zero third-party package carryover. |
| **`ADR-09`** | **Dynamic Business Modules Storage** | **`APPROVED`** | PostgreSQL 17 JSONB & Decimal specifications | Zero runtime DDL; unified `business_entities` with native `DECIMAL(18, 4)`. |
| **`ADR-10`** | **Declarative UI Schema Engine** | **`APPROVED`** | Platform Vision (`docs/PROJECT_VISION.md` Sec 9) | `DynamicFormRenderer.tsx` with Zod validation and automated secret masking. |
| **`ADR-11`** | **The Godfather Authority Boundary** | **`APPROVED`** | Platform Vision (`docs/PROJECT_VISION.md` Sec 10) | Zero autonomous write authority; read-only telemetry; founder Telegram bot. |
| **`ADR-12`** | **Context-Bound Approvals & Replay** | **`APPROVED`** | RFC 8785 JCS + NIST SP 800-107 HMAC | RFC 8785 Canonical JSON hashing; row-level exclusive locks on consumption. |
| **`ADR-13`** | **Provider Idempotency Spectrum** | **`APPROVED`** | Meta Graph API & Twilio Messaging API docs | 4-tier spectrum; 60s quarantine for WhatsApp; zero automated retries on Twilio. |
| **`ADR-14`** | **Tamper-Evident Audit Chain** | **`APPROVED`** | RagLeap Core HMAC audit chaining | Append-only SHA-256 hash chaining; hourly root hash export to WORM storage. |
| **`ADR-15`** | **Authoritative Field Acceptance** | **`APPROVED`** | Platform Vision (`docs/PROJECT_VISION.md` Sec 1) | Live conversational Telegram sessions with the founder is sole proof of completion. |

---

## 3. Register of Formally Rejected Alternatives

### REJ-01: Incremental In-Place Refactoring of `conversational_agent_engine.py`
- **Proposed By:** Traditional incremental maintenance approach.
- **Status:** **`REJECTED`**
- **Rationale:**
  The forensic audit revealed 5,291 lines of tightly coupled logic, a single 1,701-line method (`_process_owner_message`), 42 brittle regular expressions, and disparate transaction commits. Over two months of previous development attempts resulted in circular regressions where fixing one conversational edge case broke another. Complete clean-room replacement is the only viable path to platform stability.

---

### REJ-02: Direct Code Carryover or Package Dependency on Dify or n8n
- **Proposed By:** Accelerated prototyping approach.
- **Status:** **`REJECTED`**
- **Rationale:**
  Dify's license contains a Modified Apache 2.0 Clause 1.a explicitly prohibiting multi-tenant SaaS commercialization. n8n's Sustainable Use License (SUL) 1.0 prohibits offering hosted workflow services to third parties. Importing either codebase creates severe legal and IP contamination risks. Clean-room native Python/FastAPI implementation is non-negotiable.

---

### REJ-03: Dynamic Runtime DDL (`CREATE TABLE` / `ALTER TABLE`) for Tenant Modules
- **Proposed By:** Dynamic relational database generation concept.
- **Status:** **`REJECTED`**
- **Rationale:**
  Executing DDL statements at runtime in a production multi-tenant PostgreSQL database acquires exclusive table locks, fragments database schema versions, risks catastrophic SQL injection, and prevents deterministic Alembic migration management. The Hybrid Relational-Dynamic Model (`business_entities` with GIN-indexed JSONB and native SQL decimals) provides full extensibility with zero runtime DDL.

---

### REJ-04: Granting The Godfather Direct Autonomous Write Permissions
- **Proposed By:** Fully autonomous self-healing platform concept.
- **Status:** **`REJECTED`**
- **Rationale:**
  Granting an LLM supervisory agent write permissions to production code files or database records violates zero-trust enterprise security. A single prompt injection or hallucination could alter platform rules across all tenants. The Godfather must remain an out-of-band analytical supervisor whose proposals require explicit founder confirmation.

---

### REJ-05: Synchronous Skill Evolution during Customer Conversations
- **Proposed By:** Real-time conversational self-expansion concept.
- **Status:** **`REJECTED`**
- **Rationale:**
  Running code synthesis, AST validation, UV virtual environment setup, and test execution through Memento's 6 gates takes between 10 and 60 seconds per capability. Executing this synchronously mid-conversation breaches the conversational response SLA ($< 3000\text{ms}$) and causes customer abandonment. Evolution must occur asynchronously via the offline Dream Daemon during idle hours.
