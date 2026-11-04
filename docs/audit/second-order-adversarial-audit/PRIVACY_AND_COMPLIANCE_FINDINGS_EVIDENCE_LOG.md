# Evidence Log: Privacy, Statutory Data Lifecycle & Saudi PDPL Compliance

**Document ID:** `PRIVACY_AND_COMPLIANCE_FINDINGS_EVIDENCE_LOG`  
**Audit Standard:** Second-Order Adversarial Audit  
**Target Finding:** F-08 (Saudi PDPL Article 18 Statutory Erasure Failure & HMAC Audit Chains)

---

## 1. Deep-Dive Audit: Finding F-08 (Saudi PDPL Article 18 & Cryptographic Erasure)

### 1.1 Previous Claim
The previous audit asserted that the platform's reliance on soft deletion (`status = 'DELETED'`) violates Article 18 of the Saudi Personal Data Protection Law (PDPL) and GDPR Article 17, because customer PII remains in plaintext inside immutable HMAC-SHA256 audit logs (`audit_events`) and checkpoint states (`execution_checkpoints`), where deleting rows would destroy cryptographic audit chains.

### 1.2 Statutory & Regulatory Framework
- **Saudi PDPL (Royal Decree No. M/19 amended by M/148):**
  - **Article 18:** Mandates that the Controller must destroy personal data as soon as the purpose of its collection ceases to exist, or upon withdrawal of consent, unless an explicit statutory retention requirement applies.
  - **Executive Regulations Article 4:** Outlines the approved methods for personal data destruction: physical destruction, electronic destruction (permanent overwriting), or irreversible anonymization.
- **The Legal-Cryptographic Dilemma:**
  - `MASTER_ARCHITECTURE_BLUEPRINT.md:635` establishes an immutable, tamper-evident audit log:
    $$\text{CurrentHash} = \text{HMAC-SHA256}(K_{\text{audit}}, \text{PrevHash} \parallel \text{Timestamp} \parallel \text{TenantID} \parallel \text{Action} \parallel \text{PayloadDigest})$$
  - The hourly Merkle root is anchored to external Write-Once-Read-Many (WORM) storage.
  - If a customer requests data erasure (Right to Erasure / Right to Destruction):
    - If an administrator executes `DELETE FROM audit_events WHERE ...` or overwrites the payload, the HMAC-SHA256 hash chain is immediately broken, triggering a compliance failure in SOC 2 and ISO 27001 audits.
    - If the platform merely marks `fact_entities.status = 'DELETED'`, the raw customer PII (phone number, national ID, address) remains in plaintext inside `audit_events.payload` and `execution_checkpoints.state_payload`, directly violating Saudi PDPL Article 18.

### 1.3 Technical Verification in Codebase
- In `packages/models/domain.py:636`, `AuditEvent` stores `payload: JSONB`. If an agent tool call `send_whatsapp_message(to="+96650...", text="...")` is logged, the phone number is stored in plaintext in the database row and its WAL.
- In `packages/services/fact_service.py`, fact updates update status to `SUPERSEDED` or `DELETED`, leaving old fact content intact in historical rows.
- No cryptographic shredding or field-level encryption exists in the current codebase.

### 1.4 Assessment of Proposed Remedy: Envelope Encryption
- **The Proposal:** Encrypt customer PII fields using an ephemeral Data Subject Encryption Key (DSEK) $K_{subject}$ managed in KMS.
- **Evaluation:** This is a recognized cryptographic pattern (Crypto-Shredding). Destroying $K_{subject}$ renders ciphertext permanently unreadable without modifying database rows or invalidating HMAC hash chains.
- **Verdict:** `CONFIRMED` as a Critical Compliance & Architecture Defect (P0).

---
*End of Privacy & Compliance Findings Evidence Log.*
