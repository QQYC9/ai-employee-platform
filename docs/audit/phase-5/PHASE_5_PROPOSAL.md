# PHASE_5_PROPOSAL.md
## AI-Employee-Platform — Phase 5 Architecture Design & Scope Proposal
### Role-Based Digital Employee Persona Contracts & Action Policy Guardrails

> **STATUS: PROPOSAL ONLY — NOT APPROVED FOR IMPLEMENTATION.**
> **Review Target:** Phase 5 Architecture, Scope Definition, and Boundary Design
> **Prior Delivered Documentation Commit:** `ee09177452abe4f009259e8432f1df5d8535dcfb` (Stage 2E initial proposal publish)
> **Application Source Snapshot Baseline:** `8803f3c634ca17f9bf79f7cce0f15b01dc0b7660` / `e3a1c4450215df1c4a0fdd8e77369352257efdc4` (verified identical in `packages/`, `apps/`, `infrastructure/`, `tests/`)
> **Branch:** `checkpoint/phase-12-knowledge-base`
> **Proposal Revision Date:** 2026-11-01
> **Governance Notice:** This document is an architectural design proposal submitted for business owner review. It conveys zero authorization to write application code, create migrations, modify database state, or begin Phase 5 implementation.

---

## 1. Executive Summary & Strategic Intent

Following the completion of the Phase 4D Outbound Campaigns milestone, the forensic audit of CR-05-01 (Owner Approval Anti-Hijack), and the Stage 2 Comparative Architecture Review across six external agent systems (**Memento-Skills**, **LangGraph**, **Microsoft Agent Framework**, **Dify**, **n8n**, and **RagLeap Core**), this document establishes the formal design proposal for **Phase 5**.

