# Security, Multi-Tenancy Governance & Authority Audit: Defense-in-Depth Analysis

**Document ID:** `SECURITY_TENANCY_AND_AUTHORITY_AUDIT`  
**Governing Standard:** Full-Platform Target Vision (`docs/PROJECT_VISION.md` Sections 14, 15, 17)  
**Audit Standard:** Strict Forensic Vulnerability Analysis against Code & Protocols  
**Target Repository:** `QQYC9/ai-employee-platform` (Local HEAD `fc94752`)

---

## 1. Executive Summary & Security Scorecard

| Security Subsystem | Design Specification | Implementation Reality in Code | Vulnerability / Defect | Severity |
| :--- | :---: | :---: | :--- | :---: |
| **Ingress Tenant Context Propagation** | 4-Tier Isolation | **15 of 28 Routers Broken** | Missing `get_tenant_context` in `apps/agent/main.py`; ContextVar uninitialized. | **P0** |
| **Database Row-Level Security (RLS)** | Kernel-Enforced Isolation | **0% Implemented in Migrations** | Zero RLS policies in PostgreSQL; relies solely on application Python filters. | **P1** |
| **Tenant Integration Secret Encryption** | AES-256-GCM Tenant-Bound | **Static Global AAD in Code** | `packages/core/crypto.py:45` uses static byte string; permits cross-tenant secret migration. | **P0** |
| **Approval Challenge Verification** | RFC 8785 Canonical JSON | **Hardcoded Fallback Secret in Code** | `packages/services/approval_service.py:113` contains hardcoded secret key string. | **P0** |
| **Tamper-Evident Audit Chaining** | HMAC-SHA256 WORM Chaining | **0% Implemented in Models** | Existing `AuditEvent` model lacks previous hash, sequence, and payload digest columns. | **P1** |
| **Statutory Data Subject Erasure (PDPL)** | Envelope Encryption Key Shredding | **Soft Deletion (`DELETED`) Only** | Customer PII retained in immutable audit logs and checkpoint payloads. | **P0** |
| **The Godfather Supervisory Authority** | Zero Write / Telegram Gated | **Watertight Boundaries in Design** | Alert coalescing window miscalculated (5s burst vs Telegram chat limits). | **P1** |

---

## 2. Ingress & Context Isolation Forensics: The 15-Router Defect

### 2.1 Code AST Verification in `apps/agent/main.py`
An exhaustive AST dependency audit of all 28 routers in `apps/agent/api/v1/*.py` reveals:
- **10 Routers correctly enforce `Depends(get_tenant_context)`:**
  `action_policies.py`, `approvals.py`, `audit.py`, `capability_tools.py`, `decision.py`, `documents.py`, `permissions.py`, `tool_integrations.py`, `tools.py`, `traces.py`.
- **15 Routers incorrectly use `Depends(get_current_user)` WITHOUT tenant context:**
  `agents.py`, `agent_capabilities.py`, `ai_providers.py`, `auth.py`, `campaigns.py`, `capabilities.py`, `channels.py`, `conversations.py`, `customers.py`, `knowledge.py`, `memory.py`, `proactive_workflows.py`, `self_development.py`, `tasks.py`, `tenants.py`.
- **2 Routers have no tenant dependency:** `admin_integrations.py`, `webhooks.py`.
- **1 Superadmin router:** `admin.py`.

### 2.2 Operational Consequence
In `apps/agent/main.py`, routers are registered without top-level dependencies or ASGI middleware:
```python
app.include_router(agents_router, prefix=API_PREFIX)
app.include_router(campaigns_router, prefix=API_PREFIX)
```
When a tenant owner accesses `/api/v1/agents` or `/api/v1/campaigns`, FastAPI authenticates the user but does NOT initialize the `tenant_context` ContextVar (`_tenant_ctx.set(...)`). Any downstream service, repository, or tool calling `get_current_tenant_id()` immediately crashes with:
`RuntimeError: No tenant context is active`.
Developers were forced to manually thread `current_user.tenant_id` as parameter arguments, defeating the entire purpose of centralized multi-tenant context propagation.

### 2.3 Remediation: Global ASGI Tenant Middleware
Implement a mandatory ASGI middleware in `apps/agent/main.py`:
```python
class TenantContextMiddleware:
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            token = extract_bearer_token(scope)
            if token:
                payload = decode_jwt(token)
                tenant_id = UUID(payload.get("tenant_id"))
                token_reset = _tenant_ctx.set(TenantContext(tenant_id=tenant_id, ...))
                try:
                    await self.app(scope, receive, send)
                finally:
                    _tenant_ctx.reset(token_reset)
                return
        await self.app(scope, receive, send)
```

