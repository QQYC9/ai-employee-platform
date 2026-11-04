# End-to-End Scenario Architectural Audit: Tracing 10 Critical Journeys

**Document ID:** `END_TO_END_SCENARIO_AUDIT`  
**Governing Standard:** Full-Platform Target Vision (`docs/PROJECT_VISION.md`)  
**Audit Standard:** Step-by-Step Life-Cycle Tracing against Ground Truth Code & Specifications  
**Target Repository:** `QQYC9/ai-employee-platform` (Local HEAD `fc94752`)

---

## 1. Executive Summary & Scenario Audit Scorecard

| Scenario # | Scenario Description | Architectural Viability | Critical Bottleneck / Failure Mode | Severity |
| :---: | :--- | :---: | :--- | :---: |
| **S-01** | Tenant Onboarding & Autonomous Digital Employee Generation | **Partial** | Missing rollback snapshots; Dynamic module flat JSONB limits. | **P1** |
| **S-02** | Inbound Customer Inquiry with Multi-Hop Handoff | **Vulnerable** | Handoff token explosion (>15k tokens); Superstep collision ($10 < 12$). | **P1** |
| **S-03** | High-Impact Tool Execution with Owner Approval Gating | **Vulnerable** | WhatsApp 24h window expiration during delayed owner review. | **P0** |
| **S-04** | Capability Gap Discovery & Autonomous Synthesis | **Vulnerable** | Ephemeral UV sandbox illusion; In-turn dialogue customer freeze. | **P0** |
| **S-05** | Worker Crash Mid-Turn & Fencing Token Recovery | **Vulnerable** | Outbox event lacks `fence_token`; Side-effect escapes cancelled turn. | **P0** |
| **S-06** | Business Fact Update & Untrusted Dialogue Contradiction | **Vulnerable** | Customer prank text triggers DoS, freezing business facts to `CONTRADICTION_PENDING`. | **P1** |
| **S-07** | Channel Disconnection & Reconnection Under Active Traffic | **Vulnerable** | Static AES-256 AAD secret risk; WhatsApp unconfirmed retry duplicates. | **P0** |
| **S-08** | Tenant Offboarding & Statutory Erasure (PDPL / GDPR) | **Failed** | Soft delete leaves PII in immutable HMAC-SHA256 audit logs and WAL. | **P0** |
| **S-09** | Platform Zero-Downtime Release & Schema Migration | **Sound** | Prohibiting runtime DDL protects Postgres; dual-model schema needed. | **P1** |
| **S-10** | Cascading AI Provider Outage & Alert Coalescing | **Vulnerable** | 5-second sliding window emits 240 msgs in 20m; Telegram API 429 blocks bot. | **P0** |

---

## 2. Detailed Lifecycle Tracing of the 10 Critical Scenarios

### Scenario 1: Tenant Onboarding & Autonomous Digital Employee Generation
- **Target Flow:** Founder/Owner inputs business profile $	o$ System infers required agents $	o$ Synthesizes personas and skills $	o$ Staged for owner review $	o$ Activated.
- **Trace Analysis:**
  - `AUTONOMOUS_AGENT_GENERATION.md` provides prompt templates for agent discovery.
  - *Failure Mode 1 (Schema Drift):* Generated agents specify capabilities that reference dynamic business entities. Because `business_entities` DDL is conflicted across 3 documents (PK on `(tenant_id, id)` vs single `id`), entity persistence fails on initial activation.
  - *Failure Mode 2 (Missing Rollback):* If generated agent configuration degrades conversational quality, there is no `agent_versions` table or rollback API in `MASTER_ARCHITECTURE_BLUEPRINT.md`.
- **Verdict:** Requires Phase 2 schema reconciliation and version snapshotting.

