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


---

## Decision 2.4: Cleanups: Catalog List Presentation & Identity Knowledge Suppression
- **Context**:
  1. In catalog replies where a product lacks an explicit description, repetitions (e.g. "الموظف الذكي: الموظف الذكي") or Markdown table syntax (`|---|`) occurred, violating plain conversational Arabic norms.
  2. Stale knowledge snippets starting with "اسم المنشأة" could be injected into prompts alongside confirmed `company.identity` facts, introducing ambiguity or contradictions.
- **Decision**:
  1. **Safe Catalog List Presentation**:
     - When building product catalog replies, products lacking a stored description show only their name. Repeated names as descriptions are stripped.
     - Enforced simple Arabic list formatting (numbered/bulleted list) and added post-generation guardrail rule intercepting Markdown tables in catalog replies.
  2. **Knowledge Snippet Suppression for Company Identity**:
     - In both customer (`_construct_prompt`) and owner (`_process_owner_message`) prompt builders, suppressed injection of knowledge snippets whose title starts with "اسم المنشأة" if a confirmed `company.identity` fact exists.
     - All database rows in the `knowledge` table remain preserved and untouched.


---

## Decision 3.1: Adaptive Owner Onboarding Interview, Dynamic Topic Planning & Go-Live Gate
- **Context**:
  Business owners connecting to the platform across diverse industries (e.g. honey shops, software companies, restaurants, retail outlets) require an intelligent, conversational onboarding interview. The assistant must decide autonomously what it needs to know based on business classification, without code modifications per business type, without asking fixed questionnaires, without swallowing off-topic owner questions, and without allowing customers to receive unverified answers before critical knowledge is acquired.
- **Decision**:
  1. **Seamless Entry Points**:
     - *Connection Code Linking*: Hooked into the channel inbound path (`channel.config["connection_code"]`). When an unlinked owner provides the connection code, the system binds their sender ID to `owner_identifiers` and kicks off the interview immediately.
     - *Conversational Commands*: Owners can initiate or resume anytime using `"ابدأ التعارف"` or `"كمّل التعارف"`.
     - *Progress Reporting*: Querying `"وش باقي؟"` returns a structured progress report of completed topics, critical coverage percentage, and remaining critical topics.
  2. **Stage 1 Conversational Classification**:
     - Emits 4 conversational questions (Owner Name, Role, Entity Type, Country & Field).
     - Free-text answers are parsed into multi-label business tags (e.g. `{shop, honey, retail, delivery, Yemen}` or `{software, company, b2b, development, it, Yemen}`).
     - Persists profile tags as `profile.*` facts via Phase 2 `FactService` with human-readable read-back.
  3. **Stage 2 Dynamic Topic Planning**:
     - Synthesizes an interview topic plan (`InterviewPlanSchema`) mixing universal topics (`identity`, `products_services_prices`, `ordering_payment`, `delivery_coverage`, `branches_hours`, `returns_warranty`, `authority_limits`, `tone_voice`, `unknown_questions_handling`) with domain-specific topics (Honey: types, packaging sizes, storage, authenticity; Software: target clients, licenses, SLA policy, partnerships; Restaurant: menu, dine-in/takeaway).
     - Persists topics into `interview_topics` with dependencies (`depends_on`), criticality (1-5), and initial status `unknown`.
  4. **Stage 3 Conditional Follow-ups & Negative Closure**:
     - Country-specific follow-up chains (Yemen delivery ladder: intra-city delivery -> inter-governorate shipping -> international shipping).
     - Negative answer detection ("لا") immediately marks dependent topic branches as `not_applicable`, closing them cleanly without re-asking.
  5. **Deterministic Next-Question Selector**:
     - Non-model deterministic selector scans open topics whose dependencies are satisfied, picking the highest criticality candidate (tie-broken by dependency depth).
     - Generates concise Arabic questions with optional quick replies.
     - Multi-topic coverage in a single owner turn (an owner message covering products, prices, and cities marks all corresponding topics covered).
     - Understands `"لا أعلم"`, `"تخطى"`, and `"لا ينطبق"`.
     - Preserves interview state on off-topic questions: answers the owner's immediate inquiry and appends an offer to resume the interview.
  6. **Go-Live Gate & Customer Path Protection**:
     - Added `tenants.interview_required` (Boolean) and `tenants.interview_threshold` (Float, default 80.0%).
     - Existing tenants default to `interview_required=False` (unblocked). New tenants provisioned after Phase 3 default to `interview_required=True`.
     - For gated tenants below the critical coverage threshold, incoming customer messages receive a neutral Arabic reply (`"نجهّز الخدمة حاليًا، سنتواصل معك قريبًا"`), and the business owner is notified via their channel of the missing critical topics.
  7. **Tenant Isolation & Safe Database Migration**:
     - Pre-migration backup snapshot `backups/backup_ai_employee_pre_phase3.dump` (816 KB) created and verified.
     - Migration `f7a8b9c0d1e2` verified on copy database through full lifecycle (`upgrade -> downgrade -> upgrade`) before live DB upgrade.
     - Tables `interview_topics` and `interview_states` enforce `tenant_id` foreign keys with `ondelete="CASCADE"`. Tenant isolation confirmed by automated test.

---

## Decision 3.2: Phase 3.1 Content-Driven Coverage, Verbatim Extraction, and Domain Adaptation
- **Context**: The Phase 3 review accepted schema, migration safety, topic planning, gate, and pause/resume architecture, but identified defects in transcript analysis:
  1. Asked topic was marked answered even if reply addressed a different topic.
  2. Previously answered topics were re-asked.
  3. Company identity was misclassified as description (`مجال النشاط`).
  4. Product names had hardcoded brand fallbacks rewriting names to `"برنامج ناظم المحاسبي"`.
  5. Universal topics were not dynamically adapted to business model (e.g. software offered COD / branch cash).
  6. Answering "لا" marked topics as answered instead of not_applicable/skipped.
  7. Internal English tags were shown in readbacks.
  8. Duplicated greeting was emitted at interview start.
