# Evidence Log: Runtime Engine, Workflows, Handoffs & Concurrency

**Document ID:** `RUNTIME_AND_WORKFLOW_FINDINGS_EVIDENCE_LOG`  
**Audit Standard:** Second-Order Adversarial Audit  
**Target Findings:** F-06 (Callable Serialization), F-11 (Supersteps vs Handoffs), F-12 (Autonomous Skill Activation), F-14a (Outbox CFS Absence)

---

## 1. Deep-Dive Audit: Finding F-06 (Non-Serializable Callable Filters in JSONB)

### 1.1 Repository Evidence
- **File:** `docs/architecture/MASTER_ARCHITECTURE_BLUEPRINT.md` lines 156–161:
  ```python
  class EmployeeHandoffContract:
      target_employee_id: str
      target_role: str
      delegation_reason: str
      transfer_payload: dict[str, Any]
      input_filter: Callable[[HandoffContext], HandoffContext]
  ```
- **Table DDL in `MASTER_ARCHITECTURE_BLUEPRINT.md:340`:**
  ```sql
  CREATE TABLE execution_checkpoints (
      tenant_id UUID NOT NULL,
      execution_id UUID NOT NULL,
      step_index INTEGER NOT NULL,
      state_payload JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (tenant_id, execution_id, step_index)
  );
  ```

### 1.2 Technical Reproduction
- Attempting to serialize an instance containing a Python `Callable` via `json.dumps()` or SQLAlchemy `JSONB` raises:
  ```text
  TypeError: Object of type function is not JSON serializable
  ```
- **Impact:** In LangGraph, passing runtime contracts containing live Python callables across state channels crashes PostgreSQL checkpoint persistence.
- **Verdict:** `CONFIRMED` (P1). Must replace callables with declarative field whitelists/blacklists.

---

## 2. Deep-Dive Audit: Finding F-11 (`MAX_SUPERSTEPS = 10` vs `MAX_HANDOFF_HOPS = 5`)

### 2.1 Repository Evidence
- `docs/architecture/ARCHITECTURAL_CONFLICTS_AND_OPEN_QUESTIONS.md:29`:
  > *"Every customer turn is an execution graph bounded by `config.MAX_SUPERSTEPS = 10`."*
- `docs/architecture/MASTER_ARCHITECTURE_BLUEPRINT.md:761` (ADR-05):
  > *"Initial hop ceiling set as an uncalibrated hypothesis (`config.MAX_HANDOFF_HOPS = 5`)."*

### 2.2 Mathematical Tracing of Superstep Consumption
- In LangGraph Pregel:
  - Agent Invocation Node = 1 superstep.
  - Tool / Handoff Execution Node = 1 superstep.
- Tracing a 5-hop delegation chain:
  - Hop 1 (Triage $\to$ Sales): 2 supersteps.
  - Hop 2 (Sales $\to$ Operations): 2 supersteps.
  - Hop 3 (Operations $\to$ Logistics): 2 supersteps.
  - Hop 4 (Logistics $\to$ Billing): 2 supersteps.
  - Hop 5 (Billing $\to$ Triage): 2 supersteps.
  - Total minimum supersteps required: $5 \times 2 = 10$ supersteps.
- If even **one** agent executes a single database or calculation tool (1 superstep), the step count hits 11, triggering `GraphRecursionError` and terminating the customer's turn mid-conversation.
- **Verdict:** `CONFIRMED` as an arithmetic parameter conflict (P1).

---

## 3. Deep-Dive Audit: Finding F-12 (Autonomous Activation of Level 3 Skills)

### 3.1 Repository Evidence
- `docs/architecture/PLATFORM_SELF_DEVELOPMENT_RESEARCH.md` Table 2 line 27:
  ```text
  | Tier 3 | New Skill Synthesis | Procedural playbooks, operational guidelines (SKILL.md) | Autonomous (Offline) | Memento Gate 1 & 4 | Automated | Skill soft-delete |
  ```
- Conversely, `docs/architecture/AUTONOMOUS_CAPABILITY_GENERATION.md:88` (Stage 7) and `docs/PROJECT_VISION.md:125` mandate:
  > *"يُمنع قطعيًا العبث بالكود أو الصلاحيات أو قواعد بيانات الإنتاج تلقائياً دون موافقة ورقابة."*
- **Impact:** Automatically activating synthesized `SKILL.md` procedural playbooks alters digital employee runtime behavior in production without human owner review.
- **Verdict:** `CONFIRMED` as a cross-document contradiction (P1).

---

## 4. Deep-Dive Audit: Finding F-14a (OutboxWorker Completely Fair Scheduling Absence)

### 4.1 Repository Evidence
- **File:** `packages/services/outbox_service.py` lines 180–190:
  ```python
  stmt = (
      select(OutboxEvent)
      .where(
          OutboxEvent.status == "pending",
          OutboxEvent.scheduled_at <= now,
      )
  )
  if tenant_id is not None:
      stmt = stmt.where(OutboxEvent.tenant_id == tenant_id)

  stmt = stmt.order_by(OutboxEvent.scheduled_at.asc(), OutboxEvent.created_at.asc()).limit(batch_size)
  ```
- **Consequence:** When the background OutboxWorker runs without a specific `tenant_id`, it claims events ordered purely by `created_at ASC`. If Tenant A enqueues a bulk marketing campaign of 10,000 messages, all batches will pull Tenant A's messages, starving interactive customer replies for Tenant B for minutes or hours.
- **Verdict:** `CONFIRMED` as a critical operational concurrency defect (P0).

---
*End of Runtime & Workflow Findings Evidence Log.*
