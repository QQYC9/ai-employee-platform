# Empirical Evidence Gaps & Required Validation Experiments

**Document ID:** `EVIDENCE_GAPS_AND_REQUIRED_EXPERIMENTS`  
**Audit Standard:** Second-Order Adversarial Audit (Empirical Benchmark Catalog)  
**Governing Standard:** `docs/PROJECT_VISION.md` Section 17

---

## 1. Executive Summary

Static code inspection and architectural deduction cannot answer all performance and resilience questions. This document explicitly catalogs the remaining empirical evidence gaps and details the exact benchmarking experiments required during Phase 2 prototyping.

---

## 2. Master Empirical Experiments Catalog

### Experiment 1: Zipfian Multi-Tenant pgvector Retrieval Benchmark
- **The Empirical Question:** Under a realistic Zipfian (Power-Law) distribution of 500 tenants and 1,000,000 vectors, what is the exact recall and latency curve comparing:
  1. Exact B-Tree scan on `(tenant_id, status)` + in-memory cosine distance.
  2. Single shared table with `hnsw.iterative_scan = 'relaxed_order'`.
  3. Declarative table partitioning by `tenant_id` group.
- **Hypothesis:** For tenants with $<5,000$ chunks (selectivity $S < 0.5\%$), Exact B-Tree scan will execute in $<2$ms with 100% recall, while unpartitioned HNSW iterative scan will degrade to $>50$ms.
- **Experiment Design:** Synthetic dataset in PostgreSQL 17 with 1536-dimensional vectors; measure p50, p95, p99 latency and recall@5 across tenant tiers.

### Experiment 2: Redis CFS Token Bucket Recovery Chaos Test
- **The Empirical Question:** When Redis crashes during a 10,000-recipient outbound campaign, does a slow-start ramp-up (10% floor) prevent Meta WhatsApp Cloud API rate limiting and quality rating degradation?
- **Experiment Design:** Run simulated outbound campaign; execute `docker kill redis`; monitor outbound request rate and verify zero duplicate dispatches.

### Experiment 3: Container Jail Cold-Start Latency
- **The Empirical Question:** What is the p99 cold-start execution latency of Linux `nsjail` containers executing synthesized Python tools inside a Docker worker container?
- **Experiment Design:** Measure 1,000 consecutive tool invocations under memory (128 MB) and CPU (0.5 vCPU) constraints; verify complete isolation from host environment variables.

### Experiment 4: Telegram MarkdownV2 UTF-16 Streaming Stress Test
- **The Empirical Question:** Does streaming live tokens via `editMessageText` every 300ms across 4,000 UTF-16 code units with astral emojis maintain entity tag balance without triggering Telegram API 400 errors?
- **Experiment Design:** Stream 100 long Arabic responses containing mixed bold, code, and emoji combinations; measure error rate and token throughput.

---
*End of Evidence Gaps & Required Validation Experiments.*
