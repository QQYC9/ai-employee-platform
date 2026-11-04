# Legal, Regulatory & External Vendor Specifications Reference

**Document ID:** `LEGAL_AND_EXTERNAL_REFERENCES`  
**Package:** Second-Order Review Evidence Package  
**Audit Baseline Commit:** `1b3eb775d0c963fc18d9004ea20a2dc1255d5e46`  

---

## 1. Statutory & Regulatory References: Saudi PDPL

### 1.1 Saudi Personal Data Protection Law (PDPL)
- **Official Citation:** Royal Decree No. (M/19) dated 9/2/1443H, as amended by Royal Decree No. (M/148) dated 5/9/1444H.
- **Authority:** Saudi Data & AI Authority (SDAIA).
- **Article 18 (Destruction of Personal Data):**
  > *"The Controller shall destroy personal data once the purpose of its collection ceases to exist. However, it may retain such data after the purpose ceases if all identifying information is removed in accordance with the controls specified by the Regulations... The Controller may also retain personal data after the purpose ceases if there is a legal justification that requires keeping it for a specific period."*
- **Executive Regulations Article 4 (Methods of Destruction):**
  Outlines valid electronic destruction: permanent overwriting, physical destruction of storage media, or irreversible anonymization where re-identification is technically impossible.

### 1.2 Separation of Legal Text from Technical Proposals
- **Legal Mandate:** Destruction of personal data upon purpose expiration or consent withdrawal.
- **Architectural Proposal:** Envelope Encryption (DSEK) key destruction.
- **Distinction:** The law mandates *destruction or irreversible anonymization*; it does not prescribe Envelope Encryption specifically. Envelope Encryption is a recognized cryptographic method to achieve electronic destruction without invalidating immutable append-only hash chains.

---

## 2. External Vendor Protocol Specifications

### 2.1 Meta WhatsApp Cloud API (Graph API v19.0)
- **Official Documentation:** Meta for Developers — WhatsApp Business Platform Cloud API (`/messages`).
- **24-Hour Customer Service Window:**
  - A business can send free-form text messages to an end-user only within 24 hours of the customer's last inbound message.
  - Inbound messages **open and reset** the 24-hour window.
  - Sending a free-form message outside the 24-hour window returns **Error Code `#131047`** (`Re-engagement message required`).
  - Outside the 24-hour window, the business can only send pre-approved **Template Messages** (`type: "template"`).
- **Delivery Webhooks & Idempotency:**
  - `POST /messages` does not accept an `Idempotency-Key` HTTP header.
  - `biz_opaque_callback_data` (maximum 512 characters) is echoed back in downstream status webhooks (`sent`, `delivered`, `read`).

### 2.2 Telegram Bot API
- **Official Documentation:** Telegram Bot API (`sendMessage`, `editMessageText`).
- **Message Length Constraints:**
  - `sendMessage` text limit: 4,096 characters strictly measured in **UTF-16 code units**.
  - Astral emojis (e.g. `🚀`, flags, compound ZWJ sequences) count as 2 or more UTF-16 code units.
- **Rate Limits:**
  - Single private chat: 1 message per second.
  - Global bot dispatch limit: 30 messages per second.
  - Aggressive messaging (>20 msgs/min to one user) triggers anti-spam heuristic blocks (`HTTP 429 Too Many Requests`).

### 2.3 PostgreSQL & pgvector Access Methods
- **Official Documentation:** `pgvector/pgvector` GitHub repository & PostgreSQL 17 Access Method Specification.
- **HNSW Index Access Method:**
  - HNSW in `pgvector` operates on single vector columns (`vector(N)`).
  - Multi-column / composite index definitions `(column1, vector_column)` raise error:
    `psycopg.errors.FeatureNotSupported: access method "hnsw" does not support multicolumn indexes`.
  - In `pgvector 0.8.0+`, iterative scanning parameter `hnsw.iterative_scan` was introduced supporting values `'off'`, `'relaxed_order'`, and `'strict_order'`.

---
*End of LEGAL_AND_EXTERNAL_REFERENCES.md.*
