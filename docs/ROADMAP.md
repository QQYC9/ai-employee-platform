# AI-Employee-Platform Project Roadmap

This document outlines the phased plan to evolve the Digital Employee platform from rule-based and regex conversational prototypes into a hardened, multi-tenant enterprise autonomous assistant.

---

## Open Issues
- **Runtime hallucination still observed after Phase 0.5**: with only the product name stored, the owner chat still returned an invented feature list, a 14-day free trial, and Saudi VAT/e-invoicing support. Unit tests pass (mocked model), so either the guardrail is not on this runtime path or it misses these phrasings. Re-test with the real Gemini after Phase 3; then decide between fixing the guardrail and building the groundedness verifier.
- **Unreviewed legacy code swept into commit 60ad507 (approval tokens, company profile intent, depreciation calculator)**: review before launch.

---

## Phase 0: Fix the Discovered Bugs
- **Status**: done
- **Objective**: Fix confirmed architectural bugs in message retrieval, context building, business learning, entity extraction, prompt generation, conversation scoping, and post-generation safety.
- **Verification**: Verified with 10 comprehensive tests in `tests/test_phase0_fixes_verification.py` (10/10 passed), plus 23/23 passing in customer conversation regression tests.

### Work Items
- **0.1 Fix `list_messages`**: Fetch the latest N messages (`order_by(created_at.desc()).limit(N)`), then reverse to chronological order (`.reverse()`).
  - *Acceptance Criteria*: A 30-message conversation must include the latest messages in the context sent to the model.
- **0.2 Fix `_process_owner_message`**: Pass Business Brain, knowledge snippets, the last 15 messages of the owner conversation, and strict anti-hallucination rules (answer only from verified facts, state clearly if information is not recorded).
  - *Acceptance Criteria*: With an empty brain, the owner asking "ايش هو ناظم؟" must receive an answer stating it is not recorded, with zero invented descriptions.
- **0.3 Fix `_construct_prompt`**: Inject branches, locations, operating/working hours, and all populated `business_brain` fields (including operations, policies, etc.), not just the default 5.
  - *Acceptance Criteria*: Configured branches, cities, and working hours appear in the prompt context.
- **0.4 Fix `_extract_business_knowledge`**: Strip filler phrases and titles (`الرسمي`, `المعتمد`, `لدينا`, `لمنشأتنا`, `الخاص`, etc.).
  - *Acceptance Criteria*: "الاسم التجاري الرسمي لمنشأتنا المنذر تكنولوجي" extracts "المنذر تكنولوجي". Also verifies "اسم شركتنا المنذر تكنولوجي" and "اسم المحل: النور للعسل".
- **0.5 Verify Products and Cities Persistence**: Verify that products ("الموظف الذكي", "برنامج ناظم المحاسبي", "برنامج سيرو لادارة الشبكات") and cities ("صنعاء", "الحديدة", "ذمار", "إب", "المحويت", "ريمة") sent by the owner are persisted in `business_brain.products` / `business_brain.operations` (or respective columns). Fix extraction if not persisted.
  - *Acceptance Criteria*: Database record shows exact persisted values after ingestion.
- **0.6 Post-Generation Guardrail in Customer Path**: If the generated customer reply contains a price, discount percentage, unverified product name, or feature claim not supported by Business Brain / Knowledge Base, block the reply, substitute a handoff message in Arabic ("سأحوّل استفسارك للموظف المختص وسيرد عليك قريبًا"), and log the blocked attempt.
  - *Acceptance Criteria*: Unit and integration tests verify mocked hallucinations are intercepted and blocked.
- **0.7 Multi-Turn Conversation Consistency**: Ensure 3 consecutive inbound messages from the same customer land in the exact same `conversation_id` across Telegram, WhatsApp, and webhook connectors.
  - *Acceptance Criteria*: Regression tests prove consecutive messages do not spawn multiple conversation records.
- **0.8 Confirmed Values in Confirmation Responses**: The "saved" acknowledgment message must display the exact value read back from the database after persistence, not the raw unverified user string.
  - *Acceptance Criteria*: Owner receives confirmation showing the actual DB-persisted entity.
- **0.9 Customer Prompt Capability Guardrails**: Explicitly state to the model that the digital employee cannot make phone calls, book calendar appointments, send links, generate graphic images, or offer free trials. Inquiries about these must offer team handoff.
  - *Acceptance Criteria*: System instruction contains explicit capability prohibitions.

---

## Phase 0.5: Guardrails Hardening & End-to-End Integration Flow
- **Status**: done
- **Objective**: Extend post-generation guardrails to cover unverified product mentions, purpose descriptions, and high-risk capability claims (tax/ZATCA integration, free trials, 24/7 support, webinars, branches), enforce the guardrail in the owner path, and verify the complete decoupled message flow.
- **Verification**: Verified with 4 comprehensive tests in `tests/test_phase0_5_hardening.py` (4/4 passed), plus 10/10 in `tests/test_phase0_fixes_verification.py`.

