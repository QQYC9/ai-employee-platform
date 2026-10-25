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
- **Status**: done (Verified with 3 real-path tests in `tests/test_phase1_task3_owner_inquiries.py`)
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
- **1.1 Owner Inquiry Loop & Dynamic Knowledge Resolution**: Implemented migration `c1d2e3f4a5b6_add_owner_inquiries_table.py`, `OwnerInquiryService`, question normalization deduplication, holding sentence dispatch, owner answer matching (reply-to, inquiry #, single pending), FactService persistence, scope prompting ('للجميع' / 'لهذا العميل فقط'), 2h/24h reminders/timeouts, and commands ('الاستفسارات', 'تجاهل 12').

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

- **2.11 Customer Path Addendum (Precedence, Anti-Embellishment, Verbatim Extraction & Guardrails)**:
  - **Status**: done
  - Enforced confirmed facts precedence over `business_brain`: in both customer and owner prompts, confirmed identity and product facts override and neutralize stale or conflicting `business_brain` identity ("المنذر تكنولوجي" wins over "المنذر للتقنية") and omit conflicting `business_brain.products`. Confirmed identity facts are unconditionally included in context retrieval.
  - Anti-embellishment & safe catalog replacement: instructed model in Policy 11 to describe each product ONLY using its exact stored fact text verbatim. Implemented deterministic post-check Rule 12 blocking unrecorded capability/benefit claims (`إدارة المهام`, `مراقبة الأداء`, `الفواتير والتقارير`, `زيادة الإنتاجية`, `إدارة الأجهزة`) when not present in verified facts, replacing embellished product replies with a safe catalog reply built strictly from confirmed facts.
  - Verbatim product extraction: fixed fact extraction so product names remain verbatim (`"الموظف الذكي"` does not become `"برنامج للموظف الذكي"`), and stopped storing invented descriptions when none are provided by the business owner.
  - Prohibited false forwarding promises: deterministic post-check Rule 9 intercepts unapproved forwarding promises (`"سأنقل طلبك"`, `"سيرد عليك"`, `"سنعود إليك بأسرع وقت"`) and replaces them with approved handoff text: `"هذا الاستفسار يحتاج تأكيدًا من الفريق، وسنعود إليك."`.
  - Blocked unrecorded topic offers: Guardrail Rule 10 intercepts offers suggesting unrecorded topics or features (`"مميزات البرنامج"`, `"المتطلبات التقنية"`, `"الخصائص التقنية"`, `"طرق الترخيص"`, `"طريقة الاستخدام"`, `"الدعم الفني"`).
  - Enforced strict Arabic language: Guardrail Rule 11 blocks stray Latin words (e.g. `"Customer Replay"`, `"Support"`) unless verified as Latin product/brand names in confirmed facts (e.g. `"Ciro Networks"`). Sanitized prompt injection to omit Latin placeholder names.
  - Verified with 16 comprehensive tests in `tests/test_customer_path_confirmed_facts.py` (16/16 passed) and full regression suite (44 passing tests).

- **2.12 Cleanups: Simple Catalog Listing & Identity Knowledge Suppression**:
  - **Status**: done
  - Catalog listing cleanup: when a product has no stored description, the catalog reply shows only its name (eliminating repeated name as description). Enforced simple Arabic list formatting, prohibiting Markdown tables.
  - Knowledge snippet suppression: suppressed injection of knowledge snippets starting with "اسم المنشأة" into customer and owner prompts when a confirmed `company.identity` fact exists. Preserved all database rows intact.
  - Verified with 4 comprehensive tests in `tests/test_part0_cleanups.py` (4/4 passed).

---

## Phase 3: Adaptive Owner Onboarding Interview
- **Status**: done
- **Objective**: Interactive onboarding dialogue when an owner links via connection code, where the digital employee decides autonomously what it needs to know based on business classification, plans dynamic topics, executes structured extraction, tracks coverage, and gates customer go-live until critical knowledge is recorded.
- **Verification**: Verified with 10 comprehensive tests in `tests/test_phase3_adaptive_interview.py` (9 passed, 1 live-model skipped when no API key set) through the REAL router -> engine path (`InboundMessage` -> `ChannelService` -> `ConversationalAgentEngine`). Full regression suite passing (43 passed, 2 skipped).

### Work Items
- **3.1 Schema & Non-Destructive Migration**:
  - Alembic migration `f7a8b9c0d1e2_add_adaptive_interview_tables.py` creating `interview_topics` and `interview_states` with `tenant_id` foreign keys, cascades, unique constraints, and indexes.
  - Added `interview_required` (Boolean, default `False`) and `interview_threshold` (Float, default `80.0`) to `tenants`.
  - Executed pg_dump pre-migration backup (`backups/backup_ai_employee_pre_phase3.dump`, 816 KB), SQL dry-run, and full lifecycle (`upgrade -> downgrade -> upgrade`) on copy database before live DB migration.
- **3.2 Flexible Entry Points**:
  - Entry point A: Instant automatic interview greeting when an unlinked owner connects via connection code (`channel.config["connection_code"]`).
  - Entry point B: Explicit Arabic triggers ("ابدأ التعارف", "كمّل التعارف").
  - Entry point C: Progress overview query ("وش باقي؟").
- **3.3 Stage 1 Conversational Classification**:
  - 4 free-text conversational questions: Owner Name, Role, Entity Type, Country & Field of Activity.
  - Multi-label business profile tagging (e.g. `{shop, honey, retail, delivery, Yemen}` or `{software, company, b2b, development, it, Yemen}`).
  - Persisted as `profile.*` facts via Phase 2 `FactService` with clean read-back summary.
- **3.4 Stage 2 Dynamic Topic Planning**:
  - Topic planner with AI generation + deterministic domain synthesis yielding distinct topic sets for honey shops, software companies, restaurants, and retail without code changes per business.
  - Universal topics (`identity`, `products_services_prices`, `ordering_payment`, `delivery_coverage`, `branches_hours`, `returns_warranty`, `authority_limits`, `tone_voice`, `unknown_questions_handling`).
  - Field-specific topics (Honey: `honey_types`, `packaging_sizes`, `honey_storage`, `authenticity_guarantee`; Software: `target_clients`, `software_licenses`, `support_sla_policy`, `partnerships_certifications`).
- **3.5 Stage 3 Conditional Follow-ups & Negative Closure**:
  - Branching chains (e.g. Yemen delivery ladder: local governorate delivery -> inter-governorate shipping -> international shipping).
  - Negative answer detection ("لا") closes dependent topic branches cleanly without re-asking.
- **3.6 Deterministic Next-Question Selector**:
  - Evaluates satisfied dependencies, selects candidate with highest criticality (1-5, tie-broken by dependency depth).
  - Emits short Arabic questions with optional quick replies.
  - Multi-topic answer coverage in a single owner turn.
  - Skip and "لا ينطبق" handling.
  - Off-topic owner inquiries during interview answered naturally without swallowing or losing interview state.
- **3.7 Pause/Resume & Progress Reporting**:
  - State persisted per tenant in `interview_states`. Resumes seamlessly across sessions.
  - Progress summary ("وش باقي؟") returns covered count, critical coverage %, and open critical topics.
- **3.8 Go-Live Gate**:
  - For tenants with `interview_required=True` below threshold, customer inquiries receive a polite holding reply (`"نجهّز الخدمة حاليًا، سنتواصل معك قريبًا"`) and the owner is notified of missing critical topics.
  - Existing tenants remain unaffected (`interview_required=False`). New tenants provisioned after Phase 3 default to `True`.
- **3.9 Verbatim Product Extraction Regression Test**:
  - Product names remain verbatim inside interview extraction, never storing invented descriptions.
- **3.10 Tenant Isolation & Security**:
  - Every interview table and query scoped to `tenant_id`. Tenant isolation verified by test.

---

## Phase 3.1: Adaptive Interview Review Hardening & Verbatim Extraction
- **Status**: done
- **Objective**: Fix review-identified interview logic defects: content-driven coverage, verbatim extraction, domain adaptation, negative answer semantics, and clean greetings.
- **Verification**: Verified with 9 comprehensive tests in `tests/test_phase3_1_review_fixes.py` (9/9 passed) + 10 tests in `tests/test_phase3_adaptive_interview.py` (9 passed, 1 skipped) through the REAL router -> engine path (`InboundMessage` -> `ChannelService` -> `ConversationalAgentEngine`). Full regression suite passing.

### Work Items & Resolved Defects
- **3.1.1 Content-Driven Topic Coverage & Re-asking**:
  - After every owner reply, evaluated against open topics via structured model call (`ReplyCoverageEvaluation`) with deterministic semantic fallback.
  - Asked topic is NOT automatically answered. If reply addresses different topics, acknowledges what was understood, increments attempt counter, re-asks briefly once (`attempts < 2`), and parks topic after 2 attempts (`attempts >= 2`).
  - Tested: honey payment answered with honey types -> payment re-asked; software payment answered with target clients/licenses -> payment re-asked.
- **3.1.2 Never Re-Ask Covered Topics**:
  - Once a topic is covered (e.g. multi-topic reply covering target clients, software licenses, support SLA), its status is updated to `answered` and omitted from future selector picks.
- **3.1.3 Company Identity Verbatim Extraction**:
  - Replies like "شركة المنذر للحلول البرمجية الذكية" stored strictly under `company.identity` with verbatim name, NOT misclassified as `company.description` ("مجال النشاط").
- **3.1.4 Product Names Verbatim & Hardcoded String Removal**:
  - Eliminated all hardcoded brand/product names (`ناظم`, `سيرو`, `الموظف الذكي`) and rewriting fallbacks from production code in `fact_service.py` and `conversational_agent_engine.py`.
  - Verified verbatim extraction for "نظام الموظف الذكي السحابي" and "برنامج ناظم لإدارة الشركات" without appending "المحاسبي" or stripping "السحابي", plus verified extraction on unseen products ("منصة الأفق للمتاجر").
- **3.1.5 Domain-Adapted Universal Topics & Dynamic Quick Replies**:
  - Cloud software topics adapted dynamically from profile: physical `delivery_coverage` transformed to `service_coverage`, and payment quick replies tailored to digital methods (invoicing, bank transfer, annual contracts; NO cash or COD). Honey shops get physical delivery and COD options.
- **3.1.6 Negative Answer Semantics**:
  - Answering "لا" to an optional or yes/no topic marks it `not_applicable` or `skipped`, NEVER `answered`.
- **3.1.7 Profile Tags Presentation & Stated/Inferred Isolation**:
  - Display tags to owners in clean Arabic. Unstated tags (such as inferred delivery or B2B) are separated into `inferred` and never stored as stated profile facts or used in topic planning unless confirmed.
- **3.1.8 Single Non-Duplicated Greeting**:
  - Eliminated chained welcoming messages upon starting interview ("ابدأ التعارف" or after linking).
- **3.1.9 Connection Code Link Mechanism**:
  - Documented and verified `ChannelService.process_inbound_message` connection code matching (`/link <connection_code>`) linking sender to `channel.config["owner_identifiers"]` with `flag_modified` and triggering immediate Stage 1 onboarding interview.
- **3.1.10 Live Groq Model Simulations**:
  - Executed full live simulations for both Honey Shop and Software Company via Groq provider (`openai/gpt-oss-120b`). Handled Groq rate limit (429) gracefully with fallback; verified full transcripts and topic tables in `scratch/simulation_report.md`.

---

## Phase 3.2: Tenant Onboarding, Owner Personalization, Secure Link Code & Dashboard Access
- **Status**: done
- **Objective**: Harden tenant creation and owner linking workflows: single-use hashed link codes, rate limiting, audit trail, dynamic employee name personalization, secure dashboard onboarding without plaintext passwords, and unified LLM coverage evaluation with partial state tracking.
- **Verification**: Verified with 5 comprehensive tests in `tests/test_phase3_2_tenant_onboarding.py` (5/5 passed), 8 tests in `tests/test_link_code_security.py` (8/8 passed), 4 tests in `tests/test_phase3_1_addendum_x2_x4.py` (4/4 passed), 9 tests in `tests/test_phase3_1_review_fixes.py` (9/9 passed), and 9 tests in `tests/test_phase3_adaptive_interview.py` (9 passed, 1 skipped). Total 35 passing tests through the REAL router -> engine path. Frontend builds (`apps/admin-dashboard` and `apps/tenant-dashboard`) verified with 0 errors.

### Work Items & Resolved Problems
- **3.2.1 Problem A: Tenant Creation UI & API Hardening**:
  - Removed misleading auto-fill in admin dashboard (`autoComplete="off"`, `autoComplete="new-password"`) and removed hardcoded default password (`TemporaryPassword123!`).
  - Generates a strong random password (`secrets.token_urlsafe(16)`) if left empty.
  - Enforced email uniqueness check in `TenantProvisioningService`, returning clear validation errors (`Email ... is already registered`).
  - Automatically provisions default channel and returns a fresh single-use link code with copyable command modal in UI.
- **3.2.2 Problem B: Employee Name Dynamic Personalization**:
  - Persisted in `tenants.employee_name` and exposed via tenant update APIs (`TenantService.update_current_tenant` / `PATCH /api/v1/tenants/me`).
  - Welcome greeting upon linking: `"أنا سارة، موظفتك الرقمية الذكية."`.
  - Customer prompt: `"You are سارة, the autonomous Digital Employee..."`.
  - Owner prompt: `"أنت سارة والمساعد الإداري لمالك منشأة..."`.
  - Interview greeting: `"مرحباً بك يا صاحب المنشأة! أنا سارة، موظفتك الرقمية الذكية..."`.
  - Verified instant propagation when `employee_name` is updated (e.g. from "سارة" to "نورة").
- **3.2.3 Problem C & X1: Cryptographic Link Code Security & Regeneration**:
  - Migration `b3c4d5e6f7a8_add_link_codes_and_employee_name.py` creating `tenant_link_codes` table with `tenant_id` foreign key, `code_hash` (SHA-256), `channel_id`, `attempts_count`, `max_attempts` (5), `expires_at` (24h default), `is_used`, and `is_revoked`.
  - Scrubbed legacy plaintext `connection_code` from `channels.config`.
  - Rate limiting: 5 consecutive invalid guesses lock the link code, emitting `link_code_rate_limited` audit event.
  - APIs: `GET /api/v1/channels/{channel_id}/link-code` (status) and `POST /api/v1/channels/{channel_id}/link-code` (regeneration invalidating previous code).
  - Linking via chat (`/link LINK-XXXX-XXXX`) elevates sender to `owner_identifiers`, records `used_at`, marks code used, and emits `link_code_used` audit event.
  - Neutral Arabic error reply (`"تعذر إتمام عملية الربط. رمز الربط غير صحيح أو منتهي الصلاحية."`) emitted for wrong, expired, or locked codes without leaking tenant status.
- **3.2.4 Problem D: Secure Dashboard Access Without Plaintext Passwords**:
  - Employee bot sends dashboard URL, owner login email, and a single-use tokenized link (`/set-password?token=...`).
  - Plaintext passwords strictly prohibited from chat, database logs, and audit entries.
  - Password setup endpoint `POST /api/v1/auth/reset-password-with-token` verifies token type `password_reset` and validates single-use fingerprint `pwh` (SHA-256 signature of current password hash).
  - Updating the password automatically invalidates the token, preventing replay attacks.
- **3.2.5 Addendum X2-X4: Data Integrity, Partial Coverage & Unified LLM Call**:
  - Implemented `status="partial"` with `coverage=0.5` in `TopicCoverageItem`. Keeps topic open and prompts for missing details.
  - Unified coverage evaluation and fact extraction into a single model call (`ReplyCoverageEvaluation` + `FactExtractionResponse`).
  - Added exponential backoff retry loop (1s -> 2s -> 4s) on `AIRateLimitError`, emitting neutral delay notice upon exhaustion.
  - Capped open topics in LLM payload to prevent context window explosion.
  - Updated simulations script to extract topic tables directly from live database state (`InterviewTopic.status`, `InterviewTopic.coverage`, and `Message.content` via `source_message_id`).
- **3.2.6 Review Fixes: Sender-Scoped Rate Limiting, Production Dashboard Guards & Simulation Ground Truth**:
  - Re-architected link-code rate limiting in `LinkCodeService` (`SenderLinkRateLimiter`): tracks failed attempts per sender/channel with exponential backoff (base 60s, doubling), keeping link codes valid and usable for legitimate owners.
  - Added `TENANT_DASHBOARD_URL` configuration guard preventing localhost leaks in production/staging environments, with short 30-minute password reset token expiration communicated in Arabic welcome message.
  - Migration safety verified for `b3c4d5e6f7a8`: backup file `backups/backup_ai_employee_pre_phase3_2.dump` (1.62 MB), static dry-run SQL verified, and fully reversible lifecycle tested on copy DB `ai_employee_test`.
  - Executed live model simulations on Groq (`openai/gpt-oss-120b`): measured tokens per turn and per interview (Honey Shop: 14,050 tokens; Software Company: 17,483 tokens), confirmed single unified LLM call for coverage + extraction, captured persisted DB topic tables with `decided_by` counts (model vs fallback), and confirmed verbatim product extraction without hardcoded overrides.
  - Full test regression executed across all 961 tests in repository: 939 passed, 20 failed (legacy assertions / test mock differences), 2 skipped (optional live API key smoke tests). All 41 Phase 3, 3.1, 3.2, security, and part0 cleanup tests passing cleanly (1 skipped).
- **3.2.7 Telegram Webhook Auto-Registration & Dual-Check Connection**: Auto-registers webhook on channel creation/update with per-channel secret token, dual-checks both credentials (getMe) and webhook status (getWebhookInfo), adds dashboard re-registration button, and bulk CLI re-registration script.
- **3.2.8 Owner Welcome Message Hardening & Tenant Dashboard Tunnel**: Public tenant dashboard exposed with set-password page, plain-text welcome formatting without literal asterisks, fallback to 'موظفك الرقمي' when employee name is empty, and mandatory employee name validation on tenant creation.
- **3.2.9 Adaptive Interview Resilience & Coverage Gating**: Fallback evaluator capped at partial (never covered/answered), business_identity gated by extracted company.identity fact, tone_voice mapped cleanly without branches_hours collision, source_message_id persisted only on covered topics, and model failure/429 emitting Arabic delay notices without fallback guessing.

---

## Phase 4: Simulated Customer Evaluation
- **Status**: todo
- **Objective**: Pre-deployment validation suite simulating 50 realistic customer queries against stored facts.
- **Acceptance Criteria**:
  - Autonomous test runner generating field-specific inquiries.
  - Gaps automatically filed as owner questions.
  - Zero hallucination rate on unrecorded knowledge.