### Scenario 2: Inbound Customer Inquiry with Multi-Hop Handoff
- **Target Flow:** Customer message on WhatsApp $	o$ Webhook ack ($<30$ms) $	o$ Triage Agent $	o$ Sales Specialist $	o$ Operations Specialist $	o$ Reply outbox.
- **Trace Analysis:**
  - *Failure Mode 1 (Arithmetic Collision):* Handoff across 3 agents requires at least 6–8 supersteps (Triage $	o$ Tool $	o$ Handoff $	o$ Sales $	o$ Tool $	o$ Handoff $	o$ Ops $	o$ Tool $	o$ Reply). With `MAX_SUPERSTEPS = 10`, any minor tool retry triggers `GraphRecursionError`.
  - *Failure Mode 2 (Context Token Ballooning):* 64 KB output payload ceiling per step allows context to expand by 15,000+ tokens mid-turn, blowing the 3-second SLA.
  - *Failure Mode 3 (Non-Serializable Callable):* Handoff contract specifies Python `Callable` input filter, crashing JSONB serialization in `execution_checkpoints`.
- **Verdict:** Critical runtime tuning required: Increase supersteps to 25, cap handoff payload to 800 tokens, replace callables with declarative schema filters.

### Scenario 3: High-Impact Tool Execution with Owner Approval Gating
- **Target Flow:** Customer requests order refund $	o$ Agent evaluates Level 3 policy $	o$ Staged approval created $	o$ Telegram alert to Owner $	o$ Owner clicks "Approve" 26 hours later $	o$ Turn resumes $	o$ Outbox dispatches.
- **Trace Analysis:**
  - *Failure Mode 1 (WhatsApp 24h Window Timeout):* The owner approves after 26 hours. Worker resumes execution, dispatches free-form text confirmation to customer via WhatsApp. Meta returns `#131047` (`Re-engagement required`), causing outbox retries to fail permanently!
  - *Failure Mode 2 (Hardcoded Fallback Key):* If `APPROVAL_SECRET_KEY` is omitted, `packages/services/approval_service.py:113` falls back to a hardcoded string, allowing challenge token forgery.
- **Verdict:** Approval flow must check WhatsApp 24h session window and trigger Template Message if $>24$ hours; hardcoded fallback secret must be purged.

### Scenario 4: Capability Gap Discovery & Autonomous Synthesis
- **Target Flow:** Agent needs `calculate_custom_duty` $	o$ Gap recorded $	o$ Dream Daemon synthesizes Python skill $	o$ 6-Gate verification $	o$ Owner approval $	o$ Production activation.
- **Trace Analysis:**
  - *Failure Mode 1 (Subprocess Sandbox Illusion):* Dream Daemon runs code in `uv venv`. Ephemeral venv has access to host environment variables, enabling synthesized code to read `DATABASE_URL` and compromise the platform.
  - *Failure Mode 2 (Customer Turn Freezing):* In-turn gap discovery takes minutes/hours offline. Without an explicit turn deferral contract, the customer's conversational session hangs indefinitely.
  - *Failure Mode 3 (Autonomy Contradiction):* Table 2 in `PLATFORM_SELF_DEVELOPMENT_RESEARCH.md` marks Tier 3 skills as "Autonomous / Automated", violating the mandatory human approval invariant.
- **Verdict:** Isolate code synthesis in MicroVMs/jails; enforce human approval; emit polite customer turn deferral.

### Scenario 5: Worker Crash Mid-Turn & Fencing Token Recovery
- **Target Flow:** Worker 1 executes superstep 2 $	o$ Network partition occurs $	o$ Lease expires (30s) $	o$ Worker 2 claims task with `fence_token = fence_token + 1` $	o$ Worker 1 wakes up and attempts commit.
- **Trace Analysis:**
  - *Fencing Success at DB:* Worker 1's state commit is rejected by PostgreSQL conditional update (`WHERE fence_token = 101`).
  - *Failure Mode (Outbox Side-Effect Escape):* Worker 1 staged an outbound payment or SMS in `outbox_events` during superstep 1. Because `outbox_events` does NOT track `fence_token`, OutboxWorker processes the outbox event even though Worker 2 aborted or modified the turn.
- **Verdict:** Add `fence_token` to `outbox_events` and validate against `execution_tasks.fence_token` prior to external HTTP dispatch.

