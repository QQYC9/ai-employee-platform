# Architecture & Engineering Decisions Log (DECISIONS.md)

This log records major design and implementation choices, including rationale and trade-offs.

---

## Decision 0.1: Chronological Message Window via Reverse-Ordered Fetch
- **Context**: `ConversationService.list_messages` previously sorted ascending with `.limit(N)`. For conversations with more than 15 messages, this retrieved the earliest 15 messages and discarded the most recent turns.
- **Decision**: Query the latest `limit` messages sorted descending (`created_at.desc()`), and reverse the slice in memory (`[::-1]`) before returning.
- **Rationale**: Ensures the agent prompt always sees the freshest conversational context up to the limit while maintaining chronological order for LLM dialogue turns.

---

## Decision 0.2: Unified Context Assembly for Owner Conversations
- **Context**: `_process_owner_message` previously passed only the latest raw message string to `provider.generate_text`, lacking BusinessBrain context, recent history, and anti-hallucination instructions.
- **Decision**: Provide the owner chat LLM prompt with:
  1. Verified BusinessBrain facts and knowledge snippets.
  2. The last 15 messages of conversation history.
  3. The identical anti-hallucination constraint instructing the model to state clearly when information is missing rather than inventing details.
- **Rationale**: Prevents contradictory or fabricated answers when owners query their own store information or products.

---

## Decision 0.3: Complete BusinessBrain Prompt Injection
- **Context**: `_construct_prompt` only checked 5 sections (`identity`, `products`, `services`, `pricing`, `policies`), ignoring branches, delivery locations, and working hours stored in `operations` or other columns.
- **Decision**: Dynamically iterate over all populated non-empty sections of `BusinessBrain` (including `operations`, `brand`, etc.) and format them cleanly into the prompt.
- **Rationale**: Ground truth store data like branch locations and business hours must be visible to the LLM to answer basic customer inquiries accurately.

---

## Decision 0.4: Regex Entity Cleaning & Filler Word Normalization
- **Context**: The regex in `_extract_business_knowledge` greedily captured filler phrases such as "الرسمي لمنشأتنا" when owners said "الاسم التجاري الرسمي لمنشأتنا المنذر تكنولوجي".
- **Decision**: Add pre-cleaning to strip formal qualifiers and possessive prefixes (`الرسمي`, `المعتمد`, `لدينا`, `لمنشأتنا`, `الخاص`) from captured entity names.
- **Rationale**: Ensures clean business names in the persistent database without conversational residue.

---

## Decision 0.5: Post-Generation Hallucination Guardrail in Customer Reply Path
- **Context**: The platform lacked any post-generation verification, allowing any model hallucination (prices, unverified features, fake discounts) to be sent directly to customers.
- **Decision**: Inspect the LLM output before persistence and channel dispatch:
  - Check for mention of prices (numbers followed by currency like ريال / SAR / $).
  - Verify if those prices exist in `business_brain.products` / `pricing` or verified knowledge.
  - If unverified financial or pricing claims are detected, block the message, substitute a polite human escalation handoff ("سأحوّل استفسارك للموظف المختص وسيرد عليك قريبًا"), and log an audit event.
- **Rationale**: Safeguards business reputation and financial integrity by rejecting unauthorized customer pricing promises.

---

## Decision 0.6: Explicit Capability Prohibitions in System Instructions
- **Context**: The LLM could promise capabilities not supported by platform tools (e.g., booking appointments, phone calls, sending links, graphic designs, or free trials).
- **Decision**: Injected rule 7 in `system_instruction` explicitly prohibiting these promises and directing the model to offer human team handoff.
- **Rationale**: Prevents broken customer expectations and keeps the digital employee strictly bounded to actual platform capabilities.

---

## Decision 0.7: Read-Back Value Confirmations
- **Context**: When the owner taught information, the agent echoed the parsed dictionary rather than what was actually written to PostgreSQL.
- **Decision**: Flush the transaction and query `refreshed_brain = brain_svc.get_brain(tenant_id)` to display the exact values committed to the database.
- **Rationale**: Guarantees truthful acknowledgments and exposes any storage or serialization failures immediately.

---

## Decision 0.8: Multi-Turn Conversation Consistency
- **Context**: The generic webhook opened a new conversation for every payload lacking `conversation_id`, and Telegram external ID resolution could fail across database engines.
- **Decision**: Added open conversation lookup by `(tenant_id, channel_id, customer_id)` before starting a new conversation, and hardened external ID resolution across both PostgreSQL JSON and SQLite.
- **Rationale**: Ensures consecutive customer messages are correctly threaded in a single continuous conversation.

