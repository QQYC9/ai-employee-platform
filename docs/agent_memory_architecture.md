# Agent Long-Term Memory & Persistent Context Architecture

## 1. Overview & Information Taxonomy

The **Agent Long-Term Memory & Persistent Context Engine** provides Autonomous Digital Employees in the **AI Employee Platform** with bounded, auditable, and privacy-preserving memory.

In commercial multi-tenant environments, digital workers cannot treat every conversational token as permanent memory, nor can they treat institutional policies as customer-specific facts. The platform enforces a strict four-layer information taxonomy:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Information Taxonomy                            │
├─────────────────────────┬──────────────────────────────────────────────┤
│ 1. Conversation History │ Raw messages exchanged in sessions           │
│    (Conversations/Msgs) │ (Verbatim log of what was actually said)     │
├─────────────────────────┼──────────────────────────────────────────────┤
│ 2. Long-Term Memory     │ Selected, verified facts, customer           │
│    (memories table)     │ preferences, verified execution learnings,   │
│                         │ and confirmed decisions                      │
├─────────────────────────┼──────────────────────────────────────────────┤
│ 3. Enterprise Knowledge │ Institutional policies, pricing tables,      │
│    (Knowledge/Brain)    │ product catalogs, and operating procedures   │
├─────────────────────────┼──────────────────────────────────────────────┤
│ 4. Current Task Context │ Ephemeral goal parameters, runtime step      │
│    (TaskContext)        │ outputs, and execution dependencies          │
└─────────────────────────┴──────────────────────────────────────────────┘
```

---

## 2. Memory Lifecycle State Machine

Memories transition through explicit lifecycle states to ensure validity and auditable provenance:

```
[Candidate] ──> [Validation] ──> [Active] ──> [Retrieve & Use]
     │               │              │
     │ (Rejected)    │ (Secrets)    ├──> [Superseded / Deprecated] (Updated fact)
     v               v              ├──> [Invalidated] (Authority correction)
  [Dropped]       [Error]           └──> [Expired] (expires_at passed)
```

1. **Candidate**: A proposed memory extracted from customer messages, task results, or explicit user feedback.
2. **Validation**: Evaluated for credibility, duplicate suppression, and strict secret scanning (rejecting credentials, API keys, tokens).
3. **Active**: Stored in the `memories` table with scoped access (`tenant_id`, optional `customer_id`, `agent_id`).
4. **Retrieve & Use**: Ranked via multi-factor transparent scoring (Importance, Confidence, Recency, Query Relevance) and injected into `AgentContext`.
5. **Supersede / Deprecate**: When a newer trusted fact replaces an old one, the previous memory is linked (`superseded_by`) and marked `deprecated`.
6. **Invalidate**: Explicitly marked invalid by an administrator or verified signal with a recorded reason.
7. **Expire**: Automatically filtered out from active retrieval once `expires_at` is reached.
8. **Audit**: Every lifecycle event (`memory_created`, `memory_updated`, `memory_invalidated`, `memory_deleted`) is recorded via `AuditService`.

---

## 3. Security, Privacy & Secret Sanitization

Enterprise memory systems represent high-value attack surfaces. The engine enforces defense-in-depth security:

1. **Strict Secret Rejection (`MemorySanitizer`)**:
   - Automated regex and heuristic pattern scanning for:
     - API keys (`sk-...`, `ghp_...`, `AKIA...`, `api_key=...`)
     - Bearer tokens (`Bearer ey...`, JWT signatures)
     - Passwords & secrets (`password=...`, `pwd=...`, `secret=...`)
     - Private keys (`-----BEGIN PRIVATE KEY-----`)
   - Any candidate containing detected secrets is immediately rejected (`SecretDetectedError`) and prevented from storage.
2. **Untrusted Context Separation**:
   - Memory content injected into LLM context is framed as passive reference data, never as system-level instructions (`is_system_instruction = False`).
   - Memories can never grant permissions, override `ActionPolicy` rules, or bypass human approvals.
3. **Customer Boundary Isolation**:
   - Customer preferences are scoped via `metadata_json->>'customer_id'`. Customer A's memory is never returned when retrieving context for Customer B.
4. **Tenant Isolation**:
   - All database queries strictly enforce `tenant_id == current_user.tenant_id`. Cross-tenant retrieval is architecturally impossible.

---

## 4. Multi-Factor Context Ranking & Retrieval

Memory retrieval does not dump all entries into prompt context. Retrieval is bounded and ranked via transparent scoring:

$$\text{Score} = \frac{w_i \cdot \text{Importance} + w_c \cdot \text{Confidence} + w_r \cdot \text{Recency} + w_q \cdot \text{Relevance}}{w_i + w_c + w_r + w_q}$$

Where default weights are:
- **Importance Weight ($w_i = 0.40$)**: Significance of the fact to business operations (0–100).
- **Confidence Weight ($w_c = 0.30$)**: Certainty and source authority of the fact (0–100).
- **Recency Weight ($w_r = 0.15$)**: Exponential half-life decay halving approximately every 30 days.
- **Query Relevance Weight ($w_q = 0.15$)**: Lexical token matching and term overlap with the task objective or query.

---

## 5. Conflict Resolution Strategy

When conflicting facts emerge:
1. **Never Silently Overwrite**: The platform never silently discards earlier records.
2. **Explicit Provenance & Linking**:
   - If a new customer preference arrives from the same customer (e.g. switching preferred language from English to Arabic), the old record is updated to `status = "deprecated"` with `metadata_json['superseded_by'] = new_id`.
   - The new record stores `metadata_json['supersedes'] = old_id`.
3. **Uncertain Contradictions**:
   - If conflicting facts originate from ambiguous sources, both remain active with `metadata_json['conflicts_with'] = [other_id]`, flagging the conflict for review or downstream clarification.

---

## 6. Future Extensibility: Vector Embeddings & pgvector

While the current operational environment uses indexed SQL queries, JSONB metadata, and transparent multi-factor ranking:
- The production Docker environment is pre-configured with `pgvector/pgvector:pg17`.
- The `Memory` schema allows adding a vector embedding column (`embedding vector(1536)`) and HNSW index in a subsequent phase when an embedding model provider (e.g. `text-embedding-004`) is activated.
- Current lexical + multi-factor scoring provides immediate, deterministic, zero-dependency retrieval without external API coupling.