---

## 3. Cryptographic Storage & Isolation Vulnerabilities

### 3.1 Static AES-256-GCM AAD Exploit Vector
- **The Spec:** `SECURITY_AND_MULTI_TENANCY.md:81` claims secrets are stored using AES-256-GCM with authenticated associated data (AAD) cryptographically bound to `tenant_id`.
- **The Reality:** In `packages/core/crypto.py:45`:
  ```python
  class SecretsEncryptionService:
      PREFIX = "enc:v1:"
      ASSOCIATED_DATA = b"ai-employee-platform-secret-v1"  # STATIC GLOBAL BYTE STRING!
  ```
- **Exploitation:** Because the AAD is identical across all tenants, encrypted secrets are 100% portable. If an attacker or buggy migration copies an encrypted WhatsApp token or OpenAI key from Tenant A's row into Tenant B's channel row, Tenant B's agent can decrypt and use Tenant A's credentials without an authentication tag failure!
- **Remediation:** Enforce dynamic tenant-bound AAD:
  ```python
  def encrypt_secret(self, secret: str, tenant_id: UUID) -> str:
      aad = f"ai-employee-platform:{tenant_id}:v1".encode("utf-8")
      ...
  ```

### 3.2 Hardcoded Approval Fallback Secret
- **The Code:** In `packages/services/approval_service.py:113`:
  ```python
  secret = os.environ.get("APPROVAL_SECRET_KEY") or "fallback_approval_hmac_secret_key_32b_minimum!"
  ```
- **Exploitation:** If the environment variable is not explicitly injected in Docker Compose or Kubernetes, the service silently defaults to a public hardcoded string. An attacker can forge valid approval hashes and bypass human owner authorization.
- **Remediation:** Purge hardcoded fallback string. Raise `RuntimeError("APPROVAL_SECRET_KEY must be configured in environment")` at startup.

---

## 4. Statutory Privacy Compliance (Saudi PDPL & GDPR)

### 4.1 The Soft Deletion Fallacy
`KNOWLEDGE_AND_MEMORY_ARCHITECTURE.md:115` claims:
> *"Upon receiving an erasure request, PII records are securely erased or cryptographically shredded (`status = 'DELETED'`)."*
Setting a status flag to `DELETED` does NOT delete data:
1. Customer phone numbers, national IDs, and names remain in plaintext in the table row.
2. The data persists in PostgreSQL Write-Ahead Logs (WAL) and backup snapshots.
3. Plaintext PII is permanently baked into immutable `audit_events.payload` and `execution_checkpoints.state_payload`.
Under Saudi Personal Data Protection Law (PDPL) Article 18, failure to destroy personal data upon request or purpose expiration incurs substantial statutory penalties.

### 4.2 Solution: Cryptographic Shredding via Envelope Encryption
1. For every customer or data subject, generate an ephemeral **Data Subject Encryption Key (DSEK)** $K_{subject}$ managed in KMS.
2. Plaintext PII in tool arguments, audit logs, and checkpoints must be encrypted with $K_{subject}$ before database insertion.
3. Audit hash calculation uses the ciphertext:
   $$\text{AuditHash} = \text{HMAC-SHA256}(K_{\text{audit}}, \text{PrevHash} \parallel \dots \parallel \text{AES-GCM}(K_{subject}, \text{PII}))$$
4. Upon receiving an erasure request, permanently destroy $K_{subject}$ in KMS. The underlying PII becomes cryptographically unrecoverable, while the HMAC audit chain remains 100% mathematically intact!

---

## 5. The Godfather Supervisory Authority & Boundaries

### 5.1 Watertight Authority Architecture
The Godfather's boundary design is verified as exceptionally sound:
- **Zero Autonomous Write Authority:** No capability to execute runtime DDL, delete database records, modify user roles, or deploy code.
- **Out-of-Band Channel:** Communicates strictly via founder private Telegram bot.
- **Founder Webhook Confirmation:** Sensitive actions require an explicit HMAC-signed webhook (`YES <proposal_id>`).

### 5.2 Supervisory Conflation Resolution: Two-Tier Guardian Hierarchy
- **Tier 1 (The Godfather / الأب الروحي):** Platform-level supervisor. Monitors fleet-wide infrastructure, AI provider outages, database saturation, and global security. Advises the Platform Founder.
- **Tier 2 (Executive Supervisor / المشرف التنفيذي):** Tenant-level digital employee. Monitors tenant business KPIs, marketing campaign delivery, pending employee approvals, and customer escalations. Advises the Tenant Business Owner via their preferred channel.

---
*End of Security, Multi-Tenancy Governance & Authority Audit.*
