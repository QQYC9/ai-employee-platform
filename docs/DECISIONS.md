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

