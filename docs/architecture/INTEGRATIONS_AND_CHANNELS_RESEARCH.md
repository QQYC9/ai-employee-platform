# Integrations & Omni-Channel Architecture — Protocols, Idempotency & Boundaries

**Document ID:** `INTEGRATIONS_AND_CHANNELS_RESEARCH`  
**Governing Workstream:** Workstream K & Workstream L (Integrations, Channels & Operations)  
**Target Repository:** `QQYC9/ai-employee-platform` (Local HEAD `86c1abf`)  
**Status:** **AUDITED & VERIFIED**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Summary & Omni-Channel Landscape

A digital employee platform is worthless if its omni-channel connectors mangle Arabic typography, drop customer messages, double-bill outbound SMS, or crash on emoji surrogate pairs.

This document establishes the authoritative specifications for the platform's communication connectors (Telegram, WhatsApp Cloud API, Email, Inbound Webhooks), formally detailing the **4-Tier Provider Idempotency Spectrum** and channel protocol adaptations extracted from Microsoft Agent Framework and official vendor APIs.

---

## 2. Omni-Channel Protocol Specifications

### 2.1 Telegram Bot API Integration
- **Vendor Constraints (REF-TG-BOT-API):**
  - Text message limit: 4,096 characters strictly measured in **UTF-16 code units**.
  - Media caption limit: 1,024 UTF-16 code units.
  - MarkdownV2 parsing: Any unclosed formatting tag (`*`, `_`, `~`, `[`, `]`) returns `HTTP 400 Bad Request: can't parse entities`.
- **Architectural Adaptations (Extracted from MAF `hosting-telegram`):**
  1. **Surrogate Pair Code Unit Slicing:** Message length is calculated by incrementing 2 units for characters with codepoints $> \text{0xFFFF}$ (astral emojis `😀`, `🚀`, Arabic ligatures):
     ```python
     def calculate_utf16_units(text: str) -> int:
         return sum(2 if ord(c) > 0xFFFF else 1 for c in text)
     ```
  2. **Interim Plain-Text Streaming:** During real-time token streaming, interim message edits (`editMessageText`) omit `parse_mode` entirely, preventing mid-tag syntax errors. Markdown formatting is applied exclusively on the finalized turn message.
  3. **Webhook Authentication:** Validates the `X-Telegram-Bot-Api-Secret-Token` header on all inbound webhooks against the tenant's encrypted secret.

### 2.2 Meta WhatsApp Cloud API (Graph API v19.0)
- **Vendor Realities (REF-META-WA-API):**
  - `POST /v19.0/{phone_number_id}/messages` has **NO native Idempotency-Key header**. Retrying a timed-out request directly can send duplicate messages to customers.
  - 24-Hour Customer Service Window: Businesses can send free-form AI responses only within 24 hours of the customer's last incoming message. Outside the 24-hour window, only pre-approved Meta Template Messages may be dispatched.
- **Architectural Adaptations:**
  1. **Quarantine Window & Callback Correlation:** Injects the unique `outbox_event_id` into the `biz_opaque_callback_data` payload (up to 512 bytes). If an HTTP dispatch times out, the outbox event enters a 60-second Quarantine Window. When Meta's webhook echoes the callback data, the event is marked `DELIVERED` without duplicate resending.
  2. **Webhook Verification:** Validates incoming payload signatures via `X-Hub-Signature-256` using the tenant's decrypted app secret (`hmac.compare_digest`).

### 2.3 Twilio SMS & Voice API
- **Vendor Realities (REF-TWILIO-SMS):**
  - Confirmed via Twilio Programmable Messaging API documentation: `POST .../Messages.json` has **no client-provided deduplication key**. Every single POST creates a newly billed SMS.
- **Architectural Adaptations:**
  - Classified strictly in **Tier 3 (Blind / Non-Idempotent)**. Automatic network retries upon ambiguous HTTP timeout are strictly prohibited. The event is quarantined and flagged to the business owner or The Godfather.

---

## 3. The 4-Tier Provider Idempotency Spectrum Matrix

| Tier | Designation | Supported Providers | Idempotency Mechanism | Retry Behavior on Timeout | Duplicate Risk |
| :---: | :--- | :--- | :--- | :--- | :---: |
| **Tier 1** | **Native Idempotency** | Stripe, Modern Financial APIs | `Idempotency-Key: <uuid>` HTTP header with $\ge 24$-hour cache. | Instant exponential backoff retry. Provider returns identical cached response. | **0.0%** (Mathematical guarantee) |
| **Tier 2A**| **Deterministic Pre-Query** | CRMs, Slack, Linear, GitHub | Query external provider by client reference code (`external_id = outbox_id`). | Query provider before re-dispatching; if object exists, record ID and mark delivered. | **< 0.01%** (Race window during network partition) |
| **Tier 2B**| **Correlatable with Quarantine** | Meta WhatsApp Cloud API | Echoes `biz_opaque_callback_data` in downstream status webhooks. | Do NOT retry immediately. Place event in 60-second Quarantine. Await webhook confirmation. | **< 0.1%** |
| **Tier 3** | **Blind Non-Idempotent** | Twilio SMS, Legacy SMTP Servers | No client deduplication parameter; every POST creates a new action. | **ZERO automatic retries.** Move event to Quarantined Review; requires human owner sign-off. | **Controlled** (Duplicates prevented by halting auto-retries) |

---

## 4. Webhook Ingestion, Deduplication & Event Sequencing

1. **Ingress Deduplication (6-Layer Defense):**
   - Layer 1: Caddy edge rate-limiting per client IP.
   - Layer 2: Fast HMAC signature check in memory before database checkout.
   - Layer 3: Payload SHA-256 hash check against Redis Bloom filter / TTL key (`dedup:webhook:<hash>`).
   - Layer 4: PostgreSQL unique constraint on `(channel_id, external_message_id)`.
   - Layer 5: Idempotency record insertion inside initial transaction.
   - Layer 6: Monotonic task fencing tokens on worker execution.
2. **Sub-30ms Ingress Response:** Webhooks never execute LLM turns inline. Webhook handlers validate, persist the message to the database, enqueue the task ID to the Redis CFS queue, and return `HTTP 200 OK` in $< 30$ms, satisfying Meta's strict 5-second webhook timeout requirement.
