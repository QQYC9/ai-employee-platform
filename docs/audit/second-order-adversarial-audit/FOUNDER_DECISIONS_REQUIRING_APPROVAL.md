# Founder Decisions Requiring Approval: Second-Order Strategic Register

**Document ID:** `FOUNDER_DECISIONS_REQUIRING_APPROVAL`  
**Audit Standard:** Second-Order Adversarial Audit  
**Governing Standard:** `docs/PROJECT_VISION.md` & Master Ground Truth Rules

---

## 1. Executive Summary

This register presents the platform founder with the 6 pivotal architectural decisions whose resolution is mandatory before committing to implementation. Each decision is presented with verified technical realities, viable options, trade-offs, the second-order audit's recommendation, and the cost of reversal.

---

## 2. Master Decision Dossiers

### Decision FD-01: Execution Engine — Dual-Mode (ReAct + Pregel) vs Monolithic Engine
- **Technical Reality:** Pure Pregel Bulk Synchronous Parallel execution incurs 3 full database roundtrips and row locks per turn. For routine customer inquiries (80% of volume), this adds 300–600ms overhead, directly threatening the sub-3s SLA.
- **Options:**
  - *Option A (Monolithic Pregel):* Simpler conceptual model, but fails turn latency SLA and multiplies DB connection pool pressure.
  - *Option B (Dual-Mode Engine — RECOMMENDED):* Sequential ReAct for interactive customer turns (<3s); Pregel StateGraph for asynchronous background workflows and multi-agent handoffs.
- **Recommendation:** **Adopt Option B (Dual-Mode).**
- **Reversal Cost:** Moderate.

### Decision FD-02: Code Synthesis Sandboxing — MicroVMs vs Linux Container Jails
- **Technical Reality:** Ephemeral `uv venv` provides zero OS-level isolation, enabling untrusted synthesized code to read `DATABASE_URL` and compromise the host.
- **Options:**
  - *Option A (Ephemeral uv venv):* Insecure; banned in multi-tenant production.
  - *Option B (Linux Container Jails via nsjail / gVisor — RECOMMENDED FOR DOCKER):* Drops all Linux capabilities, enforces read-only root filesystems, memory limits, and isolated network namespaces in Docker Compose.
  - *Option C (MicroVMs via Firecracker):* True hardware-level virtualization. Cold start ~150ms. Recommended for multi-tenant cloud deployments.
- **Recommendation:** **Adopt Option B locally, Option C in cloud.**
- **Reversal Cost:** High.

### Decision FD-03: Supervisory Architecture — Two-Tier Guardian vs Monolithic Godfather
- **Technical Reality:** The Godfather currently conflates platform infrastructure oversight with tenant-level business operations, creating an unmanageable notification bottleneck for the founder.
- **Options:**
  - *Option A (Single Godfather):* Founder receives operational noise from all 500 tenants.
  - *Option B (Two-Tier Model — RECOMMENDED):* Central Godfather for Platform Founder; Executive Digital Supervisor for Tenant Business Owner.
- **Recommendation:** **Adopt Option B.**
- **Reversal Cost:** Low.

### Decision FD-04: Dynamic Business Modules — Two-Tier Relational vs Flat JSONB
- **Technical Reality:** A flat JSONB table (`business_entities`) cannot enforce double-entry bookkeeping, foreign keys, or high-precision financial constraints.
- **Options:**
  - *Option A (Flat JSONB EAV Only):* Schema flexibility, but high risk of data corruption in financial ledgers.
  - *Option B (Two-Tier Schema — RECOMMENDED):* Pre-migrated dormant relational tables for standard financial archetypes (invoices, inventory) + JSONB for custom extension attributes.
- **Recommendation:** **Adopt Option B.**
- **Reversal Cost:** Very High.

### Decision FD-05: Statutory Data Privacy — Envelope Encryption vs Soft Deletion
- **Technical Reality:** Soft deletion (`status = 'DELETED'`) leaves plaintext customer PII inside immutable HMAC audit logs, violating Saudi PDPL Article 18.
- **Options:**
  - *Option A (Soft Deletion):* Legally non-compliant.
  - *Option B (Envelope Encryption with Customer DSEK Shredding — RECOMMENDED):* Destroying ephemeral keys shreds data permanently while preserving HMAC audit chains.
- **Recommendation:** **Adopt Option B.**
- **Reversal Cost:** High.

### Decision FD-06: Field Acceptance Gate — Mandatory Live Founder Telegram Sessions
- **Technical Reality:** Synthetic unit/integration tests ("green tests") routinely produce false-positive readiness declarations.
- **Recommendation:** **Reaffirm ADR-15 as non-negotiable.**
- **Reversal Cost:** Zero.

---
*End of Founder Decisions Requiring Approval.*