---

## Decision 0.9: Extended Reply Guardrails (Entities & Capability Claims)
- **Context**: Guardrail item 0.6 initially covered only prices and discounts. In runtime tests, the LLM invented product descriptions (e.g., claiming Nazim is a task/inventory tool), unrecorded features (tax/ZATCA integration), trials ("14-day free trial"), 24/7 support, webinars, and unverified branch locations.
- **Decision**: Extend `_evaluate_reply_guardrails` to evaluate:
  1. **Product/Service Entities**: Scan for product indicators (`برنامج`, `نظام`, `تطبيق`, `أداة`, `منصة`, `منتج`, `خدمة`) followed by candidate names. Exclude common stop-words (`الخاص`, `المعتمد`, `الرسمي`, etc.). If the candidate is not found in the verified corpus (`BusinessBrain` + `Knowledge`), block the reply.
  2. **Product Purpose Claims**: Scan for definition patterns (`هو نظام لـ...` / `عبارة عن أداة لـ...`). Check that content tokens (e.g. `مهام`, `مخزون`) exist in verified facts.
  3. **High-Risk Feature & Capability Claims**:
     - *Tax / ZATCA / VAT*: Block assertions like `الربط مع الضرائب` or `الفوترة الإلكترونية` unless explicitly recorded.
     - *Free Trials*: Block `نسخة تجريبية مجانية` or `14 يومًا تجربة` unless documented in policies.
     - *Support Hours*: Block `24/7` or `على مدار الساعة` unless documented.
     - *Webinars / Workshops*: Block claims of training courses or webinars unless documented.
     - *Branch Locations*: Extract city names from `فرعنا في <city>` and check against verified locations or operations.
  4. **Negation Awareness**: Preceding negation phrases (`لا نوفر`, `لا يدعم`, `غير متاح`, `ليس لدينا`) are recognized as honest boundary statements and are allowed rather than blocked.
- **Matching Mechanism & Known Limits**:
  - *Mechanism*: Token and regex pattern matching evaluated against an aggregated verified corpus (`json.dumps(business)` + knowledge snippets).
  - *False Positives*: Can occur if the model uses novel phrasing that resembles a capability claim without a direct negation phrase. Minimized via local context window look-behind for negation particles.
  - *False Negatives*: Highly paraphrased or indirect claims without trigger keywords (e.g., "نحن متواجدون دائمًا لراحتكم" instead of "24/7") might bypass regex pattern matching. Full structured facts evaluation in Phase 2 will further address this.

---

## Decision 0.10: Guardrail Enforcement in Owner Management Path
- **Context**: When the owner asked general business questions (`ما هو برنامج ناظم وما هي مميزاته؟`), the owner path called `generate_text` without post-generation validation, allowing invented facts to be shown to the owner.
- **Decision**: Apply `_evaluate_reply_guardrails` to `_process_owner_message` in general guidance / chat branch J. If the LLM generates an unverified claim, block it, log an `owner_reply_blocked_by_guardrail` audit event, and substitute:
  `"المعلومات المتعلقة بهذا الاستفسار غير مسجلة حالياً في قاعدة بيانات المنشأة. يمكنك تزويدي بتفاصيلها لحفظها وتوثيقها فوراً."`
- **Rationale**: The assistant must be truthful to the owner; hallucinating company features back to the owner erodes platform trust and breaks administrative workflows.

---

