# AI-Employee-Platform Project Roadmap

This document outlines the phased plan to evolve the Digital Employee platform from rule-based and regex conversational prototypes into a hardened, multi-tenant enterprise autonomous assistant.

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
- **Status**: todo
- **Objective**: Transition from conversational regex parsing to schema-validated structured model extraction and persistent `facts` ledger.
- **Acceptance Criteria**:
  - `facts` table with key, value, source, confidence, visibility, expiration, and status.
  - Schema-validated structured JSON fact extraction.
  - Conflict resolution and owner confirmation workflow.
  - Reversible migration plan preserving existing `business_brain` data.

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
