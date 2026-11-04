# Existing Data & Domain Model — Forensic Database Architecture Review

**Document ID:** `EXISTING_DATA_AND_DOMAIN_MODEL`  
**Governing Workstream:** Workstream A & Workstream K (Database & Domain Lifecycle)  
**Target Repository:** `QQYC9/ai-employee-platform` (Local HEAD `86c1abf`)  
**Status:** **AUDITED & VERIFIED**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Summary & Schema Topology

The AI-Employee-Platform database architecture is built on **PostgreSQL 17** using **SQLAlchemy 2.0 ORM** with declarative mapped columns (`Mapped[T] = mapped_column(...)`) and Alembic migrations.

The schema spans 52 distinct relational entities partitioned into 8 functional clusters:
1. **Tenancy & IAM:** `tenants`, `users`, `permissions`, `tenant_link_codes`.
2. **Employee Persona & Agents:** `employee_personas`, `agents`, `capabilities`, `tools`, `integrations`, `agent_capabilities`, `capability_tools`, `tool_integrations`.
3. **Conversational Engine & Ingress:** `channels`, `customers`, `conversations`, `messages`, `owner_inquiries`.
4. **Execution Tasks & Approvals:** `tasks`, `execution_traces`, `execution_steps`, `approvals`, `action_policies`, `idempotency_records`.
5. **Knowledge & Memory Architecture:** `business_brains`, `knowledges`, `facts`, `memories`, `sources`, `source_policies`.
6. **Self-Development & Evolution:** `learnings`, `development_requests`, `learning_evidences`, `capability_versions`, `development_runs`, `interview_topics`, `interview_states`.
7. **Async Delivery & Outbox:** `outbox_events`, `dispatch_attempts`, `dispatch_attempt_chunks`.
8. **Campaigns & Governance:** `campaigns`, `campaign_recipients`, `proactive_workflows`, `workflow_runs`, `audit_events`, `daily_reports`, `tenant_ai_budgets`, `ai_usage_logs`.

---

## 2. Forensic Evaluation of Schema Strengths & Structural Defects

### 2.1 Architectural Strengths
- **Composite Multi-Tenant Isolation:** Most tenant-scoped tables feature explicit `tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE`.
- **Decoupled Outbox Queue:** `outbox_events` provides a clean Transactional Outbox pattern enabling reliable `FOR UPDATE SKIP LOCKED` async delivery.
- **Audit & Idempotency Tables:** `audit_events` and `idempotency_records` provide basic tracking foundations.

### 2.2 Critical Schema Defects Identified in Legacy Models
1. **Missing Concurrency Fencing on Tasks:**
   - In `tasks` and `conversations`, there is no monotonic `fence_token INTEGER` or explicit row-level `locked_until TIMESTAMPTZ`. When a worker hangs or enters a slow LLM stream, a second worker claiming the task can overwrite newer state upon commit (split-brain condition).
2. **Flat String Fact Representation:**
   - The `facts` table stores facts as unstructured string values without multidimensional scoping (spatial, temporal, audience validity). Facts lack explicit versioning and cryptographic supersession pointers (`superseded_by_id UUID`).
3. **Lack of Dynamic Business Entity Storage:**
   - There is no generic, typed dynamic entity table. Attempting to support autonomous modules (e.g., invoices, products, stock levels) currently requires either schema alterations or cramming arbitrary JSON into `metadata JSONB` fields without typed decimal constraints (`balance_due DECIMAL(18, 4)`).
4. **Missing Checkpoint Hierarchy for StateGraphs:**
   - The schema lacks an `execution_checkpoints` table modeled after LangGraph's `BaseCheckpointSaver`. Checkpoints are necessary to support deterministic superstep rollbacks and n8n-style `WaitTracker` suspension.

---

## 3. Schema Target Extension Strategy (Phase 5 Rebuild)

To support the full platform vision without breaking existing relational integrity, the schema will be extended with 4 new foundational tables via Alembic:

### Extension 1: `execution_tasks` (PostgreSQL 17 Concurrency & Fencing)
```sql
CREATE TABLE execution_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    fence_token INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(32) NOT NULL DEFAULT 'pending', -- pending, running, suspended, completed, failed
    worker_id VARCHAR(64),
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_execution_tasks_lease ON execution_tasks (status, locked_until) WHERE status IN ('pending', 'running');
```

### Extension 2: `execution_checkpoints` (Deterministic State Persistence)
```sql
CREATE TABLE execution_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES execution_tasks(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    superstep INTEGER NOT NULL,
    state_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_checkpoint_task_superstep UNIQUE (task_id, superstep)
);
```

### Extension 3: `business_entities` (Hybrid Relational-Dynamic Storage Model)
```sql
CREATE TABLE business_entities (
    id UUID NOT NULL,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    entity_type VARCHAR(64) NOT NULL, -- product, invoice, customer_order, stock_item
    title VARCHAR(255) NOT NULL,
    reference_code VARCHAR(64),
    balance_due DECIMAL(18, 4) DEFAULT 0.0000, -- Typed financial decimal
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    dynamic_attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX idx_business_entities_gin ON business_entities USING GIN (dynamic_attributes jsonb_path_ops);
```

### Extension 4: `ui_interface_declarations` (Declarative UI Schemas)
```sql
CREATE TABLE ui_interface_declarations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    capability_id UUID NOT NULL REFERENCES capabilities(id) ON DELETE CASCADE,
    scope_type VARCHAR(32) NOT NULL, -- admin_global vs tenant_module
    schema_version INTEGER NOT NULL DEFAULT 1,
    form_definition JSONB NOT NULL, -- JSONSchema / Pydantic field layout
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```
