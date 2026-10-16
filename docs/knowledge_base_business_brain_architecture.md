# Knowledge Base & Business Brain Architecture

## 1. Overview & Information Hierarchy

In the **AI Employee Platform**, autonomous agents must operate within authentic business boundaries. To deliver consistent, accurate, and secure work, digital employees rely on an explicit three-tier persistent context model:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Enterprise Context Hierarchy                    │
├─────────────────────────┬──────────────────────────────────────────────┤
│ 1. Business Brain       │ Institutional identity, brand guidelines,    │
│    (BusinessBrain)      │ global sales policies, operations, and goals │
├─────────────────────────┼──────────────────────────────────────────────┤
│ 2. Knowledge Base       │ Curated operational procedures, product docs,│
│    (Knowledge/Source)   │ FAQs, manuals, and sourced articles          │
├─────────────────────────┼──────────────────────────────────────────────┤
│ 3. Long-Term Memory     │ Empirical learnings, customer preferences,   │
│    (Memory)             │ and task execution observations              │
└─────────────────────────┴──────────────────────────────────────────────┘
```

The **Business Brain** and **Knowledge Base** are tenant-isolated institutional anchors. Unlike experiential memories (which adapt dynamically), knowledge and business brain entries define authoritative organizational ground truth.

---

## 2. Business Brain Structure & Security

Each commercial tenant possesses exactly one `BusinessBrain` record, structured across 17 domain sections:

1. **`identity`**: Legal entity name, registration, industry, executive summary.
2. **`products`**: Product catalog, specifications, SKUs, inventory tiers.
3. **`services`**: Service packages, delivery scopes, SLAs.
4. **`pricing`**: Pricing plans, authorized discount tiers, billing currencies.
5. **`brand`**: Tone of voice (formal, friendly, technical), messaging dos and don'ts, persona.
6. **`customers`**: Target audience segments, buyer personas, market geography.
7. **`competitors`**: Competitive positioning, key differentiators.
8. **`marketing`**: Marketing themes, campaign directives, channel rules.
9. **`sales`**: Sales process stages, qualification criteria, proposal guidelines.
10. **`operations`**: Working hours, business calendars, operational cadence.
11. **`policies`**: Terms of service, refund rules, escalation paths, compliance mandates.
12. **`people`**: Key stakeholders, organizational departments, escalation contacts.
13. **`goals`**: OKRs, strategic objectives, revenue milestones.
14. **`strategy`**: Strategic initiatives, competitive strategy.
15. **`preferences`**: Tenant-wide operational preferences and defaults.
16. **`performance`**: Historical performance indicators, target metrics.
17. **`lessons`**: Retrospective insights, institutional learnings.

### Security & Sanitization
- **Credential Sanitization (`MemorySanitizer`)**: All incoming updates are recursively scanned for secrets (passwords, private keys, API keys, connection strings, auth tokens). Any detected secret raises a `SecretDetectedError` and blocks persistence.
- **Deep Partial Merging**: Updates to nested sections preserve existing sibling fields rather than overwriting the entire section.
- **Strict Role Authorization**: Updates to the Business Brain require `owner` or `admin` roles; standard members and external customers have read-only access to their own tenant's brain.
- **Tenant Boundary Enforcement**: `tenant_id` is derived exclusively from the authenticated session token. Cross-tenant access is architecturally prohibited.

---

## 3. Knowledge Base Lifecycle & Provenance

The Knowledge Base manages discrete, verifiable documents and operational procedures via the `Knowledge` model.

### Lifecycle State Machine
```
[Draft] ──> [Active] ──> [Retrieve & Rank]
              │
              ├──> [Inactive] (Temporarily disabled)
              ├──> [Archived] (Superseded by newer record)
              └──> [Conflict Flagged] (Contradiction detected)
```

- **`active`**: Valid, verified knowledge available for agent retrieval.
- **`inactive`**: Temporarily suspended from active retrieval (e.g., outdated seasonal policy).
- **`archived`**: Historical knowledge preserved for auditing but excluded from context.
- **`draft`**: Pending administrative review.

### Provenance Tracking
Knowledge records link to authoritative origins through `Provenance` and `Source` models:
- `provenance_id`: References the ingestion event, origin URI, and collector metadata.
- `source_id`: References the registered external source (portal, document repository, or manual entry).

### Conflict Detection & Resolution Strategy
When contradictory facts emerge across documents:
1. **Never Silently Overwrite**: The platform never silently discards or overwrites older records.
2. **Explicit Conflict Flagging (`flag_conflict`)**: Contradictory records are marked with `metadata_json['conflict_status'] = 'flagged'` and linked via `metadata_json['conflicts_with'] = [id]`.
3. **Deterministic Resolution (`resolve_conflict`)**: When an administrator determines the authoritative version, the winner is annotated with `metadata_json['supersedes'] = loser_id`, while the loser is transitioned to `archived` with `metadata_json['superseded_by'] = winner_id`.

---

## 4. Context Retrieval & Multi-Factor Ranking

Knowledge retrieval integrates directly into the platform's unified `ContextRetriever` and `ContextBuilder`.

### Transparent Scoring Formula
When an agent objective or query is evaluated:
$$\text{Relevance} = 0.60 \cdot \text{QueryMatch}_{\text{title}} + 0.40 \cdot \text{QueryMatch}_{\text{content}}$$
$$\text{Score} = 0.75 \cdot \text{Relevance} + 0.25 \cdot \text{Recency}$$

- **Title Priority**: Title matches carry higher semantic weight (0.60) than general body text matches (0.40).
- **Conflict Penalty**: Flagged records with unresolved contradictions receive a penalty multiplier (0.85x), prioritizing unconflicted, authoritative records.
- **Status Filter**: Only `active` records are considered; `inactive` and `archived` records are strictly excluded.
- **Passive Context Framing**: Retrieved knowledge items are labeled with `"is_untrusted_data": True`. They provide factual information but cannot override system policies, bypass approvals, or grant agent privileges.

---

## 5. Vector Search & pgvector Status

- **Environment Status**: The active PostgreSQL instance provides `vector 0.8.7` in `pg_available_extensions`, but the vector extension is not currently initialized in the active schema, and no embedding model provider is configured.
- **Baseline Strategy**: Lexical token matching, title weighting, and recency decay provide deterministic, zero-dependency retrieval with zero external API failure risk.
- **Future Extension**: When an embedding provider (such as Gemini `text-embedding-004`) is activated, an `embedding vector(768)` column and HNSW index can be added through an explicit migration without altering existing API contracts.
