# Skill Orchestration Register — AI-Employee-Platform Full Rebuild

**Document ID:** `SKILL_ORCHESTRATION_REGISTER`  
**System Designation:** AI Employee Platform (Full-Platform Target Architecture)  
**Governing Skill:** `/goal` (Long-Running Autonomous Mission Management)  
**Status:** **ACTIVE & VERIFIED**  
**Date:** 2026-11-04  
**Auditor / Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Summary & Discovery Methodology

In strict compliance with **Section 1 (Mandatory Skill Discovery and Orchestration)** of the platform rebuild directive, this register documents the actual, verified skills discovered in the current Antigravity environment.

Every skill listed below has been:
1. Discovered in the environment paths (`.agents/skills/`, builtin skills, plugin skills).
2. Forensically inspected via its `SKILL.md` instruction file.
3. Mapped to its specific research workstream and mission role.
4. Assigned an exact invocation mechanism and operational boundaries.
5. Evaluated for its contributions, outputs, and known limitations.

No skill names are fabricated. No uninstalled skills are assumed. Source-code evidence and verified repository data take precedence over any skill assertion.

---

## 2. Discovered Skills Inventory & Orchestration Matrix

| Skill Name | Canonical Path | Invocation Mechanism | Mission Role & Workstream | Input Data | Expected Output | Validation Method | Known Limitations |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`/goal`** | Builtin Slash Command / Protocol | User Prompt Header `/goal` & Mission Ledger Protocol | **Primary Mission Manager**: Maintains progress ledger, tracks 13 workstreams (A–M), coordinates skills, prevents premature termination, enforces acceptance criteria. | Platform Vision (`docs/PROJECT_VISION.md`), user directive, repository state. | Coordinated multi-workstream architecture specification & acceptance report. | Verification of 25 acceptance criteria across all deliverables. | Operates at the meta-coordination level; relies on domain skills for deep code and systems analysis. |
| **`autonomous-page-testing`** | `d:\AI-Employee-Platform\.agents\skills\autonomous-page-testing\SKILL.md` | `python scripts/test_dashboard_runner.py --suite [smoke\|routes\|auth\|components]` | **Workstream K (Dashboard Architecture)**: Audits existing routes in `tenant-dashboard` and `admin-dashboard`, verifies role boundaries, and establishes declarative UI manifests. | Dashboard source files (`apps/*-dashboard/src/`), route manifests, mock auth tokens. | Discovered route inventory, component test reports, declarative UI schema specs. | Vitest + JSDOM headless execution and Vite build compilation (`npm run build`). | Scoped to current static frontend implementations; requires declarative engine extension for dynamic forms. |
| **`supabase-postgres-best-practices`** | `<user_home>/.gemini\config\plugins\supabase\skills\supabase-postgres-best-practices\SKILL.md` | Skill guidelines reference (`query-`, `conn-`, `lock-`, `schema-`, `security-`) | **Workstream C & I (Concurrency, Locking & Storage)**: Governs PostgreSQL 17 lease concurrency, `SET LOCAL lock_timeout`, fencing token verification, connection pool release, and pgvector schemas. | Database models (`packages/models/`), SQLAlchemy session lifecycles, SQL commit queries. | Fencing SQL transactions, connection release patterns, indexing strategy. | Forensic code review against PostgreSQL 17 locking and isolation specifications. | Specific Supabase cloud tooling (e.g. pg_net, Supabase Vault) adapted to self-hosted PostgreSQL/Redis. |
| **`build-agents`** | `<user_home>/.gemini\config\plugins\vercel-plugin\skills\build-agents\SKILL.md` | Skill pattern guidelines | **Workstream D & H (Agent Composition & Runtime)**: Informs durable agent execution, tool-calling loops, multi-agent handoffs, and background daemon lifecycles. | Agent blueprints, tool registries, handoff contracts. | Pregel-compatible turn resolution loop, supervisor architecture. | Alignment with OpenAI Agents SDK and LangGraph state machines. | Vendor-neutral adoption: platform engine is written natively in Python/FastAPI, avoiding external framework lock-in. |
| **`chat-sdk`** | `<user_home>/.gemini\config\plugins\vercel-plugin\skills\chat-sdk\SKILL.md` | Skill adapter patterns | **Workstream D & L (Omni-Channel Connectors & Protocols)**: Guides multi-platform message ingestion, Telegram bot API chunking, WhatsApp webhook normalization, and card/form schemas. | Channel connectors (`packages/connectors/`), Telegram/WhatsApp payload schemas. | Standardized channel message contracts, UTF-16 chunking rules, webhook idempotency. | Unit tests measuring UTF-16 code units with astral emojis; payload idempotency tests. | Designed primarily for TypeScript; core principles ported cleanly to Python 3.14 / Pydantic v2. |
| **`create-a-backend`** | `<user_home>/.gemini\config\plugins\vercel-plugin\skills\create-a-backend\SKILL.md` | Workload architectural matching | **Workstream I & J (Backend Architecture & Workload Decoupling)**: Matches workloads (webhooks, long-running agent inference, scheduled campaigns, offline dream daemons) to runtime patterns. | Core API routes, Outbox workers, Celery background tasks. | Decoupled four-tier architecture: Ingestion, Gateway, Pregel Engine, Outbox/Worker Tier. | Concurrency profiling and architectural review under simulated load. | Must account for on-premise Docker Compose deployment rather than serverless-only Vercel Functions. |
| **`react-best-practices`** | `<user_home>/.gemini\config\plugins\vercel-plugin\skills\react-best-practices\SKILL.md` | Performance and component rules | **Workstream K (Dynamic Dashboard Rendering)**: Informs declarative form rendering, elimination of client-side request waterfalls, and state-preserving modal interactions. | React component trees (`apps/*-dashboard/src/components/`). | Dynamic Schema Form Renderer component specification (Zero-Waterfalls, Strict Typing). | TypeScript compilation check (`tsc --noEmit`) and bundle analyzer profiling. | Focuses on client runtime performance; does not define backend schema storage (governed by Pydantic). |
| **`verification`** | `<user_home>/.gemini\config\plugins\vercel-plugin\skills\verification\SKILL.md` | Full-Story Verification Protocol | **Workstream M (Architectural Review & Ground Truth)**: Enforces end-to-end full-story verification: channel ingress → auth & scope → state graph → data persistence → outbox dispatch. | Inbound channel events, database states, outbox records, outbound messages. | Ground Truth Verification Matrix, Telegram Acceptance Test Protocol. | Live conversational verification with platform founder via Telegram. | Cannot be substituted by synthetic unit test passes ("Green Test Delusion" prohibition). |
| **`google-antigravity-sdk`** | `<user_home>/.gemini\config\plugins\google-antigravity-sdk\skills\google-antigravity-sdk\SKILL.md` | Agent Composition & Tool Contracts | **Workstream J & L (Agent Composition & Tool Contracts)**: Guides agent definition, tools declaration, multi-agent conversational connections, and resilient AI provider fallbacks. | Provider factory (`packages/ai_providers/`), tool definitions (`packages/tools/`). | Strict Tool Contract specification, ResilientProvider fallback chain. | Provider failover simulation and schema validation tests. | Hosted vs local model trade-offs; must support OpenRouter, Gemini, and Groq abstractions. |

