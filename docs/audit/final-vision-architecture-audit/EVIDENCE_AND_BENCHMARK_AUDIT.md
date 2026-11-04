# Empirical Evidence & Benchmark Validity Audit: Epistemological Ledger

**Document ID:** `EVIDENCE_AND_BENCHMARK_AUDIT`  
**Governing Standard:** Full-Platform Target Vision (`docs/PROJECT_VISION.md` Section 17)  
**Audit Standard:** Strict Epistemological Classification (Fact vs Inference vs Proposal vs Hypothesis)  
**Target Repository:** `QQYC9/ai-employee-platform` (Local HEAD `fc94752`)

---

## 1. Executive Summary & Epistemological Classification

Every major architectural claim across the 76 published documents was audited against primary source code, commit history, and mathematical/protocol realities.

```text
Epistemological Classification Tiers:
- VERIFIED FACT: Directly inspected in repository code or vendor protocol specs with 100% empirical evidence.
- ARCHITECTURAL INFERENCE: Logical deduction derived from verified facts, but requiring operational validation.
- CONSTRUCTIVE PROPOSAL: Target architectural design not yet implemented in code.
- EMPIRICAL HYPOTHESIS: Unverified claim or assumption requiring experimental benchmarking before acceptance.
- UNRESOLVED CONTRADICTION: Conflicting statements across documents that must be formally reconciled.
```

---

## 2. Master Epistemological Claim Audit Ledger

| Claim ID | Architectural Claim | Current Document Classification | Audit Epistemological Reality | Evidence & Ground Truth Reference | Severity / Impact |
| :---: | :--- | :---: | :---: | :--- | :---: |
| **E-01** | Legacy turn engine (`ConversationTurnService`) was monolithic and unmaintainable. | Verified Fact | **VERIFIED FACT** | 1,220 lines in `packages/services/conversation_turn_service.py` with tight coupling and regression history. | Supported |
| **E-02** | pgvector supports composite HNSW index on `(tenant_id, embedding)`. | Proposed Design | **SYNTACTIC IMPOSSIBILITY** | `RESEARCH_EVIDENCE_GAPS.md:29`. PostgreSQL `pgvector` throws syntax error on composite HNSW indexes. | **P0** |
| **E-03** | `SET LOCAL hnsw.ef_search = 100` restores vector recall to >95% for small tenants. | Accepted Mitigation | **MATHEMATICAL FALLACY** | For $S = 0.0001$, $(1 - S)^{100} = 99\%$ probability of ZERO matching candidates. True recall is ~1%. | **P0** |
| **E-04** | Static AST node whitelisting guarantees Python code synthesis safety. | Security Invariant | **PROVEN BYPASSABLE** | Python CPython reflection (`().__class__.__base__.__subclasses__()`) executes arbitrary code without forbidden AST nodes. | **P0** |
| **E-05** | Ephemeral `uv venv` provides complete sandboxed execution for untrusted tools. | Security Architecture | **SANDBOX ILLUSION** | Subprocess inherits environment variables (`DATABASE_URL`, `JWT_SECRET_KEY`) and unshielded host network. | **P0** |
| **E-06** | 15 API routers in `apps/agent/main.py` fail to activate tenant context ContextVar. | Audit Finding | **VERIFIED FACT** | Confirmed by AST scan: 15 routers use `get_current_user` without invoking `get_tenant_context`. | **P0** |
| **E-07** | Integration secrets are encrypted using AES-256-GCM with tenant-bound AAD. | Security Invariant | **DEFECTIVE IN CODE** | `packages/core/crypto.py:45` uses static global `ASSOCIATED_DATA = b"ai-employee-platform-secret-v1"`. | **P0** |
| **E-08** | Inbound WhatsApp customer messages can fail due to 24-hour service window expiry. | Empirical Gap 6 | **CONCEPTUAL INVERSION** | Inbound messages RESET the 24h window. Meta error #131047 occurs only on outbound campaigns and delayed approvals. | **P0** |
| **E-09** | OutboxWorker enforces Completely Fair Scheduling across tenants via PostgreSQL. | Operational Blueprint | **FALSE CLAIM IN CODE** | `outbox_service.py:180-197` orders purely by `created_at ASC`. 10,000-message campaign starves interactive turns. | **P0** |
| **E-10** | Telegram alert coalescing with 5-second sliding window prevents API 429 rate limits. | Accepted Mitigation | **MATHEMATICAL MISCALCULATION** | 5s window emits 12 msgs/min = 240 msgs in 20m. Telegram private chats ban bots exceeding ~20 msgs/min. | **P0** |
| **E-11** | Optimistic Concurrency Control via `version_id` prevents lost updates during streaming. | Accepted Mitigation | **PHANTOM SPECIFICATION** | `version_id` column is completely absent from `execution_tasks` DDL and commit logic. | **P0** |
| **E-12** | Database Row-Level Security (RLS) enforces multi-tenancy at the PostgreSQL kernel. | Security Invariant 4 | **ZERO RLS IN CODE** | Verified across all Alembic migrations: zero RLS policies exist in PostgreSQL. | **P1** |
| **E-13** | Frontend dashboards parse 18-digit financial string decimals using `BigInt`. | Data Mitigation 5 | **SYNTAX ERROR IN JS** | `BigInt("1250000.5000")` throws runtime `SyntaxError`. Neither dashboard includes `decimal.js`. | **P1** |
| **E-14** | Soft deletion (`status = 'DELETED'`) complies with Saudi PDPL & GDPR Right to Erasure. | Privacy Architecture | **STATUTORY VIOLATION** | Raw PII remains in immutable HMAC audit logs and checkpoints. Requires Envelope Encryption key shredding. | **P0** |

---

## 3. Audit of Proposed Benchmarks in `RESEARCH_EVIDENCE_GAPS.md`

### 3.1 Gap 1: pgvector Multi-Tenant Partitioning Benchmark
- **Flaw:** Document proposes testing 1,000,000 chunks across 100 uniform tenants (10,000 chunks/tenant).
- **Reality:** Real SaaS data follows a **Zipfian Power-Law distribution** across 500 tenants. Uniform 100-tenant testing conceals the extreme sparsity ($S < 0.01\%$) where post-filtered graph traversal completely collapses.
- **Required Benchmark:** 500 tenants distributed Zipfian (top 5 tenants with 50,000 chunks; bottom 295 tenants with $<200$ chunks). Compare Exact B-Tree scan vs Partitioned HNSW vs Iterative scan.

### 3.2 Gap 2: Redis CFS Token Bucket Recovery under Node Crash
- **Flaw:** Proposed testing `docker kill redis` without defining the recovery algorithm.
- **Required Specification:** Benchmark slow-start token initialization (10% floor) and PostgreSQL recent dispatch history query latency ($<5$ms) during simulated 10,000-message campaign.

### 3.3 Gap 3: Sandbox Isolation Performance: UV Virtualenv vs MicroVM
- **Flaw:** Frames the choice as a performance trade-off, ignoring the critical security boundary.
- **Required Specification:** Ephemeral `uv venv` cannot be used in multi-tenant production regardless of latency. Benchmark Firecracker cold-start ($<150$ms) vs Linux `gVisor` / `nsjail` containers ($<30$ms).

---
*End of Empirical Evidence & Benchmark Validity Audit.*
