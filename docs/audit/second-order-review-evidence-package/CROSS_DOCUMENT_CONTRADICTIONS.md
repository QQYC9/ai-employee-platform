# Cross-Document Contradiction Register: Counts, Severities & Inconsistencies

**Document ID:** `CROSS_DOCUMENT_CONTRADICTIONS`  
**Package:** Second-Order Review Evidence Package  
**Audit Baseline Commit:** `1b3eb775d0c963fc18d9004ea20a2dc1255d5e46`  

---

## 1. Executive Summary

This register catalogs all documented contradictions, count discrepancies, and severity drifts across:
1. The original architecture documents (`docs/architecture/`).
2. The first audit report (`docs/audit/final-vision-architecture-audit/`).
3. The second-order audit report (`docs/audit/second-order-adversarial-audit/`).

---

## 2. Discrepancies in Severity & Classification Across Audits

The second-order audit re-evaluated findings from the first audit. The following table highlights where classifications or severities shifted based on newly uncovered evidence:

| Finding ID | Topic | First Audit Severity | Second-Order Severity | Reason for Shift / Nuance |
| :---: | :--- | :---: | :---: | :--- |
| **F-01** | 15 API Routers Lacking Tenant Context | **P0** | **P1 (High)** | Route handlers currently pass `current_user.tenant_id` manually as arguments, preventing an immediate crash. It is an architectural defect, not an active production outage. |
| **F-04** | HNSW Recall Collapse ($S = 0.0001$) | **P0** | **P1 (High)** | The mathematical refutation of `ef_search = 100` was verified. However, `pgvector 0.8+` supports `hnsw.iterative_scan = 'relaxed_order'`, which prevents zero-recall at the cost of high query latency. |
| **F-07** | PostgreSQL Row-Level Security (RLS) Absence | **P1** | **P2 (Medium)** | Inspection revealed RLS was not promised in `SECURITY_AND_MULTI_TENANCY.md` (only composite primary keys). RLS was introduced by the adversarial reviewer as a proposal. |

---

## 3. Contradictions Between Original Architecture Documents

### Contradiction 1: WhatsApp Quarantine Duration & Re-Dispatch
- **Source A:** `ARCHITECTURAL_CONFLICTS_AND_OPEN_QUESTIONS.md:80`:
  > *"If dispatch times out, place event in a **60-second Quarantine Window**... if no webhook arrives after 60s, **re-dispatch**."*
- **Source B:** `MASTER_ARCHITECTURE_BLUEPRINT.md:396`:
  > *"The task enters a `WAITING_DELIVERY_CONFIRMATION` quarantine window (configurable, **e.g. 15 minutes**)... automatic blind retry is **STRICTLY FORBIDDEN**."*

### Contradiction 2: Optimistic Concurrency Control (`version_id`)
- **Source A:** `ARCHITECTURAL_CONFLICTS_AND_OPEN_QUESTIONS.md:104-112` (Mitigation 2):
  > *"Every task row contains an integer `version_id`... `WHERE id = :task_id AND version_id = :expected_version_id;`"*
- **Source B:** `MASTER_ARCHITECTURE_BLUEPRINT.md:330-345`:
  `execution_tasks` DDL has `fence_token BIGINT NOT NULL DEFAULT 1`, but contains **zero** `version_id` column.

### Contradiction 3: Autonomous Skill Activation
- **Source A:** `PLATFORM_SELF_DEVELOPMENT_RESEARCH.md` Table 2 line 27:
  Tier 3 (New Skill Synthesis: procedural playbooks, `SKILL.md`) is labeled:
  *"Permitted Automation Level: **Autonomous (Offline)**; Authorization Boundary: **Automated**"*.
- **Source B:** `AUTONOMOUS_CAPABILITY_GENERATION.md:88` (Stage 7) & `PROJECT_VISION.md:125`:
  Mandates strict **Human Owner Approval** before any synthesized capability can be activated in production.

### Contradiction 4: Execution Loop Limits
- **Source A:** `ARCHITECTURAL_CONFLICTS_AND_OPEN_QUESTIONS.md:29`:
  > *"Every customer turn is an execution graph bounded by `config.MAX_SUPERSTEPS = 10`."*
- **Source B:** `MASTER_ARCHITECTURE_BLUEPRINT.md:761` (ADR-05):
  > *"Initial hop ceiling set as an uncalibrated hypothesis (`config.MAX_HANDOFF_HOPS = 5`)."*

---
*End of CROSS_DOCUMENT_CONTRADICTIONS.md.*
