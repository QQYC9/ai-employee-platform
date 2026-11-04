# Evidence Gaps & Open Empirical Questions Dossier

**Document ID:** `EVIDENCE_GAPS_AND_OPEN_QUESTIONS`  
**Package:** Second-Order Review Evidence Package  
**Audit Baseline Commit:** `1b3eb775d0c963fc18d9004ea20a2dc1255d5e46`  

---

## 1. Executive Summary

This dossier catalogs the empirical boundaries of the current evidence base. It separates claims that are conclusively settled by code inspection from claims that cannot be settled without live hardware execution, cluster-level benchmarking, or live telephony sandbox runs.

---

## 2. Settled Findings vs Open Empirical Questions

```text
Conclusively Settled by Primary Evidence:
- F-01: 15 API routers lack tenant context ContextVar (AST parse of apps/agent/main.py).
- F-02: Static AES-256-GCM AAD in packages/core/crypto.py (Code inspection & decryption test).
- F-03: Composite HNSW index unsupported in PostgreSQL (PostgreSQL 17 syntax error reproduction).
- F-05: Missing version_id in Blueprint DDL (DDL inspection in MASTER_ARCHITECTURE_BLUEPRINT.md).
- F-06: Python Callable in JSONB checkpoints (Python json.dumps TypeError reproduction).
- F-07: PostgreSQL RLS missing from migrations (Inspection of 100% of Alembic migrations).
- F-08: Soft deletion leaves PII in immutable HMAC audit logs (Saudi PDPL Art 18 & ORM schema).
- F-09: WhatsApp 60s quarantine contradiction & 24h window inversion (Cross-document & API specs).
- F-10: Telegram alert storm arithmetic (Mathematical derivation & Telegram Bot API rate limits).
- F-11: MAX_SUPERSTEPS=10 vs MAX_HANDOFF_HOPS=5 arithmetic collision (Step consumption tracing).
- F-12: Autonomous skill activation contradiction in Table 2 (Platform Self-Dev doc inspection).
- F-14: OutboxWorker lack of tenant fairness in SQL ordering (outbox_service.py:190 inspection).
```

---

## 3. Detailed Ledger of Open Empirical Questions

### Question 1: Exact Latency Curve of pgvector Iterative Scan vs B-Tree Scan
- **The Gap:** We proved that pgvector 0.8 supports `hnsw.iterative_scan = 'relaxed_order'`, which prevents complete recall collapse. However, the exact latency penalty (whether it takes 20ms or 250ms) for small tenants ($S = 0.0001$) under a 1,000,000-vector dataset remains unmeasured.
- **Specific Experiment Required:** Populate a PostgreSQL 17 test table with 1,000,000 synthetic 1536-dimensional embeddings partitioned across 500 tenant IDs following a Zipfian distribution. Measure p50, p95, and p99 query latency comparing:
  1. Exact B-Tree scan on `(tenant_id, status)` + in-memory cosine distance.
  2. Single shared table with `hnsw.iterative_scan = 'relaxed_order'`.
  3. Declarative table partitioning by `tenant_id`.

### Question 2: Redis CFS Token Bucket Cold Recovery under Live Chaos
- **The Gap:** We proved that in-memory token bucket counters reset on Redis restart. However, whether a slow-start ramp-up (10% floor) successfully avoids Meta Cloud API `#131056` spam blocks under a live 10,000-recipient burst requires live telephony testing.
- **Specific Experiment Required:** Execute `docker kill redis` during an active mock campaign and observe whether outbound rate throttles gracefully resume without HTTP 429 errors.

### Question 3: Container Jail Cold-Start Overhead
- **The Gap:** We proved that ephemeral `uv venv` lacks OS-level security isolation. However, the exact execution latency of Linux `nsjail` containers executing synthesized tools inside Docker worker containers requires physical measurement on target Linux hosts.

---
*End of EVIDENCE_GAPS_AND_OPEN_QUESTIONS.md.*