---

## 3. Workstream to Skill Mapping Register

| Workstream | Workstream Title | Primary Governing Skill | Supporting Skills & Tools | Required Inputs | Expected Key Deliverables |
| :---: | :--- | :--- | :--- | :--- | :--- |
| **A** | Repository & Historical Research Recovery | `/goal` | Git CLI, `read_file`, `run_command` | `docs/audit/`, `docs/architecture-research/`, Git commit history. | `00_RESEARCH_PROGRESS_LEDGER.md`, `REPOSITORY_COVERAGE_LEDGER.md`. |
| **B** | Memento-Skills & Memory Architecture | `/goal` | `build-agents`, `supabase-postgres-best-practices` | `D:\AI-Employee-Platform-Research\memento-skills`, `01_MEMENTO_SKILLS_DEEP_DIVE.md` | `TOOL_AND_SKILL_ARCHITECTURE.md`, 6-Gate Evolution Engine. |
| **C** | LangGraph & Execution Orchestration | `/goal` | `build-agents`, `supabase-postgres-best-practices` | `D:\AI-Employee-Platform-Research\langgraph`, `02_LANGGRAPH_DEEP_DIVE.md` | `WORKFLOW_AND_EXECUTION_PATHS.md`, Pregel State Loop Spec. |
| **D** | Microsoft Agent Framework & Lifecycle | `/goal` | `chat-sdk`, `build-agents` | `D:\AI-Employee-Platform-Research\microsoft-agent-framework`, `03_...` | Channel adapters, UTF-16 chunking, Middleware lifecycle. |
| **E** | Dify & Platform Architecture | `/goal` | `create-a-backend`, `supabase-postgres-best-practices` | `D:\AI-Employee-Platform-Research\dify`, `04_DIFY_DEEP_DIVE.md` | Connection pool preservation pattern, Cognitive step telemetry. |
| **F** | n8n & Workflow Generation | `/goal` | `create-a-backend` | `D:\AI-Employee-Platform-Research\n8n`, `05_N8N_DEEP_DIVE.md` | `WaitTracker` execution suspension, Human-in-the-loop triggers. |
| **G** | RagLeap Core & Knowledge Architecture | `/goal` | `supabase-postgres-best-practices` | `D:\AI-Employee-Platform-Research\ragleap-core`, `06_RAGLEAP_CORE_DEEP_DIVE.md` | `KNOWLEDGE_AND_MEMORY_ARCHITECTURE.md`, 3-Tier Autonomy. |
| **H** | OpenAI Agents SDK & Runtime | `/goal` | `build-agents`, `google-antigravity-sdk` | `D:\AI-Employee-Platform-Research\openai-agents-python`, `07_...` | Declarative Handoff contracts, `input_filter` context sanitization. |
| **I** | AI-Employee-Platform Repository Audit | `/goal` | Git CLI, Pytest, `read_file` | `packages/services/`, `packages/models/`, legacy engine files | `EXISTING_ARCHITECTURE_ASSESSMENT.md`, Replacement Strategy. |
| **J** | Full-Platform Target Architecture | `/goal` | `create-a-backend`, `build-agents` | All reference deep dives, `PROJECT_VISION.md`, master blueprint | Comprehensive Platform Target Architecture Blueprint. |
| **K** | Dashboard & User-Input Architecture | `autonomous-page-testing` | `react-best-practices` | `apps/tenant-dashboard/`, `apps/admin-dashboard/` | `DASHBOARD_GENERATION_ARCHITECTURE.md`, UI Ownership Matrix. |
| **L** | Security & Autonomous Capability Gen | `/goal` | `supabase-postgres-best-practices`, `build-agents` | Cryptographic specs, Memento 6-gate engine, Scope specs | `SECURITY_AND_MULTI_TENANCY.md`, `AUTONOMOUS_CAPABILITY_GENERATION.md`. |
| **M** | Independent Architectural Review | `verification` | `/goal`, forensic audit protocol | All generated architecture specifications and matrices | `QUALITY_ASSURANCE_REVIEWS.md`, Final Acceptance Report. |

---

## 4. Conflict Resolution & Evidence Hierarchy

To guarantee scientific and engineering accuracy, the following precedence rule is strictly enforced across all workstreams:
1. **Physical & Mathematical Reality:** Distributed systems constraints (impossibility of distributed consensus over uncoordinated partial failures, atomic commit limits).
2. **Source Code & Verified Runtime Tests:** Actual executable code, AST behavior, and verified command outputs from `D:\AI-Employee-Platform-Research` and local tests.
3. **Official Provider Specifications:** Published API documentation (PostgreSQL 17 manual, Meta Graph API specs, Stripe API docs, Twilio API reference, RFC 8785).
4. **Skill Output & Agent Hypotheses:** Output from AI skills, agents, or heuristic blueprints. Any assertion produced by a skill that contradicts verified source code or API specifications is immediately flagged, refuted, and corrected.
