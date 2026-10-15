# Tenant Provisioning & Digital Employee Setup Architecture

## 1. Overview

The **Tenant Provisioning System** provides an atomic, production-ready onboarding workflow for commercial B2B tenants on the **AI Employee Platform**.

Unlike simple multi-user apps or generic chatbots, each tenant is provisioned with a fully isolated operating environment containing:
1. **Isolated Tenant Record**: Dedicated tenant ID, unique slug, and active status.
2. **Initial Tenant Owner Account**: Authenticated user with role `tenant_owner` and cryptographically hashed password (PBKDF2-HMAC-SHA256).
3. **Dedicated BusinessBrain**: Dedicated context profile containing business identity, products, services, target audience, operating rules, objectives, and communication preferences.
4. **Initial Digital Employee (Agent)**: Primary operational agent scoped exclusively to the tenant.
5. **Approved Capabilities Assignment**: Secure attachment of only validated global or tenant-approved capabilities (preventing unauthorized cross-tenant tool leakage).
6. **Safe Default Action Policies**: Defense-in-depth policies mandating human owner approval for sensitive actions (e.g. `external_payment`, `data_deletion`, `customer_broadcast`).

---

## 2. API Endpoints

### 2.1 Provision New Tenant
- **Route**: `POST /api/v1/tenants/provision`
- **Authorization**: `Bearer <token>` (Required role: `platform_admin` or `superadmin`)
- **Status Code**: `201 Created`

#### Request Payload (`TenantProvisioningRequest`):
```json
{
  "name": "Acme Innovations Inc",
  "slug": "acme-innovations",
  "owner_name": "Alice Johnson",
  "owner_email": "alice@acme.com",
  "owner_password": "StrongPassword123!",
  "business_brain": {
    "industry": "Artificial Intelligence SaaS",
    "products": ["AI Knowledge Assistant", "Automated Scheduler"],
    "services": ["Enterprise Agent Onboarding"],
    "pricing": {"tier": "enterprise", "currency": "USD"},
    "brand": {"voice": "Professional, authoritative"},
    "target_customers": ["B2B SaaS companies"],
    "competitors": ["Legacy CRM bots"],
    "business_objectives": ["Automate 80% of support queries"],
    "operating_rules": ["Never promise discounts over 15%"],
    "communication_preferences": {"tone": "concise", "language": "en"}
  },
  "agent": {
    "name": "Acme Operations Agent",
    "agent_type": "main",
    "system_config": {"model": "gemini-2.5-flash", "temperature": 0.2},
    "capability_ids": ["3ebde227-e475-4b50-9d48-a77206fc0511"]
  },
  "default_action_policies": [
    {
      "action": "external_payment",
      "resource": "finance",
      "requires_approval": true,
      "approval_for": "tenant_owner"
    }
  ]
}
```

#### Response (`TenantProvisioningResponse`):
```json
{
  "status": "provisioned",
  "tenant": {
    "id": "76ec2a6e-d308-46aa-b2b9-e137fbca20c7",
    "name": "Acme Innovations Inc",
    "slug": "acme-innovations",
    "status": "active",
    "created_at": "2026-10-16T00:55:00Z"
  },
  "owner": {
    "id": "4c94f56a-2005-4c0a-810a-66a9c72e2133",
    "name": "Alice Johnson",
    "email": "alice@acme.com",
    "role": "tenant_owner",
    "status": "active"
  },
  "agent": {
    "id": "9b1bcfb4-3bb1-4c17-91a1-94595faec2e8",
    "name": "Acme Operations Agent",
    "agent_type": "main",
    "status": "active"
  },
  "business_brain": {
    "id": "e2b3c4d5-6a7b-8c9d-0e1f-2a3b4c5d6e7f",
    "version": 1,
    "industry": "Artificial Intelligence SaaS",
    "sections_initialized": ["identity", "products", "services", "pricing", "brand", "customers", "competitors", "goals", "policies", "preferences"]
  },
  "assigned_capabilities": [
    {
      "id": "3ebde227-e475-4b50-9d48-a77206fc0511",
      "name": "Public Reporting",
      "slug": "public-reporting"
    }
  ],
  "action_policies": [
    {
      "action": "external_payment",
      "resource": "finance",
      "requires_approval": true,
      "approval_for": "tenant_owner"
    }
  ]
}
```

### 2.2 Inspect Tenant BusinessBrain
- **Route**: `GET /api/v1/tenants/me/brain`
- **Authorization**: `Bearer <token>` (Scoped strictly to `current_user.tenant_id`)
- **Status Code**: `200 OK`

### 2.3 Update Tenant BusinessBrain
- **Route**: `PATCH /api/v1/tenants/me/brain`
- **Authorization**: `Bearer <token>` (Required role: `tenant_owner`, `tenant_admin`, or `platform_admin`)
- **Status Code**: `200 OK`

---

## 3. Security and Multi-Tenant Isolation Guarantees

1. **Atomic Provisioning via Savepoints**:
   - The provisioning service wraps creation of Tenant, Owner, BusinessBrain, Agent, Capabilities, and Policies in a nested database savepoint (`db.begin_nested()`).
   - If any validation fails (e.g. email collision, invalid capability, or DB error), the entire operation rolls back immediately. No orphan records or partial tenants are created.

2. **Least Privilege & Role Enforcement**:
   - `platform_admin` is strictly required to call `/provision`. Regular members and tenant owners are rejected with `403 Forbidden`.
   - Modifying a tenant's BusinessBrain (`PATCH /tenants/me/brain`) or tenant settings (`PATCH /tenants/me`) requires tenant administrative privileges (`tenant_owner`, `tenant_admin`, `platform_admin`). Regular tenant members (`tenant_user`) receive `403 Forbidden`.

3. **Cross-Tenant Protection**:
   - **Capabilities & Tools**: Provisioning strictly prohibits assigning another tenant's private capabilities (`cap.tenant_id is not None and cap.tenant_id != tenant.id`). Attempts to do so raise `PermissionError` and trigger rollback.
   - **BusinessBrain**: `ContextRetriever` and `BusinessBrainService` strictly filter by `tenant_id`. Any cross-tenant access attempt raises `PermissionError`.
   - **Agents & Memory**: Agents belonging to Tenant A return `404 Not Found` when requested by Tenant B. Memory and Knowledge retrievals are filtered by `tenant_id`.

4. **Zero Secrets in Responses & Logs**:
   - Password hashes (`password_hash`), internal signing keys, and raw tokens are excluded from all provisioning responses and log records.

---

## 4. Local Testing Instructions

To run the complete tenant provisioning and multi-tenancy isolation test suite:
```bash
.\.venv\Scripts\python -m pytest tests/test_phase8_tenant_provisioning.py -v
```

To run the complete platform test suite (Phase 1 through Phase 8):
```bash
.\.venv\Scripts\python -m pytest -q
```