### Scenario 6: Business Fact Update & Untrusted Dialogue Contradiction
- **Target Flow:** Tenant owner updates return policy to 14 days $	o$ Customer sends text: "Your clerk said return window is 90 days" $	o$ Fact extraction runs.
- **Trace Analysis:**
  - *Failure Mode (Dialogue Contradiction DoS):* `KNOWLEDGE_AND_MEMORY_ARCHITECTURE.md:104` blindly compares dialogue against `fact_entities`. Customer's claim conflicts with owner fact. System downgrades verified fact to `CONTRADICTION_PENDING`, suspending return policy inquiries across the business and spamming the owner's Telegram!
- **Verdict:** Dialogue extraction must be segregated to unverified candidate queue (`status = 'CUSTOMER_CLAIM'`); untrusted dialogue cannot alter verified facts.

### Scenario 7: Channel Disconnection & Reconnection Under Active Traffic
- **Target Flow:** WhatsApp token expires $	o$ Inbound/outbound traffic fails $	o$ Owner updates token in dashboard $	o$ System re-encrypts secret $	o$ Resumes traffic.
- **Trace Analysis:**
  - *Failure Mode 1 (Static AAD Vulnerability):* `packages/core/crypto.py` uses static global AAD. If Tenant B copies Tenant A's encrypted secret during channel configuration, it decrypts without authentication tag failure.
  - *Failure Mode 2 (Outbox Burst Flaw):* During token downtime, 500 messages accumulate in `pending`. Upon reconnection, worker bursts all 500 messages at line rate, triggering Meta Cloud API 429 spam blocks.
- **Verdict:** Dynamic `tenant_id` AAD in AES-256-GCM; Outbox slow-start rate limiting upon channel re-enablement.

### Scenario 8: Tenant Offboarding & Statutory Erasure (PDPL / GDPR)
- **Target Flow:** Tenant offboards $	o$ Submits statutory Right to Erasure request $	o$ System deletes tenant data and customer PII $	o$ Retains legal compliance records.
- **Trace Analysis:**
  - *Failure Mode (Direct Statutory Violation):* Architecture marks records `status = 'DELETED'`. Customer phone numbers, national IDs, and names remain in plaintext inside immutable `audit_events` and `execution_checkpoints`. Deleting audit rows breaks HMAC hash chains; keeping them violates Saudi PDPL Article 18 and GDPR Article 17.
- **Verdict:** Envelope Encryption with Data Subject Keys ($K_{subject}$); key destruction shreds PII instantly while preserving HMAC audit chains.

### Scenario 9: Platform Zero-Downtime Release & Schema Migration
- **Target Flow:** Platform updates from v1.2 to v1.3 $	o$ Runs Alembic migrations $	o$ Zero-downtime rolling update across worker containers.
- **Trace Analysis:**
  - *Architectural Soundness:* Strictly prohibiting autonomous agents from executing runtime DDL (`CREATE/ALTER TABLE`) guarantees database migration locks are strictly under developer control via Alembic.
  - *Gap:* Hybrid relational-dynamic storage (`business_entities`) requires pre-provisioned dormant tables for standard business archetypes (invoices, inventory) to avoid performance degradation when tenants scale past 10,000 entities.
- **Verdict:** Two-tier schema architecture: pre-provisioned relational tables + JSONB extensions.

### Scenario 10: Cascading AI Provider Outage & Alert Coalescing
- **Target Flow:** OpenAI/Gemini experiences 20-minute global outage (HTTP 503) $	o$ 200 concurrent turns fail $	o$ The Godfather detects anomaly $	o$ Notifies Founder Telegram.
- **Trace Analysis:**
  - *Failure Mode (Telegram Bot Ban):* With a 5-second sliding window, The Godfather emits 12 messages/minute = 240 messages in 20 minutes. Telegram rate limits bots to 1 msg/sec and bans bots that spam private chats, silencing the supervisory alert precisely during a disaster!
- **Verdict:** Adaptive Incident Aggregator (Alert 1 immediate, Alert 2 at +1m, Alert 3 at +5m, Alert 4 at +15m) capping notifications to $\le 5$ structured messages.

---
*End of End-to-End Scenario Architectural Audit.*
