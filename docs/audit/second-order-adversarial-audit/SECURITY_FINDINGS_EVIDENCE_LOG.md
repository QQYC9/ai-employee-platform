# Evidence Log: Security, Ingress Routing, Multi-Tenancy & Cryptography

**Document ID:** `SECURITY_FINDINGS_EVIDENCE_LOG`  
**Audit Standard:** Second-Order Adversarial Audit  
**Target Findings:** F-01 (15 API Routers), F-02 (Static AES-256 AAD), F-07 (PostgreSQL RLS), F-14b (Hardcoded Approval Key)

---

## 1. Deep-Dive Audit: Finding F-01 (15 API Routers Lacking Tenant Context)

### 1.1 Previous Claim
The previous audit asserted that 15 out of 28 API routers in `apps/agent/api/v1/` use `Depends(get_current_user)` instead of `Depends(get_tenant_context)`, failing to activate the `tenant_context` ContextVar and causing any downstream call to `get_current_tenant_id()` to crash with `RuntimeError: No tenant context is active`.

### 1.2 Repository Evidence & AST Verification
- **File:** `apps/agent/main.py` lines 136–163:
  Routers are included via `app.include_router(..., prefix=API_PREFIX)` without any router-level dependencies or ASGI middleware.
- **AST Scan of `apps/agent/api/v1/*.py`:**
  - **10 Routers with `get_tenant_context`:** `action_policies.py`, `approvals.py`, `audit.py`, `capability_tools.py`, `decision.py`, `documents.py`, `permissions.py`, `tool_integrations.py`, `tools.py`, `traces.py`.
  - **15 Tenant Routers using `get_current_user` ONLY:** `agent_capabilities.py`, `agents.py`, `ai_providers.py`, `auth.py`, `campaigns.py`, `capabilities.py`, `channels.py`, `conversations.py`, `customers.py`, `knowledge.py`, `memory.py`, `proactive_workflows.py`, `self_development.py`, `tasks.py`, `tenants.py`.
  - **Other:** `admin.py` (Superadmin), `admin_integrations.py` (Webhook/Admin), `webhooks.py` (Signature validated).
- **Code Behavior in `packages/auth/context.py` & `packages/tenants/context.py`:**
  ```python
  # packages/auth/context.py:12
  def get_tenant_context(current_user: User = Depends(get_current_user)):
      with tenant_context(current_user.tenant_id):
          yield current_user

  # packages/tenants/context.py:22
  def get_current_tenant_id() -> UUID:
      tenant_id = _current_tenant_id.get()
      if tenant_id is None:
          raise RuntimeError("No tenant context is active")
      return tenant_id
  ```

### 1.3 Adversarial Scrutiny & Severity Revision
- **Does the application currently crash on these 15 routes?**
  **NO.** Because in those 15 routers, developers manually threaded `current_user.tenant_id` as an explicit argument into repository and service functions (e.g. `agent_service.get_agents(tenant_id=current_user.tenant_id)`).
- **Why is it an architectural vulnerability?**
  If any developer introduces a service that relies on `get_current_tenant_id()`, or if PostgreSQL Row-Level Security (RLS) is enabled via connection hooks querying the ContextVar, all 15 routes will immediately crash with `RuntimeError`.
- **Verdict:** `CONFIRMED` as a repository fact. Severity revised from **P0** to **P1 (High)** because it is an architectural defect and barrier to centralized context, but does not cause an immediate production crash under current explicit parameter passing.

---

## 2. Deep-Dive Audit: Finding F-02 (Static AES-256-GCM AAD)

### 2.1 Previous Claim
The previous audit asserted that `packages/core/crypto.py` uses a static global byte string for AES-256-GCM Authenticated Associated Data (AAD), contradicting documentation claims that secrets are bound to `tenant_id` and allowing cross-tenant secret portability.

### 2.2 Repository Evidence
- **File:** `packages/core/crypto.py` lines 44–45:
  ```python
  PREFIX = "enc:v1:"
  ASSOCIATED_DATA = b"ai-employee-platform-secret-v1"
  ```
- **Lines 103–107 & 136–140:**
  ```python
  ciphertext_and_tag = self._aesgcm.encrypt(nonce, data_bytes, self.ASSOCIATED_DATA)
  ...
  plaintext_bytes = self._aesgcm.decrypt(nonce, ciphertext_and_tag, self.ASSOCIATED_DATA)
  ```
- **Documentation Claim in `docs/architecture/SECURITY_AND_MULTI_TENANCY.md:81`:**
  > *"3. Decryption at Rest: Integration secrets are stored encrypted in PostgreSQL using AES-256-GCM with authenticated associated data (AAD) bound to `tenant_id`."*

### 2.3 Adversarial Reproduction & Impact
- **Reproduction:** An encrypted secret generated for Tenant A was decrypted using the service without passing any tenant context. The decryption succeeded with 100% fidelity.
- **Security Impact:** If a database read vulnerability or an improper API endpoint allows Tenant B to obtain Tenant A's ciphertext string, Tenant B's agent can decrypt and use Tenant A's private WhatsApp bot token or OpenAI key.
- **Verdict:** `CONFIRMED` as a critical security defect (P0).

---

## 3. Deep-Dive Audit: Finding F-07 (PostgreSQL Row-Level Security)

### 3.1 Previous Claim
The previous audit asserted that PostgreSQL Row-Level Security (RLS) is completely missing from migrations, despite being mandated as Tier 3 defense-in-depth.

### 3.2 Repository Evidence
- We inspected 100% of Alembic migration versions in `infrastructure/migrations/versions/*.py`.
- **Result:** Exactly zero instances of `ENABLE ROW LEVEL SECURITY` or `CREATE POLICY`.
- **Documentation Inconsistency:** `SECURITY_AND_MULTI_TENANCY.md:68` defined Tier 3 strictly as *"Relational Schema Composite Keys: PRIMARY KEY (tenant_id, id)"*. It did NOT promise RLS. RLS was introduced as a recommended invariant by `INDEPENDENT_ADVERSARIAL_REVIEW.md:64`.

### 3.3 Adversarial Scrutiny & Trade-Offs
- Enforcing RLS in an async connection pool (SQLAlchemy AsyncEngine + PgBouncer in transaction mode) requires executing `SET LOCAL app.current_tenant_id = :id` on every transaction checkout.
- RLS provides strong kernel-level defense against accidental un-scoped queries, but introduces connection setup latency and query planning overhead.
- **Verdict:** `PARTIALLY CONFIRMED`. The lack of RLS in the database is a repository fact. However, labeling it as a "broken specification" is inaccurate because the original blueprint did not specify RLS. It remains an **Architectural Proposal / Founder Decision (FD-05)**.

---

## 4. Deep-Dive Audit: Finding F-14b (Hardcoded Fallback Approval Secret Key)

### 4.1 Repository Evidence
- **File:** `packages/services/approval_service.py` lines 112–114:
  ```python
  secret = (
      os.environ.get("APPROVAL_SECRET_KEY")
      or "fallback_approval_hmac_secret_key_32b_minimum!"
  )
  ```
- **Impact:** If `APPROVAL_SECRET_KEY` is omitted from the deployment environment, challenge tokens can be forged by any attacker who reads this open repository.
- **Verdict:** `CONFIRMED` as a Critical Defect (P0).

---
*End of Security Findings Evidence Log.*
