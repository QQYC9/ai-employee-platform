# Evidence Log: Product Vision, Cognitive Memory, Proactivity & Governance

**Document ID:** `PRODUCT_VISION_FINDINGS_EVIDENCE_LOG`  
**Audit Standard:** Second-Order Adversarial Audit  
**Target Findings:** F-13 (Chatbot Collapse & Omission of Episodic Memory), F-09 (WhatsApp Delivery Window & Quarantine), F-10 (Telegram Alert Storm)

---

## 1. Deep-Dive Audit: Finding F-13 (The Chatbot Collapse & Episodic Memory Omission)

### 1.1 Previous Claim
The previous audit asserted that:
1. The target architecture models execution exclusively on inbound customer chat messages (`Client -> Webhook -> Worker -> Pregel Turn -> Outbox -> Client`), lacking any proactive scheduler (`AgentJobScheduler`).
2. The 5-tier memory architecture completely omits **Episodic Conversation Memory** (customer session dialogue transcripts) by equating Tier 2 with active execution graph checkpoints (`execution_checkpoints`).

### 1.2 Repository Evidence
- **File:** `docs/architecture/MASTER_ARCHITECTURE_BLUEPRINT.md` §2.1 & §2.2:
  - Sequence diagrams and flowcharts only begin at `Internet -> Caddy -> FastAPI Gateway -> Inbound Webhook`.
  - There is zero mention of cron scheduling, shift schedules, or proactive autonomous triggers for agents.
- **File:** `docs/architecture/KNOWLEDGE_AND_MEMORY_ARCHITECTURE.md` lines 18–42:
  - Tier 1: Working Context Buffer (active turn).
  - Tier 2: Task & Operation Memory (`execution_checkpoints`).
  - Tier 3: Persistent Fact Memory (`fact_entities`).
  - Tier 4: Semantic Knowledge Memory (pgvector document RAG).
  - Tier 5: Procedural Skill Memory (`SKILL.md`).
- **The Cognitive Gap:**
  `execution_checkpoints` records transient Pregel supersteps for an in-flight turn. Once a turn completes, it becomes an inactive transaction log. The historical conversation messages in `conversations` and `messages` are never indexed or queried by the agent's 5-tier memory retriever!
- **Verdict:** `CONFIRMED` as a major architectural omission (P0).

---

## 2. Deep-Dive Audit: Finding F-09 (WhatsApp Quarantine & 24-Hour Window Inversion)

### 2.1 Repository Evidence
- `docs/architecture/ARCHITECTURAL_CONFLICTS_AND_OPEN_QUESTIONS.md:80`:
  > *"If dispatch times out, place event in a 60-second Quarantine Window. If webhook arrives matching the token, mark delivered; if no webhook arrives after 60s, re-dispatch."*
- `docs/architecture/MASTER_ARCHITECTURE_BLUEPRINT.md:396`:
  > *"The task enters a `WAITING_DELIVERY_CONFIRMATION` quarantine window (configurable, e.g. 15 minutes) awaiting an incoming status webhook... automatic blind retry is STRICTLY FORBIDDEN."*
- `docs/architecture/RESEARCH_EVIDENCE_GAPS.md:86` (Gap 6):
  > *"How does the conversation state graph handle inbound customer turns that arrive after Meta's 24-hour free-form customer service window has expired... If last_customer_message_timestamp > 24 hours, route the response through an approved Meta Utility/Marketing Template Message..."*

### 2.2 Protocol Reality (Meta WhatsApp Cloud API v19.0)
- In Meta Graph API, customer inbound messages **open and reset** the 24-hour service window. An inbound customer message *never* encounters error `#131047`.
- Error `#131047` occurs exclusively on outbound business-initiated messages (e.g. marketing campaigns or delayed approvals).
- Re-dispatching a timed-out message after 60 seconds guarantees duplicate messages whenever handset delivery webhooks are delayed.
- **Verdict:** `CONFIRMED` as a cross-document contradiction and conceptual error (P0).

---

## 3. Deep-Dive Audit: Finding F-10 (Telegram Alert Storm Arithmetic)

### 3.1 Repository Evidence
- `docs/architecture/ARCHITECTURAL_CONFLICTS_AND_OPEN_QUESTIONS.md:128`:
  > *"The Godfather incorporates an in-memory alert coalescing queue with a 5-second sliding window. Identical failure signatures are collapsed into a single summarized digest... before dispatching to Telegram."*

### 3.2 Protocol & Mathematical Verification
- 5-second window during a 20-minute outage:
  $$\frac{60\text{ s}}{5\text{ s}} = 12\text{ digests/minute} \times 20\text{ minutes} = \mathbf{240\text{ Telegram messages}}$$
- Telegram Bot API private chat rate limits: ~20 messages/minute before triggering anti-spam heuristic blocks (`HTTP 429 Too Many Requests`).
- **Verdict:** `CONFIRMED` as a mathematical and protocol reality (P0).

---
*End of Product Vision Findings Evidence Log.*