- **Decision**:
  1. **Content-Driven Coverage**: Evaluates each owner reply against all open topics using structured Pydantic model (`ReplyCoverageEvaluation`) with semantic fallback. A topic asked is never marked answered automatically. If off-target, acknowledged points are confirmed, attempt counter is incremented, the topic is re-asked briefly once (`attempts < 2`), and parked after 2 attempts (`attempts >= 2`).
  2. **Never Re-Ask**: Covered topics are flagged `answered` with `coverage=1.0` and excluded from future questions.
  3. **Verbatim Company Identity**: Exact names starting with entity keywords (`شركة`, `مؤسسة`, `متجر`) are strictly mapped to `company.identity`, preserving verbatim strings.
  4. **Generic Product Extraction**: Removed all hardcoded product names (`ناظم`, `سيرو`, `الموظف الذكي`) across production code (`fact_service.py`, `conversational_agent_engine.py`). Tested verbatim extraction with unseen products (`منصة الأفق للمتاجر`).
  5. **Domain Adaptation**: Universal topics adapt dynamically: software companies receive `service_coverage` (not physical delivery) and digital payment options without COD; physical shops receive delivery and COD options.
  6. **Answer Semantics**: Negative replies ("لا") mark topics as `not_applicable` or `skipped`, closing dependent branches.
  7. **Arabic Tags**: Profile tags displayed exclusively in clean Arabic (`ARABIC_TAG_LABELS`). Inferred tags are segregated from stated tags and omitted from topic planning unless confirmed.
  8. **Clean Greetings**: Eliminated greeting redundancy between link handler and Stage 1 Question 1.



---

## Decision 3.3: Phase 3.2 Tenant Onboarding, Cryptographic Link Codes, Employee Identity & Passwordless Activation
- **Context**: The platform owner identified critical usability and security deficiencies in tenant onboarding and owner linking:
  1. Creating a tenant in the admin UI pre-filled the same static email and password (`TemporaryPassword123!`), causing confusion and security risk.
  2. The configured digital employee name (e.g. "سارة") was never used in conversations or system prompts.
  3. No secure, single-use linking code mechanism existed; legacy setups relied on static plaintext config attributes without expiration, rate limiting, or audit events.
  4. Linking flows lacked secure dashboard access: plaintext passwords in chat are unacceptable in enterprise environments.
  5. Owner replies covering only part of a topic prematurely marked it answered without asking for missing details, and coverage evaluation required multiple round-trips.
- **Decision**:
  1. **Autofill Removal & Unique Generation**:
     - Stripped browser autocomplete defaults (`autoComplete="off"`, `autoComplete="new-password"`) and removed hardcoded fallback passwords from dashboard client and backend.
     - Optional password fields generate cryptographically secure passwords (`secrets.token_urlsafe(16)`).
     - Enforced email uniqueness validation in `TenantProvisioningService`, rejecting duplicates with clear domain errors.
  2. **Employee Name Personalization Across All Entry Points**:
     - Stored `tenants.employee_name` in DB and propagated across all touchpoints:
       - Chat welcome on linking: `"أنا {employee_name}، موظفتك الرقمية الذكية."`.
       - Customer system prompt: `"You are {employee_name}, the autonomous Digital Employee..."`.
       - Owner administrative prompt: `"أنت {employee_name} والمساعد الإداري..."`.
       - Adaptive interview greeting: `"أنا {employee_name}، موظفتك الرقمية الذكية..."`.
     - Supports live updates via `TenantService.update_current_tenant` and `PATCH /api/v1/tenants/me`.
  3. **Cryptographic Link Code Lifecycle**:
     - Dedicated table `tenant_link_codes` storing SHA-256 hashes of cryptographically random codes (`LINK-XXXX-XXXX`), scoped strictly to `tenant_id` and `channel_id`.
     - Enforced single-use consumption (`is_used=True`, `used_at`, `used_by_sender_id`), short configurable expiry (default 24h), and brute-force protection (max 5 failed attempts locks code).
     - Full audit trail recorded via `AuditService` (`link_code_generated`, `link_code_used`, `link_code_failed`, `link_code_revoked`, `link_code_rate_limited`).
     - Regeneration API revokes existing active codes immediately.
     - Neutral Arabic reply emitted for wrong, expired, or locked codes without leaking tenant status.
  4. **Passwordless Dashboard Activation via Fingerprinted Tokens**:
     - When an owner links via chat, the bot emits dashboard URL, owner login email, and a tokenized password setup link (`/set-password?token=...`). Plaintext passwords strictly prohibited from chat and logs.
     - Token is signed with type `password_reset` and fingerprinted with `hash(user.password_hash)`.
     - Resetting the password updates `user.password_hash`, which instantly invalidates the token, preventing reuse or replay attacks.
  5. **Data Integrity & Unified LLM Coverage Call**:
     - Introduced `status="partial"` with `coverage=0.5`. Topics with missing essential details remain open with follow-up prompts for missing specifics.
     - Unified coverage evaluation and fact extraction into a single model call (`ReplyCoverageEvaluation` + `FactExtractionResponse`), reducing model roundtrips.
     - Added exponential backoff retry loop (1s -> 2s -> 4s) on AI rate limit errors with polite delay notice on exhaustion.
     - Automated live simulation reporting extracting actual database rows dynamically (`InterviewTopic.status`, `InterviewTopic.coverage`, and `Message.content` via `source_message_id`).
