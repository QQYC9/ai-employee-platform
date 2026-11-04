# Epistemological Ledger: Confirmed vs Unverified Findings

**Document ID:** `CONFIRMED_VS_UNVERIFIED_FINDINGS`  
**Audit Standard:** Second-Order Adversarial Audit (Epistemological Separation)  
**Governing Standard:** `docs/PROJECT_VISION.md` Section 17

---

## 1. Classification Overview

To prevent architectural drift and premature declarations, every finding is classified into distinct categories:
- **CONFIRMED (11 Findings):** Direct repository code, database reproduction, vendor protocol, or mathematical proof.
- **PARTIALLY CONFIRMED (3 Findings):** Core issue exists, but severity was overstated or mitigated by recent technical updates.
- **UNVERIFIED (0 Findings):** All 14 findings have been independently examined with direct evidence.
- **INCORRECT (0 Findings):** None of the 14 previous findings were fabricated.

---

## 2. Detailed Breakdown by Category

### Category A: Confirmed Findings (11 Items)
1. **F-01 (15 API Routers Lacking Tenant Context):** Confirmed in `apps/agent/main.py` and `api/v1/*.py`.
2. **F-02 (Static AES-256-GCM AAD):** Confirmed in `packages/core/crypto.py:45`.
3. **F-03 (Composite HNSW Impossibility):** Confirmed by PostgreSQL `pgvector 0.8.7` syntax error.
4. **F-05 (Missing `version_id` OCC):** Confirmed absent from `MASTER_ARCHITECTURE_BLUEPRINT.md:330`.
5. **F-06 (Python Callable in JSONB Handoff Contracts):** Confirmed in `MASTER_ARCHITECTURE_BLUEPRINT.md:161`.
6. **F-08 (Saudi PDPL Soft Deletion Failure):** Confirmed by statutory text and immutable HMAC design.
7. **F-09 (WhatsApp Quarantine Contradiction & 24h Window Inversion):** Confirmed in Conflict 4 vs Blueprint §5.5 and Gap 6.
8. **F-10 (Telegram Alert Storm Arithmetic):** Confirmed by 5-second sliding window math ($240\text{ msgs/20m}$).
9. **F-11 (Supersteps vs Handoffs Arithmetic Collision):** Confirmed by graph step consumption ($10 \ge 10$).
10. **F-12 (Autonomous Skill Activation Contradiction):** Confirmed in Table 2 line 27 vs Stage 7.
11. **F-13 (Chatbot Collapse & Omission of Episodic Memory):** Confirmed by lack of scheduler and memory tier design.
12. **F-14 (OutboxWorker CFS Absence & Hardcoded Secret):** Confirmed in `outbox_service.py:190` and `approval_service.py:113`.

### Category B: Partially Confirmed Findings (2 Items)
1. **F-04 (Claimed 99% Recall Collapse):** The mathematical refutation of `ef_search = 100` is confirmed for static graph search. However, pgvector 0.8+ supports `hnsw.iterative_scan = 'relaxed_order'`, mitigating absolute zero-recall at the cost of high query latency.
2. **F-07 (PostgreSQL Row-Level Security):** The absence of RLS in the database is confirmed. However, RLS was not promised in the original blueprint; it is a recommended defense-in-depth proposal with connection pooling trade-offs.

---
*End of Confirmed vs Unverified Findings Ledger.*