## Decision 2.1: Flexible Facts Store Architecture & Structured Extraction
- **Context**: The legacy `business_brain` table relied on a fixed schema (`identity`, `products`, `services`, `pricing`, `policies`) and fragile regex parsers. This proved incapable of representing diverse business domains (such as honey shops, electronics distributors, network providers) without modifying database columns and regex patterns.
- **Decision**: Implement a decoupled, schema-agnostic `facts` ledger and structured extraction engine:
  1. **Schema Design**:
     - `id`: UUID primary key.
     - `tenant_id`: Mandatory tenant foreign key with isolation enforcement on every operation.
     - `topic`: Free-form dot-separated slug (e.g., `product.nazim.pricing`, `delivery.zones.sanaa`, `company.goals`).
     - `subject`: Human-readable label for the entity or assertion.
     - `value`: JSONB payload capable of storing any data model (scalars, lists, dictionaries, specifications).
     - `source`: Enum/string (`owner_stated`, `owner_confirmed`, `inferred`).
     - `confidence`: Float metric between 0.0 and 1.0.
     - `visibility`: `public` (accessible to customer-facing prompts) or `private` (restricted to owner and internal workflows).
     - `status`: `confirmed`, `pending_confirmation`, `stale`, or `conflict`.
     - `expires_at`: Optional timestamp for time-sensitive data (promotions, seasonal hours, pricing).
     - `superseded_by`: Self-referential UUID foreign key to track fact revisions without destructive overwrites.
     - Composite indexes on `(tenant_id, topic)`, `(tenant_id, status)`, and `(tenant_id, subject)`.
  2. **Extraction Engine**:
     - Primary path uses AI provider structured JSON output conforming to Pydantic schema `FactExtractionResponse`.
     - Handles multiple facts in a single message and parses Yemeni/regional Arabic business terminology (`نبيع`, `نخدم`, `حقنا`, `المحل`).
     - Documented regex fallback (`_extract_facts_regex_fallback`) guarantees deterministic parsing if the AI provider fails or is absent.
  3. **Confirmation vs. Direct Auto-Confirm**:
     - Ambiguous, inferred, or low-confidence facts are saved with `status="pending_confirmation"` accompanied by an Arabic summary asking the owner to confirm or correct.
     - Clear, direct, unambiguous owner declarations (e.g. "اسم شركتنا المنذر تكنولوجي", "نقدم برنامج ناظم المحاسبي") are marked `confirmed` with `source="owner_stated"`, accompanied by an explicit read-back acknowledgment of the saved values.
     - Corrections mark the superseded fact with `superseded_by` and insert the updated fact.
  4. **Contradiction & Conflict Resolution**:
     - When a new fact is stated that conflicts with an active confirmed fact on the same topic/subject, it is flagged as `status="conflict"`.
     - Both conflicting records are preserved until the owner explicitly resolves the conflict, notifying the owner in Arabic of the discrepancy.
  5. **Data Expiration**:
     - Facts regarding pricing and temporary campaigns receive an expiration date (`expires_at`).
     - `FactService.list_stale_facts` queries expired or aging facts per tenant to enable proactive re-verification.
  6. **Customer vs. Owner Retrieval Isolation**:
     - `get_relevant_facts`:
       - Customer inquiries strictly query `status == 'confirmed'`, `visibility == 'public'`, and `(expires_at IS NULL OR expires_at > now())`.
       - Owner inquiries retrieve both public and private verified facts.
  7. **Migration Safeguards**:
     - Migration plan documented in `docs/MIGRATION_PLAN_PHASE2.md`.
     - Pre-migration JSON export of all `business_brains` and `knowledge` rows.
     - Alembic revision `e6f7a8b9c0d1_add_facts_table.py` creates the `facts` table with full rollback capability (`op.drop_table('facts')`).
     - Non-destructive data migration copies existing brain and knowledge records into the `facts` table while preserving existing tables during the transition.
     - Execution on live database is gated by explicit user review and approval.




---

## Decision 2.2: Primary Structured Fact Routing, Additive Merging & Truthful Query Answering
- **Context**: In runtime testing with realistic multi-clause declarations and consecutive inquiries, legacy regex parsers and intent branches intervened prematurely. Company names could silently overwrite existing records without conflict detection, queries like "ما هي منتجاتنا؟" read empty legacy columns, additive sentences like "لا، نخدم أيضًا محافظة عمران" failed or collided with existing facts, and the old regex confirmation message was still emitted.
- **Decision**:
  1. **Structured Fact Extraction as Primary Handler**:
     - In `ConversationalAgentEngine._process_owner_message`, structured extraction is executed ahead of legacy catalog/knowledge fallback routes.
     - The old regex confirmation acknowledgment message has been made completely unreachable.
     - All exceptions in this path are logged with `tenant_id`, `message_id`, and stack traces; exceptions are never swallowed silently.
  2. **Additive Coverage Merging**:
     - When owner declarations include additive terminology (`أيضًا`, `ايضا`, `كذلك`, `بالإضافة`, `إضافة`), or provide new coverage cities without negating previous ones, `FactService.save_extracted_facts` merges new cities into the existing confirmed record (`list(dict.fromkeys(existing + new))`), marks the previous fact as `superseded_by`, and confirms the updated list without generating a conflict.
     - Contradictory identity declarations (e.g. changing company name) continue to be strictly flagged as `status="conflict"` requiring owner confirmation.
  3. **Truthful Direct Query Handlers**:
     - Product catalog inquiries ("ما هي منتجاتنا؟") query confirmed facts directly from the `facts` table, formatted into an ordered Arabic listing.
     - Delivery coverage inquiries ("ما هي المدن التي نخدمها؟") return the deduplicated list of confirmed coverage cities.
     - Product price inquiries ("كم سعر ناظم؟") check the confirmed product record; if unrecorded, the agent truthfully states that the price is not recorded and offers to record it, strictly without hallucinating features, guessing numbers, or asking about unrelated categories (such as heat regulators or lighting).
  4. **Alembic Migration Reconciled**:
     - Restored `d5e6f7a8b9c0` (approvals token/expires_at) to the migration chain between `c4d5e6f7a8b9` and `e6f7a8b9c0d1`.
     - Preserves single Alembic head and 100% schema alignment across live DB and fresh databases.
     - Eliminated out-of-band table creation in tests (`checkfirst=True` and strict `ai_employee_test` validation).