### The Core Strategic Problem
In the current codebase ([`packages/services/conversational_agent_engine.py:142-156`](file:///d:/AI-Employee-Platform/packages/services/conversational_agent_engine.py#L142-L156)), every tenant is provisioned with a generic agent instance. Agent identity is constructed dynamically via ad-hoc string formatting combining `tenant.employee_name` and `tenant.name`. There is no persisted, verifiable contract defining the digital employee's specific job role, behavioral dialect/tone, operational boundaries, permitted tool categories, or escalation thresholds.

Consequently:
1. **Role Ambiguity:** The agent acts as an unconstrained generalist, risking conversational overreach regarding its business responsibilities.
2. **Tool Scope Leakage:** Without pre-invocation role filters, all tenant-registered tools in [`packages/tools/registry.py`](file:///d:/AI-Employee-Platform/packages/tools/registry.py) are theoretically exposed to every incoming conversational context.
3. **Prompt Brittleness:** Tone, dialect (e.g. Formal Saudi Corporate vs. Warm GCC Friendly), and operational constraints cannot be tailored per business vertical without modifying backend Python code.

### Proposed Solution for Phase 5
Phase 5 proposes adapting the **Role-Based Digital Employee Persona Contract** pattern (identified in RagLeap Core and prioritized in Decision Log Entry 05) and combining it with a **Pre-Invocation Action Policy Guard** integrated directly into the central decision pipeline ([`packages/services/decision_engine.py`](file:///d:/AI-Employee-Platform/packages/services/decision_engine.py) / [`packages/tools/executor.py`](file:///d:/AI-Employee-Platform/packages/tools/executor.py)).

Phase 5 introduces a declarative, database-backed `EmployeePersona` schema and middleware layer that equips each digital employee with:
- An explicit job role specification (e.g., *Customer Care Specialist*, *Consultative Sales Consultant*, *Operations & Appointment Coordinator*).
- Calibrated Arabic dialect and behavioral tone configurations.
- Whitelisted tool categories evaluated *before* tool execution.
- Deterministic escalation and refusal boundaries for inquiries exceeding the assigned persona's authority.

---

## 2. Context & Reconciliation with Prior Milestones

This proposal builds directly upon the established repository roadmap without reopening settled research:

1. **Phase 4D Baseline:** Omni-channel connectors (Telegram, WhatsApp, Webhooks), Outbound Campaigns, and Lifecycle Management are implemented and verified across all existing regression test suites.
2. **CR-05-01 Forensic Reality:**
   - **Approval Challenge Creation & Verification:** *Functional.* Base29 6-character OTP generation, HMAC-SHA256 signature verification, and transactional outbox event insertion are verified and operating as designed.
   - **Downstream Action Execution:** *Defective / Nonfunctional.* In [`packages/services/outbox_worker.py:929`](file:///d:/AI-Employee-Platform/packages/services/outbox_worker.py#L929), `_handle_approval_action_execution` is defined outside `class OutboxWorker` at module level (raising `AttributeError` at runtime). In lines 1017–1030, `ToolExecutor` is stubbed out and bypassed, recording fake success in the database without executing the approved business mutation. In addition, worker fencing generation bumping (`claim_generation`) is absent, and stale event recovery diverges from approval records.
3. **Comparative Review Synthesis:**
   - **RagLeap Core (Pattern 05 - ADAPT):** Role-based personas provide the highest immediate business value with the lowest operational complexity.
   - **LangGraph (Pattern 01 - ADAPT):** State graph checkpointing is valuable for long-term multi-turn interruptions, but represents excessive architectural volatility while CR-05-01 execution remains open. Deferred to post-CR-05-01 hardening.
   - **Memento-Skills (Pattern 06 - INVESTIGATE):** Dynamic reflective skill generation introduces sandbox and verification risks; SOP knowledge extraction is deferred to Phase 12.
   - **Dify / n8n (Pattern 07 - AVOID):** Wholesale platform replacement is rejected due to VPS resource limits and multi-tenancy requirements.

---

## 3. Section A: Phase Objective & User/Business Value

### A.1 Phase Objective
To transition `AI-Employee-Platform` from a single-agent generic chatbot model to a **Structured Multi-Role Digital Workforce**, allowing business tenants to deploy, configure, and govern specialized AI Digital Employees with guaranteed behavioral boundaries, role-specific tool restrictions, and verified Arabic tone profiles.

### A.2 Business & User Value
- **Enterprise-Grade Role Specialization:** Business owners can assign specific job titles (e.g. "موظف خدمة العملاء والدعم الفني", "مستشار المبيعات التسويقي", "منسق العمليات والحجوزات") to individual agents.
- **Enforced Execution Boundaries:** The digital employee cannot execute unapproved actions, modify catalog data, or access administrative tools unless explicitly permitted by its persona contract.
- **Dialect & Cultural Alignment:** Native Arabic dialect profiles (Saudi Formal, GCC Friendly, Levantine Commercial, Modern Standard Arabic) configured declaratively per tenant brand identity.
- **Deterministic Escalation:** Inquiries or requested actions outside the persona's job description trigger a graceful, brand-aligned escalation or polite refusal rather than conversational confusion.

---

## 4. Section B: Scope, Invariants & Explicit Non-Goals

### B.1 In-Scope Deliverables
1. **`EmployeePersona` Domain Model:** A tenant-isolated entity storing role type, tone configuration, permitted tool categories, escalation policies, and prompt templates.
2. **Standard System Persona Catalog:** Three pre-packaged, expert-tested system templates:
   - `system_customer_support`: Specializes in FAQ resolution, operating hours, store locations, policy explanations, and product/conversation read inquiries.
   - `system_sales_consultant`: Specializes in consultative selling, product comparisons, lead qualification, and customer profile registration.
   - `system_operations_assistant`: Specializes in appointment coordination, internal task tracking, and structured owner inquiries.
3. **Persona Binding & Resolution:** Associating an `Agent` with an `EmployeePersona` via a foreign key `agents.persona_id`, with tenant-level overrides.
4. **Pre-Invocation Action Policy Guard:** Integration into the central decision pipeline ([`packages/services/decision_engine.py`](file:///d:/AI-Employee-Platform/packages/services/decision_engine.py) / [`packages/tools/executor.py`](file:///d:/AI-Employee-Platform/packages/tools/executor.py)) evaluating whether an agent's active persona permits a requested tool *before* executing the tool.
5. **Persona-Aware Prompt Synthesizer:** Structured assembly of the agent system prompt within `ConversationalAgentEngine` that injects role boundaries, tone directives, and allowed action summaries within a strict token budget.
6. **Tenant & Admin REST APIs:** Endpoints to list system templates, create custom tenant personas, and assign personas to agents.

### B.2 Explicit Non-Goals (Out of Scope)
- **NO CR-05-01 Code Fixes in Phase 5:** Phase 5 will NOT repair the `OutboxWorker` scoping bug, will NOT remove the `ToolExecutor` stub in the worker, and will NOT implement claim generation bumping. Those fixes belong strictly to a dedicated **CR-05-01 Remediation Milestone**.
- **NO LangGraph StateGraph Rewrite:** The platform will NOT replace its existing conversational execution loop with LangGraph or cyclical graph engines.
- **NO Memento-Skills Autonomous Tool Authoring:** The agent will NOT dynamically generate, synthesize, or execute new Python tools at runtime. All tools remain statically typed and registered in [`packages/tools/registry.py`](file:///d:/AI-Employee-Platform/packages/tools/registry.py).
- **NO Neo4j Graph RAG Container:** Knowledge retrieval continues to rely on PostgreSQL 17 relational JSONB and `pgvector`. No secondary graph database container will be introduced.
- **NO Autonomous Agent-to-Agent Debates:** Conversations remain single-agent grounded dialogues between the customer/owner and the digital employee.

---

## 5. Section C: The Persona Permission Boundary (Subtractive Constraint Invariant)

### C.1 The Six Independent Security & Authority Layers
A fundamental architectural invariant of Phase 5 is that **Persona permissions are strictly subtractive (narrowing). A persona NEVER grants new authority, bypasses existing security layers, or overrides tenant boundaries.**

Every tool invocation in `AI-Employee-Platform` must pass through six independent layers in strict hierarchical order:

```mermaid
flowchart TD
    REQ["Inbound Action / Tool Execution Request"] --> L1{"Layer 1: Tenant Isolation & Status"}
    L1 -->|Fail| D1["DENY: Invalid/Inactive Tenant"]
    L1 -->|Pass| L2{"Layer 2: Actor Authentication & RBAC"}
    L2 -->|Fail| D2["DENY: Unauthenticated / Role Unauthorized"]
    L2 -->|Pass| L3{"Layer 3: Resource Ownership Boundary"}
    L3 -->|Fail| D3["DENY: Cross-Tenant Resource Access Blocked"]
    L3 -->|Pass| L4{"Layer 4: Platform ActionPolicy & Denies"}
    L4 -->|Fail| D4["DENY: Explicit Deny / Policy Rejection"]
    L4 -->|Pass| L5{"Layer 5: Tool Contract Permissions"}
    L5 -->|Fail| D5["DENY: Required Contract Permission Missing"]
    L5 -->|Pass| L6{"Layer 6: Persona Operational Constraint"}
    L6 -->|Fail| D6["DENY: Tool Category Exceeds Persona Role"]
    L6 -->|Pass| EXEC["PERMITTED: Proceed to Tool Execution"]
```

1. **Layer 1: Tenant Isolation & Status Gate:** Verifies `tenant_id` exists, is active (`Tenant.status == 'active'`), and protected by [`packages/core/safety_guard.py`](file:///d:/AI-Employee-Platform/packages/core/safety_guard.py).
2. **Layer 2: Actor Authentication & RBAC Context:** Verifies caller JWT and role via [`packages/auth/dependencies.py`](file:///d:/AI-Employee-Platform/packages/auth/dependencies.py) (e.g. `platform_admin`, `superadmin`, `tenant_owner`, `owner`, `tenant_admin`, `admin`, `tenant_user`, or inbound `customer`).
3. **Layer 3: Resource Ownership Boundary:** Confirms the target resource (customer record, task, product) belongs strictly to `current_tenant_id`. Cross-tenant queries fail closed.
4. **Layer 4: Platform ActionPolicy & Explicit Denies:** Evaluates [`packages/models/domain.py:ActionPolicy`](file:///d:/AI-Employee-Platform/packages/models/domain.py#L380) and `Permission` table explicit denies via [`packages/services/permission_service.py`](file:///d:/AI-Employee-Platform/packages/services/permission_service.py).
5. **Layer 5: Tool Contract Security Boundary:** Asserts that the caller possesses the specific `(action, resource)` tuples declared in [`packages/tools/contract.py:ToolContract.required_permissions`](file:///d:/AI-Employee-Platform/packages/tools/contract.py).
6. **Layer 6: Persona Operational Constraint (Phase 5 Addition):** Asserts that the tool belongs to `EmployeePersona.permitted_tool_categories`.

### C.2 Subtractive Hierarchy Rules
- **Rejection at ANY layer immediately halts execution.** Subsequent layers are not evaluated.
- **Layer 6 cannot widen Layers 1–5:** Even if a persona configuration lists a tool as permitted, execution is rejected if Layer 2 (RBAC), Layer 4 (ActionPolicy), or Layer 5 (Contract Permissions) rejects it.
- **`persona_overrides` Invariant:** Overrides defined on an individual `Agent` can only further restrict tools or adjust cosmetic tone attributes; they can **never** add tool categories omitted from the base persona.

### C.3 Distinguishing Physical Action Execution vs Textual Output (Hallucination Reality)
It is architecturally vital to distinguish between two completely different failure modes:
1. **Physical Action Execution (Deterministically Guaranteed):** Enforced by Layer 6 inside the application execution path. The agent physically cannot invoke database mutations or external APIs if disallowed by the persona.
2. **Textual Hallucination in Prompt Responses (Probabilistic, NOT Guaranteed by Persona):** A persona prompt instruction (e.g. "You are a customer service rep and cannot give discounts") guides the LLM, but cannot mathematically guarantee the model won't generate an incorrect statement in Arabic text (e.g. claiming "I can give you a 20% discount").
   - *Mitigation:* Textual truth is governed by **Grounded Fact Precedence** ([`packages/services/fact_service.py`](file:///d:/AI-Employee-Platform/packages/services/fact_service.py)) and explicit fallback refusal rules, NOT by assuming the LLM obeys persona boundaries blindly.

---

## 6. Section D: PreInvocationPolicyGuard Integration & Central Bottleneck

### D.1 The Central Execution Bottleneck in Current Code
A critical finding from codebase inspection is that [`packages/tools/executor.py:ToolExecutor.execute`](file:///d:/AI-Employee-Platform/packages/tools/executor.py#L228) is the **single central bottleneck** for all tool executions across the platform:
- In [`packages/services/conversational_agent_engine.py`](file:///d:/AI-Employee-Platform/packages/services/conversational_agent_engine.py), all model-requested tool calls pass into `self.tool_executor.execute(...)`.
- `ToolExecutor.execute()` immediately invokes `self.decision_engine.decide(...)` at line 260. If decision is not `ALLOW`, execution is blocked, logged in audit, and returned without invoking any tool handler.

```mermaid
flowchart TD
    subgraph Central Decision Pipeline
        TE[ToolExecutor.execute] --> DE[DecisionEngine.decide]
        DE --> PS[PermissionService.is_allowed - Layers 1-4]
        DE --> APS[ActionPolicyService.resolve_policy - Layer 4]
        DE --> PIPG[PreInvocationPolicyGuard - Layer 6 Persona Check]

        PIPG -->|Persona Permits Category| DE_ALLOW[DecisionResult: ALLOW]
        PIPG -->|Persona Denies Category| DE_DENY[DecisionResult: DENY - Persona Policy Violation]
        PIPG -->|Tool Category Missing| DE_SAFE_DENY[DecisionResult: DENY - Unknown Category]
    end

    DE_ALLOW --> TH[Tool Handler Execution]
    DE_DENY & DE_SAFE_DENY --> BLK[Audit Event: tool_execution_blocked & Return Result]
```

### D.2 Integration Without Parallel Pipelines
To avoid creating a fragile parallel permission path:
1. **DecisionEngine Integration:** `PreInvocationPolicyGuard` logic will be invoked directly inside `DecisionEngine.decide(..., agent_id=agent_id)` or as an explicit middleware immediately before it within `ToolExecutor.execute()`.
2. **Preventing Bypass:** Because all entry points (conversational engine, API routes, background tasks) invoke `ToolExecutor.execute()`, no execution path can bypass the persona check if `agent_id` is supplied.
3. **Handling Tools Without Categories:** As verified in `packages/tools/contract.py`, `ToolContract` currently lacks a native `category` field. If a tool has no assigned category in the Phase 5 taxonomy, the guard **fails closed** and returns `DENIED_UNKNOWN_CATEGORY`.
4. **Behavior for Agents Without Persona (`persona_id IS NULL`):**
   - *Legacy Fallback:* During the Phase 5 rollout, existing agents with `persona_id = NULL` bypass Layer 6 and remain governed by Layers 1–5 (existing Phase 4D behavior).
   - *Architectural Decision:* Newly provisioned tenants will be required to have an explicit persona assigned during onboarding provisioning.

---

## 7. Section E: Tool Categories Taxonomy Mapped to Real ToolRegistry

Codebase inspection of [`packages/tools/registry.py:create_default_registry`](file:///d:/AI-Employee-Platform/packages/tools/registry.py#L121) reveals exactly **15 real tools** currently registered. Notice that the contract slug for document generation is `generate_document` (not `document_generator`).

Furthermore, `ToolContract` currently defines `risk_level: ToolRiskLevel` (`read_only`, `low`, `medium`, `high`, `critical`), but **does not possess a formal `category` field**.

Therefore, Phase 5 establishes the following **Canonical Tool Category Taxonomy** to be implemented in Stage 5.1:

| Actual Tool Slug | Implementation Class | Physical Risk Level | Read / Write / Sensitive | Current Contract Permissions | Proposed Canonical Category | Proposed Allowed System Personas |
| :--- | :--- | :---: | :---: | :--- | :--- | :--- |
| **`product_list`** | `ProductListTool` | `read_only` | Read | `[('read', 'products')]` | `product_read` | Support, Sales |
| **`product_add_or_update`** | `ProductAddOrUpdateTool` | `low` | Write (Catalog Mutation) | `[('write', 'products')]` | `product_write` | **None** (Owner/Catalog Manager only) |
| **`business_summary`** | `BusinessSummaryTool` | `read_only` | Read | `[('read', 'reports')]` | `business_read` | Support, Sales, Operations |
| **`customer_search`** | `CustomerSearchTool` | `read_only` | Read | `[('read', 'customers')]` | `customer_read` | Sales, Operations |
| **`customer_get`** | `CustomerGetTool` | `read_only` | Read | `[('read', 'customers')]` | `customer_read` | Sales, Operations |
| **`customer_create_or_update`**| `CustomerCreateOrUpdateTool`| `medium` | Write (CRM Mutation) | `[('write', 'customers')]` | `customer_write` | Sales |
| **`conversation_search`** | `ConversationSearchTool` | `read_only` | Read | `[('read', 'conversations')]` | `conversation_read` | Support, Operations |
| **`conversation_get_messages`** | `ConversationGetMessagesTool` | `read_only` | Read | `[('read', 'conversations'), ('read', 'messages')]` | `conversation_read` | Operations |
| **`conversation_summarize`** | `ConversationSummarizeTool` | `read_only` | Read | `[('read', 'conversations'), ('read', 'messages')]` | `conversation_read` | Operations |
| **`conversation_summarize_all`**| `ConversationSummarizeAllTool`| `read_only` | Read | `[('read', 'conversations'), ('read', 'messages')]` | `conversation_read` | Operations |
| **`conversation_escalation_status`**| `ConversationEscalationStatusTool`| `read_only` | Read | `[('read', 'conversations')]` | `conversation_read` | Support, Operations |
| **`task_query`** | `TaskQueryTool` | `read_only` | Read | `[('read', 'tasks')]` | `task_read` | Operations |
| **`task_create`** | `TaskCreateTool` | `medium` | Write (Task Mutation) | `[('write', 'tasks')]` | `task_write` | Operations |
| **`generate_document`** | `DocumentGeneratorTool` | `medium` | Write (Doc Generation) | `[('write', 'documents')]` | `document_write` | Operations |
| **`http_request`** | `HttpRequestTool` | `medium` | Write / External Side-Effect | `[('execute', 'tools:http_request')]` | `external_integration` | **None** (Platform / Admin only) |

> [!IMPORTANT]
> Because `ToolContract` does not currently contain a `category` property, defining and populating this property on `ToolContract` or mapping it in a canonical dictionary is an explicit prerequisite step for Stage 5.1.

---

## 8. Section F: Resolution of CR-05-01 & The APPROVAL_PENDING Boundary

### F.1 The Unresolved Reality of CR-05-01
The forensic audit established that downstream approved-action execution is physically defective in the repository:
1. **Scoping Bug:** `_handle_approval_action_execution` is defined at [`outbox_worker.py:929`](file:///d:/AI-Employee-Platform/packages/services/outbox_worker.py#L929) outside `class OutboxWorker`.
2. **Execution Bypass Stub:** Lines 1017–1030 in `outbox_worker.py` commit fake success (`is_success=True`) without invoking `ToolExecutor`.
3. **Inoperative Worker Fencing:** `claim_generation` is never incremented on claim or recovery (`outbox_service.py:210, 342`).
4. **Recovery State Divergence:** `recover_stale_events` resets outbox status to `pending` but leaves `approvals` stuck in `executing`.

### F.2 Technical Fencing Guarantees in Phase 5
Phase 5 **does not fix CR-05-01**, and therefore **cannot represent approved tool execution as operational.** Simply returning an "APPROVAL_PENDING" text message to the user is NOT a security fence.

To prevent Phase 5 from triggering fake success or executing through the broken worker:
1. **The Physical Gate Location (Action Decision Boundary):**
   - The prevention gate lies at the **Decision Boundary in `DecisionEngine` / `ApprovalService`**, before any event can be claimed by the worker.
   - When a persona-constrained action evaluates to `requires_approval=True`, `ApprovalService` generates the Base29 challenge for owner inspection, but **downstream asynchronous dispatch to `OutboxWorker` is held closed**.
   - No `approval_action_execution` event is claimed or processed by the worker until the **CR-05-01 Remediation Milestone** is completed.
2. **Preventing Fake Success:**
   - Because events are held closed at the challenge creation boundary, lines 1017–1030 in `outbox_worker.py` are never reached, completely preventing the fake `record_execution_result(is_success=True)` stub from executing.
3. **Database Assertion, Not Text Messages:**
   The guarantee that the action did not execute is verified by asserting in PostgreSQL:
   - `approvals.execution_status == 'not_started'`
   - Zero mutation records written in target tables (`tasks`, `products`).
   - An explicit audit event `approval_challenge_created` is logged.
4. **What CANNOT be guaranteed without CR-05-01:**
   - Reliable asynchronous dispatch of approved actions cannot be guaranteed. That functionality is strictly blocked pending the separate **CR-05-01 Remediation Milestone**.

---

## 9. Section G: Data Model, Partial Unique Index & Override Governance

### G.1 Domain Model: `EmployeePersona`
*(Note: Full schema-level versioning is deferred to Phase 6/12; Phase 5 implements a mutable model with tracking timestamps).*

```python
# Location: packages/models/domain.py

class EmployeePersona(Base):
    __tablename__ = "employee_personas"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )  # NULL for global system templates; non-NULL for tenant custom personas

    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )  # 'customer_support', 'sales_consultant', 'operations_assistant'

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    tone_profile: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    permitted_tool_categories: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    escalation_policies: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    system_prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_system_template: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"), index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"), index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

### G.2 PostgreSQL Partial Unique Index for System Templates
In PostgreSQL and the SQL standard, `NULL != NULL`. Therefore, a simple `UniqueConstraint("tenant_id", "slug")` would allow duplicate slugs when `tenant_id IS NULL`.

Phase 5 addresses this via two **partial unique indexes** in the Alembic migration:
```sql
-- 1. Enforces slug uniqueness for global system templates
CREATE UNIQUE INDEX uq_system_personas_slug ON employee_personas (slug) WHERE tenant_id IS NULL;

-- 2. Enforces slug uniqueness per tenant for custom personas
CREATE UNIQUE INDEX uq_tenant_personas_slug ON employee_personas (tenant_id, slug) WHERE tenant_id IS NOT NULL;
```

### G.3 Schema Modification on `Agent` and `persona_overrides` Governance

```python
# Added to class Agent in packages/models/domain.py:

persona_id: Mapped[uuid.UUID | None] = mapped_column(
    ForeignKey("employee_personas.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
)
persona_overrides: Mapped[dict] = mapped_column(
    JSONB,
    nullable=False,
    default=dict,
    server_default=text("'{}'::jsonb"),
)
```

#### Strict Override Governance Rules:
- **Permitted Override Keys:** `display_name`, `greeting_message`, and cosmetic tone tweaks (`tone_profile.formality`, `tone_profile.empathy`).
- **PROHIBITED Override Keys:** `permitted_tool_categories`, `role_type`, `escalation_policies`, and any security constraints.
- **Merge Order:** `System Template -> Tenant Persona -> Agent persona_overrides`.
- **Validation:** `PersonaContractService` validates override payloads upon saving; any attempt to inject unwhitelisted keys raises `InvalidPersonaOverrideError`.

---

## 10. Section H: Multi-Tenant Isolation & Cross-Process Cache Synchronization

### H.1 Preventing Cross-Tenant Persona Assignment
Because a database foreign key from `agents.persona_id` to `employee_personas.id` does not validate that both rows belong to the same tenant, `PersonaContractService.assign_persona(tenant_id, agent_id, persona_id)` enforces:
```python
persona = self.get_persona(persona_id)
if persona is None:
    raise PersonaNotFoundError()
if not persona.is_system_template and persona.tenant_id != tenant_id:
    raise CrossTenantPersonaAssignmentError(
        f"Tenant {tenant_id} cannot assign persona {persona_id} belonging to tenant {persona.tenant_id}"
    )
```

### H.2 Multi-Worker Cache Synchronization
`AgentIdentityService` currently contains an in-memory dictionary `self._profile_cache`. In a multi-worker production environment (multiple Uvicorn processes or background workers), clearing the cache in one process does not invalidate other processes.

Phase 5 establishes as a design specification and implementation requirement:
1. **Short TTL:** In-memory cached profiles expire after 60 seconds.
2. **Versioned Tenant Key in Redis:** When a persona or override is updated, `PersonaContractService` bumps a Redis key `tenant:{id}:persona_version`. Workers check this lightweight integer before serving from local memory.

### H.3 RBAC Role Mapping Grounded in Codebase
Grounded in [`packages/auth/dependencies.py`](file:///d:/AI-Employee-Platform/packages/auth/dependencies.py):
- **Platform Superadmin (`require_platform_admin`):** `platform_admin`, `superadmin`. Authorized to manage system templates.
- **Tenant Admin / Owner (`require_tenant_admin`):** `tenant_owner`, `owner`, `tenant_admin`, `admin`. Authorized to create custom personas and bind them to agents.
- **Tenant User:** `tenant_user`. Read-only access to assigned personas.

---

## 11. Section I: Unified Token Budget & Truncation Invariants

### I.1 Unified Budget Allocations
To eliminate conflicting numbers in earlier drafts, the token budget is formally unified:
- **Persona Instruction Envelope:** Allocated strictly **<= 250 tokens** (approx. 1,000 characters). This includes role description, dialect/tone rules, permitted tool category summary, and escalation boundaries.
- **Total Assembled System Prompt Budget:** Allocated strictly **<= 1,500 tokens** (approx. 6,000 characters). This encompasses tenant corporate branding, persona envelope, grounded facts from `FactService`, and runtime conversation context.

### I.2 Token Estimation & Overflow Policy
- **Estimation Method:** Measured via character count heuristic (~4 characters per token for mixed Arabic/English text), or tokenizer utility when available in the provider adapter.
- **Truncation Priority Invariant:** If the total prompt exceeds the 1,500-token threshold, the truncation algorithm **MUST NEVER truncate:**
  1. Multi-tenant isolation instructions.
  2. Persona behavioral and refusal boundaries.
  3. Pre-invocation safety constraints.
- *Truncation order:* Low-relevance knowledge/fact chunks are shed first. Core persona boundary instructions are permanently protected from truncation.

---

## 12. Section J: Backward Compatibility & Migration Strategy

- **Additive Schema Evolution:** The migration creates `employee_personas`, partial indexes, and adds nullable `agents.persona_id`.
- **Zero Disruption for Existing Tenants:** Existing `agents` have `persona_id = NULL`.
- **Legacy Fallback Path:** When `persona_id` is `NULL`, `ConversationalAgentEngine` invokes the Phase 4D legacy system prompt builder verbatim.
- **Clean Downgrade:** Dropping `agents.persona_id` and table `employee_personas` restores the database to the exact Phase 4D schema without altering conversations, messages, or channels.

---

## 13. Section K: Implementation Sequence (Verifiable Micro-Stages)

Phase 5 must be implemented in five small, independently verifiable micro-stages:

1. **Stage 5.1: Database Schema & Canonical Tool Taxonomy:**
   - Define `EmployeePersona` model in `domain.py`.
   - Add `persona_id` and `persona_overrides` to `Agent`.
   - Implement Alembic migration with partial unique indexes and seed data for the 3 system templates.
   - Define canonical tool categories for the 15 tools.
2. **Stage 5.2: Persona Service & Policy Guard Integration:**
   - Implement `PersonaContractService` with cross-tenant assignment validation and Redis version bumping.
   - Integrate `PreInvocationPolicyGuard` into `DecisionEngine.decide` / `ToolExecutor.execute`.
3. **Stage 5.3: Prompt Synthesizer & Engine Integration:**
   - Implement `PersonaPromptSynthesizer` with 250-token envelope budget.
   - Integrate into `ConversationalAgentEngine.process_message`, preserving legacy fallback when `persona_id IS NULL`.
4. **Stage 5.4: REST API Endpoints & RBAC:**
   - Implement `/api/v1/personas` and `/api/v1/agents/{id}/persona` matching `packages/auth/dependencies.py` roles (`require_tenant_admin`).
5. **Stage 5.5: Comprehensive Verification:**
   - Execute automated pytest test suite.
   - Execute manual Telegram verification scenarios using designated test environment placeholders.

---

## 14. Section L: Automated Testing Strategy

Automated tests will be located under `tests/test_phase5_personas_and_policy_guard.py` and must verify:

1. **Schema & Multi-Tenant Isolation Tests:**
   - Tenant A cannot view, update, or assign Tenant B's custom personas.
   - Cross-tenant persona assignment raises `CrossTenantPersonaAssignmentError`.
   - Partial unique indexes enforce slug uniqueness independently for system templates vs tenant custom personas.
2. **Pre-Invocation Policy Guard & Bottleneck Tests:**
   - Persona with `["product_read"]` category allows `product_list`.
   - Persona with `["product_read"]` category strictly rejects `task_create` and `product_add_or_update`.
   - Rejection occurs inside `DecisionEngine.decide` before `ToolExecutor` reaches handlers.
   - Tools with unknown/missing categories fail closed (`DENIED_UNKNOWN_CATEGORY`).
3. **Prompt Synthesis & Token Budget Tests:**
   - Persona prompt envelope strictly <= 250 tokens.
   - Core boundary instructions survive context truncation.
4. **Backward Compatibility Tests:**
   - Agents with `persona_id = NULL` produce identical system prompts to Phase 4D baseline.
   - 100% of existing regression test suites pass without modification.

---

## 15. Section M: Manual Acceptance Test Strategy (Live Telegram Verification)

> [!IMPORTANT]
> Real-world manual testing on a live messaging connector (Telegram) requires verified pre-flight test credentials. Do NOT assume test bots or tenants exist without verification.

### M.1 Test Environment Pre-Flight Verification Checklist
Before executing manual acceptance tests, the operator must verify:
- `<CONFIGURED_TEST_TELEGRAM_BOT>`: Verified active bot token configured in `channels`.
- `<PROVISIONED_TEST_TENANT_ID>`: Verified dedicated test tenant with seeded facts and catalog items.
- `<AUTHORIZED_TEST_OWNER_ID>`: Verified user with role `owner` or `tenant_owner`.
- Zero real customer data present in test tenant.
- Test execution does NOT invoke real destructive actions.

### M.2 Test Protocol & Scenarios

| Scenario ID | Test Name | Inbound Telegram Message | Assigned Persona | Expected Digital Employee Response | Persisted State & Evidence to Verify |
| :---: | :--- | :--- | :--- | :--- | :--- |
| **TG-01** | **Normal Role Behavior (Support)** | "أهلاً، ما هي ساعات العمل لديكم وما هي سياسة الاسترجاع؟" | `system_customer_support` | Accurate answer drawn from `FactService` in professional Saudi corporate tone; zero hallucinations; polite closing. | `messages` record created with `sender_type='agent'`; `ExecutionTrace` logs `persona_slug='system_customer_support'`. |
| **TG-02** | **Action Boundary Refusal** | "أريد إلغاء طلب عميل آخر رقم 482 وإعادة المبلغ كاش فوراً" | `system_customer_support` | Polite refusal explaining that order cancellation/refunds exceed support persona authority, offering to log inquiry for management. | Tool `task_create` blocked by `PreInvocationPolicyGuard`; `AuditEvent` recorded with `tool_policy_violation`. |
| **TG-03** | **Persona Role Switch (Sales)** | "أبحث عن أفضل باقة تناسب متجر تجزئة صغير، ما هي مقترحاتكم؟" | `system_sales_consultant` (Switched via API) | Proactive consultative sales tone; asks qualifying questions about store size; recommends products based on catalog. | `ExecutionTrace` verifies active persona switch; tone conforms to sales consultant guidelines. |
| **TG-04** | **CR-05-01 Gated Safe Refusal / Halting** | "احذف جميع المنتجات المنتهية فوراً" (Sent by Owner) | `system_operations_assistant` | Generates 6-char Base29 OTP challenge code; halts at decision boundary; does NOT execute destructive mutation. | `approvals` table contains challenge with `execution_status='not_started'`; target database rows remain untouched; zero fake success recorded. |

---

## 16. Section N: Explicit Go / No-Go Acceptance Criteria

Phase 5 will be approved for production merge **only** if all 10 criteria pass:

1. **Schema Integrity:** Alembic migration runs forwards and backwards cleanly on PostgreSQL 17 without data loss.
2. **Partial Unique Indexes:** Partial indexes verified; duplicate slugs blocked for system templates and per tenant.
3. **Tenant Isolation:** Zero cross-tenant persona leakage or assignment proven across automated tests.
4. **Policy Guard Efficacy:** 100% of unpermitted tool calls blocked at `DecisionEngine` / `ToolExecutor` before reaching handlers.
5. **Token Budget Compliance:** Synthesized persona prompt envelope is <= 250 tokens.
6. **CR-05-01 Boundary Intact:** No downstream approved-action execution executed; gate halts cleanly with zero fake success recording.
7. **Backward Compatibility:** All existing agents with `persona_id = NULL` operate identically to Phase 4D.
8. **Existing Regression Suite:** 100% of existing Phase 4 regression test suites pass without regression.
9. **Phase 5 Automated Suite:** 100% of newly authored Phase 5 automated tests pass.
10. **Telegram Manual Acceptance:** All 4 Telegram scenarios (TG-01 through TG-04) verified and signed off with database and audit logs.

---

## 17. Section O: Rollback & Recovery Strategy

1. **Immediate Application Mitigation (Zero Downtime):**
   - Execute SQL command to set `agents.persona_id = NULL` for affected tenant:
     `UPDATE agents SET persona_id = NULL WHERE tenant_id = :affected_tenant_id;`
   - The agent immediately falls back to Phase 4D prompt generation without restarting the container.
2. **Complete Schema Rollback:**
   - Downgrade Alembic migration:
     `.venv\Scripts\alembic downgrade -1`
   - Drops `agents.persona_id`, `agents.persona_overrides`, and table `employee_personas`.
   - All conversations, messages, channels, and outbox records remain intact.

---

## 18. Section P: Open Decisions & Architectural Governance for Owner Review

### Open Architectural Decisions Requiring Business Owner Confirmation:
1. **Decision 1 (Persona Assignment Level):** Current codebase routes channels to conversations without an `agent_id` column; agent lookup defaults to the tenant's primary agent (`Agent.agent_type == 'main'`). Phase 5 proposes binding personas at the `Agent` level (`agents.persona_id`). Extending persona binding to individual `Channels` (e.g. Sales on WhatsApp, Support on Telegram) requires adding `channel.persona_id` and is recommended for Phase 6.
2. **Decision 2 (Default Persona for New Tenants):** When a new tenant is provisioned via `TenantProvisioningService`, should the agent default to `system_customer_support`, or remain `NULL` (legacy prompt) until explicitly selected? *(Proposal recommends leaving `NULL` during Phase 5 testing, transitioning to required selection in onboarding interview).*
3. **Decision 3 (CR-05-01 Remediation Milestone Sequencing):** Does the owner wish to execute the dedicated **CR-05-01 Remediation Milestone** *before* Phase 5 or *in parallel* as an independent track? *(Proposal confirms Phase 5 is fully functional for conversational customer service even if CR-05-01 remediation is scheduled immediately thereafter).*

---
*End of Phase 5 Definition and Design Proposal (Architecture Review Corrections).*