### Work Items
- **0.5.1 Product & Purpose Guardrails**:
  - Scan for unverified product/service entities and purpose descriptions (e.g., "برنامج ناظم هو نظام لإدارة المهام والمخزون").
  - Block with Arabic handoff if unsupported by BusinessBrain or Knowledge Base.
- **0.5.2 High-Risk Capability Claims**:
  - Intercept claims of Tax/ZATCA integration ("يدعم الربط مع الضرائب في السعودية"), free trials ("نسخة تجريبية مجانية لمدة 14 يومًا"), 24/7 support, webinars, and branch locations when unrecorded.
  - Support honest negative statements via negation look-behind.
  - Allow identical sentences when verified facts exist in the brain.
- **0.5.3 Owner Path Guardrail Enforcement**:
  - Apply `_evaluate_reply_guardrails` to the general chat branch of `_process_owner_message`.
  - Block hallucinated responses to owner queries and replace with Arabic missing-data prompt.
- **0.5.4 Real Message Flow Integration Test**:
  - Webhook payload -> Inbound persistence -> Outbox process_incoming_message -> OutboxWorker -> Engine reasoning & guardrails -> Channel dispatch send.
  - Inspect and assert stored `conversation_id`, inbound message ID, and persisted reply.

---

## Phase 1: Owner Inquiry Loop (Ask the Owner When Answer is Unknown)
- **Status**: todo
- **Objective**: Implement asynchronous inquiry escalation to the business owner when customer questions lack verified knowledge.
- **Acceptance Criteria**:
  - `owner_inquiries` table with `tenant_id`, `conversation_id`, `customer_question`, `status`, `owner_answer`, timestamps.
  - One-time customer waiting message ("لحظة أتأكد لك") without loops.
  - Dispatch inquiry to owner's channel with correlation token/id.
  - Correlate owner reply and deliver answer immediately to waiting customer.
  - Offer owner the choice to save the answer globally or per-customer.
  - Escalation task and customer notification upon timeout.
  - Deduplication across multiple customers asking the same question.
  - Multi-tenant isolation verified by test.

---

## Phase 2: Facts Store & Structured Extraction
- **Status**: done (Implementation & test suite verified; live DB migration gated by user approval of `docs/MIGRATION_PLAN_PHASE2.md`)
- **Objective**: Transition from conversational regex parsing to a flexible, multi-tenant `facts` store, schema-validated structured model extraction, confirmation/conflict workflows, and non-destructive migration.
- **Verification**: Verified with 7 comprehensive tests in `tests/test_phase2_facts_store.py` (7/7 passed), plus 21/21 passing in full Phase 0, Phase 0.5, and Phase 2 regression suites.

### Work Items
- **2.1 Flexible Facts Schema**:
  - Table `facts` with `id`, `tenant_id`, `topic` (dot-separated slug), `subject`, `value` (JSONB), `source` (`owner_stated`/`owner_confirmed`/`inferred`), `confidence`, `visibility` (`public`/`private`), `status` (`confirmed`/`pending_confirmation`/`stale`/`conflict`), `expires_at`, `created_at`, `updated_at`, `superseded_by`.
  - Composite indexes on `(tenant_id, topic)`, `(tenant_id, status)`, and `(tenant_id, subject)`.
- **2.2 Structured AI Fact Extraction & Dialect Support**:
  - Model extraction via Pydantic schema `FactExtractionResponse` supporting multiple facts per sentence and Yemeni Arabic dialects ("نبيع", "نخدم", "حقنا", "المحل").
  - Documented deterministic regex fallback (`_extract_facts_regex_fallback`).
- **2.3 Confirmation & Auto-Confirm Workflow**:
  - Ambiguous/inferred facts stored as `pending_confirmation` with Arabic review summary.
  - Direct unambiguous owner declarations auto-confirmed with read-back summary.
  - Correction flow updates fact and marks superseded version.
- **2.4 Contradiction & Conflict Resolution**:
  - Conflicting assertions marked `status="conflict"` and preserved until owner resolution.
- **2.5 Expiry Tracking**:
  - Expiration dates for prices/promotions and `list_stale_facts` function.
- **2.6 Public vs Private Retrieval**:
  - `get_relevant_facts` strictly limits customer context to public confirmed non-expired facts; owner context receives both public and private facts.
- **2.7 Non-Destructive Migration Plan**:
  - Pre-migration backup routine, Alembic migration `e6f7a8b9c0d1_add_facts_table.py`, and data copier `migrate_business_brains_and_knowledge_to_facts`. Documented in `docs/MIGRATION_PLAN_PHASE2.md` awaiting user approval before applying to live DB.