---

## Decision 2.3: Live DB Reconciliation, Human-Readable Read-Back, Conflict Resolution, Operation Semantics & Dialect Robustness
- **Context**: In Phase 2 review, specific hardening requirements and live database safety reconciliations were specified:
  1. Live DB reconciliation via copy lifecycle verification, fresh pg_dump, drop empty unmanaged `facts`, and real migration to `e6f7a8b9c0d1 (head)`.
  2. Owner read-back must be formatted in natural human-readable Arabic, completely eliminating raw JSON/dict formatting (`{"name": ...}`).
  3. Conflict resolution: owner responses after a conflict message must resolve the conflict (chosen fact confirmed, unchosen superseded, history preserved).
  4. Dialect-robust queries: Yemeni Arabic queries for products, cities, prices, and product comparisons must answer faithfully from stored facts only, without phrase brittleness.
  5. Operation schema: replace keyword additive detection with an `operation` field (`add` / `replace` / `remove`), prompting confirmation when replacement removes cities.
  6. Customer path isolation: customer queries must strictly use only confirmed public facts, never exposing conflict, private, or pending facts.
- **Decision**:
  1. **Live DB Upgrade Verified**:
     - Tested on scratch copy lifecycle (upgrade -> downgrade -> upgrade).
     - Created verified backup snapshot `backups/backup_ai_employee_pre_phase2.dump` (759.55 KB) and verified clean restore.
     - Upgraded live DB (`ai_employee`) to `e6f7a8b9c0d1 (head)`: applied approvals columns (`token`, `expires_at`), managed `facts` table, and confirmed zero row count alterations on all existing tables.
  2. **Format Fact Arabic**:
     - Implemented `FactService.format_fact_readable_arabic`: converts dicts, lists, and scalars into natural Arabic strings without braces, brackets, quotes, or JSON syntax.
     - Owner read-back presents grouped items: company identity, products catalog, and coverage cities in clear, professional Arabic.
  3. **Conversational Conflict Resolution**:
     - On conflict detection, stores `pending_conflict` in conversation metadata.
     - In subsequent turn, detects owner choice (Option 1 vs Option 2 or explicit name mention).
     - Invokes `FactService.resolve_conflict`: marks chosen fact as `confirmed` (`owner_confirmed`), rejected fact as `superseded` (`superseded_by = chosen.id`), and retains complete historical ledger.
  4. **Robust Dialect Answering & Strict Product Comparison**:
     - Supported Yemeni dialect variants for products ("وش المنتجات اللي عندكم؟"، "ايش تبيعوا؟"), cities ("وين تخدموا؟"), and prices ("بكم ناظم؟"، "كم يكلف سيرو؟").
     - Implemented dedicated comparison handler for "ايش الفرق بين ناظم وسيرو؟" querying confirmed product facts, echoing stored descriptions, and explicitly stating detailed technical comparisons are not recorded in the database.
  5. **Operation-Driven Extraction**:
     - Added `operation: Literal["add", "replace", "remove"] = "add"` to `ExtractedFactItem`.
     - Model prompt and regex fallback classify operation:
       - `add`: merges new cities into confirmed coverage.
       - `remove`: removes specified cities ("ما نخدم ذمار بعد اليوم") and confirms remaining cities.
       - `replace`: if replacement removes active cities ("نخدم صنعاء فقط" removes 5 cities), flags for owner confirmation before superseding existing coverage.
  6. **Customer Path Isolation**:
     - Verified end-to-end that customer query prompt assembly and reply generation use only `status == 'confirmed'` and `visibility == 'public'` facts; conflict, private, and pending facts are strictly excluded.
