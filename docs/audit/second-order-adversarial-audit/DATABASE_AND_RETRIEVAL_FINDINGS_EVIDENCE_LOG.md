# Evidence Log: Database, pgvector, HNSW & Concurrency

**Document ID:** `DATABASE_AND_RETRIEVAL_FINDINGS_EVIDENCE_LOG`  
**Audit Standard:** Second-Order Adversarial Audit  
**Target Findings:** F-03 (Composite HNSW Impossibility), F-04 (Vector Recall Collapse), F-05 (Missing version_id & OCC)

---

## 1. Deep-Dive Audit: Finding F-03 (Composite HNSW Index Impossibility)

### 1.1 Previous Claim
The previous audit asserted that `RESEARCH_EVIDENCE_GAPS.md:29` and `ARCHITECTURAL_CONFLICTS_AND_OPEN_QUESTIONS.md:143` propose a composite HNSW index on `(tenant_id, embedding)`, which PostgreSQL `pgvector` does not support.

### 1.2 Repository Citation
- `docs/architecture/RESEARCH_EVIDENCE_GAPS.md:29`:
  > *"Under high-volume multi-tenant loads (>1,000,000 vector chunks across 500 active tenants), does a single composite HNSW/IVFFlat index on `(tenant_id, embedding)` maintain sub-50ms query latency..."*
- `docs/architecture/RESEARCH_EVIDENCE_GAPS.md:34`:
  > *"Single table with composite HNSW index + `SET LOCAL hnsw.ef_search = 100`."*

### 1.3 Empirical Reproduction in PostgreSQL 17 + pgvector 0.8.7
We executed the following SQL in the live PostgreSQL instance:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TEMPORARY TABLE test_hnsw (tenant_id UUID, embedding vector(3));
CREATE INDEX ON test_hnsw USING hnsw (tenant_id, embedding vector_cosine_ops);
```
- **Observed Database Error:**
  ```text
  psycopg.errors.FeatureNotSupported: access method "hnsw" does not support multicolumn indexes
  ```
- **Technical Reality:** HNSW and IVFFlat index access methods in PostgreSQL are strictly single-column. Proposing a multi-column HNSW index is a **Syntactic Impossibility**.
- **Verdict:** `CONFIRMED` (P0 Blocker).

---

## 2. Deep-Dive Audit: Finding F-04 (Claimed 99% Recall Collapse)

### 2.1 Previous Claim
The previous audit argued that for a small tenant with 100 chunks in a shared table of 1,000,000 chunks (selectivity $S = 0.0001$), `SET LOCAL hnsw.ef_search = 100` yields a **99.00% probability of returning zero matching vectors** under post-filtered graph traversal.

### 2.2 Mathematical Verification & Algorithmic Reality
- **Under Traditional Static HNSW Post-Filtering:**
  - HNSW graph search explores up to `ef_search` candidate nodes based on distance in the global space.
  - If candidate exploration stops after inspecting 100 nodes, and the local tenant selectivity is $S = 0.0001$, the probability of encountering zero matching nodes is $(1 - 0.0001)^{100} = (0.9999)^{100} \approx 99.00\%$.
  - Therefore, the original document's claim (`ARCHITECTURAL_CONFLICTS_AND_OPEN_QUESTIONS.md:116`) that `SET LOCAL hnsw.ef_search = 100` restores recall to >95% is a **Mathematical Fallacy**.
- **Mitigating Factor Discovered in Second-Order Audit:**
  - In `pgvector 0.8+`, PostgreSQL introduced iterative index scanning:
    `SET hnsw.iterative_scan = 'relaxed_order';`
  - When iterative scanning is enabled, pgvector does NOT abort after `ef_search` nodes; it continues traversing graph paths until `LIMIT` matching rows are found or index exhaustion occurs.
  - However, for small tenants with $S = 0.0001$, traversing tens of thousands of graph nodes causes query latency to jump from $<10$ms to hundreds of milliseconds, blowing past the turn SLA.
- **Verdict:** `PARTIALLY CONFIRMED` (P1). The mathematical refutation of `ef_search = 100` is 100% correct, but pgvector 0.8's iterative scan prevents absolute recall collapse at the cost of high latency. The recommended Bimodal architecture (B-Tree scan for $<5,000$ chunks) remains the mathematically optimal remedy.

---

## 3. Deep-Dive Audit: Finding F-05 (Missing `version_id` & Lost Update Anomaly)

### 3.1 Repository Evidence
- **Document:** `docs/architecture/ARCHITECTURAL_CONFLICTS_AND_OPEN_QUESTIONS.md:104-112`:
  > *"Mitigation 2: Database Connection Release vs Lost Updates -> Optimistic Concurrency Control (`version_id`)... Every task row contains an integer `version_id`... `WHERE id = :task_id AND version_id = :expected_version_id;`"*
- **Target DDL in `docs/architecture/MASTER_ARCHITECTURE_BLUEPRINT.md:330`:**
  ```sql
  CREATE TABLE execution_tasks (
      tenant_id UUID NOT NULL,
      execution_id UUID NOT NULL,
      status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
      active_step_index INTEGER NOT NULL DEFAULT 0,
      claimed_by_worker_id VARCHAR(64) NULL,
      lease_expires_at TIMESTAMPTZ NULL,
      fence_token BIGINT NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY (tenant_id, execution_id)
  );
  ```
- **Commit SQL in `MASTER_ARCHITECTURE_BLUEPRINT.md:337`:**
  ```sql
  UPDATE execution_tasks
  SET active_step_index = :new_step_index, updated_at = CURRENT_TIMESTAMP
  WHERE tenant_id = :tenant_id AND execution_id = :execution_id AND fence_token = :expected_fence_token;
  ```

### 3.2 Concurrency Analysis
- `fence_token` protects against a worker whose lease was claimed by another worker node.
- However, if the same worker is executing a turn, and a concurrent webhook modifies the task, `fence_token` does NOT detect the concurrent update.
- More importantly, `Mitigation 2` explicitly promised a `version_id` column which is **completely absent** from the Blueprint DDL and commit SQL.
- **Verdict:** `CONFIRMED` as a cross-document inconsistency (P1).

---
*End of Database & Retrieval Findings Evidence Log.*