- **2.8 Runtime Integration & Real Entry-Point Wire-up**:
  - Routed all owner business declarations directly through structured fact extraction as primary engine, making old regex confirmation messages completely unreachable.
  - Added additive delivery zone merging (e.g. "لا، نخدم أيضًا محافظة عمران" merges into existing coverage without conflict, superseding previous record while keeping existing cities).
  - Wired direct query handlers for product catalogs ("ما هي منتجاتنا؟"), delivery coverage ("ما هي المدن التي نخدمها؟"), and specific product prices ("كم سعر ناظم؟") answering strictly from the Facts Store without hallucinating features or asking about unrelated categories.
  - Reconciled Alembic migration chain (`c4d5e6f7a8b9 -> d5e6f7a8b9c0 -> e6f7a8b9c0d1`), ensuring fresh and live DB schema parity.
  - Eliminated outside-Alembic table creation leaks (`setup_facts_table` restricted strictly to `ai_employee_test`).
  - Verified across all 6 messages through real entry point on scratch DB. Full regression suite passing (23/23).

- **2.9 Live DB Reconciliation & Part B Hardening Pass**:
  - Reconciled live PostgreSQL DB (`ai_employee`) to `e6f7a8b9c0d1 (head)` with verified pg_dump snapshot (`backups/backup_ai_employee_pre_phase2.dump`, 759.55 KB) and copy lifecycle proof.
  - Enforced human-readable Arabic read-back (`FactService.format_fact_readable_arabic`), completely removing raw JSON/dict formatting.
  - Implemented interactive conflict resolution in owner chat: owner choice ('المنذر تكنولوجي', 'الاسم الصحيح هو الثاني', 'اعتمد المنذر للتقنية') confirms chosen fact, marks rejected fact as superseded, and preserves complete history.
  - Added robust dialect intent detection for Yemeni Arabic queries ('وش المنتجات اللي عندكم؟'، 'ايش تبيعوا؟'، 'وين تخدموا؟'، 'بكم ناظم؟'، 'كم يكلف سيرو؟') and product comparisons ('ايش الفرق بين ناظم وسيرو؟') strictly answering from stored facts.
  - Migrated coverage operations to an `operation` schema (`add` / `replace` / `remove`), prompting owner confirmation when a replace operation removes active cities.
  - Verified customer path isolation: customer query prompts receive only confirmed public facts; conflict, private, or pending facts are strictly excluded.
  - Full test suite passing (28/28 passed, 1 skipped).

- **2.10 Customer Path Facts Answering & Guardrail False-Positive Fix**:
  - **Status**: done
  - Resolved false-positive blocking in Guardrail Rule 3 where Arabic verbs, descriptive adjectives, prepositions, and markdown characters (e.g. `يُسهّل`, `متكامل`, `|`, `بشكل`) following "برنامج/منتج/خدمة" were falsely classified as unverified product entity names.
  - Hardened Rule 3 with comprehensive Arabic stopwords, grammatical filters, and tashkeel normalization, preserving strict blocking for actual hallucinated product names (e.g. "برنامج الكافي").
  - Refined Rule 8 (branch check) so location claims for physical branches ("فرع في صنعاء") are verified strictly against dedicated branch/headquarters facts rather than general service coverage.
  - Updated handoff reply to: `"هذا الاستفسار يحتاج تأكيدًا من الفريق، وسنعود إليك."` so it makes no false promise while Phase 1 is not yet implemented.
  - Logged every customer handoff event with `tenant_id`, `conversation_id`, and `question` into the queryable `audit_events` table for tenant owner visibility.
  - Verified with 9 comprehensive tests in `tests/test_customer_path_confirmed_facts.py` (9/9 passed) across products questions ("ما هي منتجاتكم؟", "ايش تبيعوا؟"), coverage question ("وين تخدموا؟"), branch questions, and unverified price/trial/VAT handoffs. 37/37 regression passing.

---

## Phase 3: Adaptive Owner Onboarding Interview
- **Status**: todo
- **Objective**: Interactive onboarding dialogue when an owner links via connection code.
- **Acceptance Criteria**:
  - 4 foundational classification questions.
  - Dynamic topic map based on business field.
  - Coverage score gate preventing customer go-live until critical topics are answered.

---

## Phase 4: Simulated Customer Evaluation
- **Status**: todo
- **Objective**: Pre-deployment validation suite simulating 50 realistic customer queries against stored facts.
- **Acceptance Criteria**:
  - Autonomous test runner generating field-specific inquiries.
  - Gaps automatically filed as owner questions.
  - Zero hallucination rate on unrecorded knowledge.
