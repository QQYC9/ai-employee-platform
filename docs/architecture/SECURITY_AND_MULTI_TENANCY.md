# Security and Multi-Tenancy Architecture — Defense-in-Depth & Cryptographic Governance

**Document ID:** `SECURITY_AND_MULTI_TENANCY`  
**Governing Standard:** Full-Platform Target Vision (`docs/PROJECT_VISION.md` Sections 10, 14, 18; User Request Section 10)  
**Target Repository:** `QQYC9/ai-employee-platform`  
**Status:** **AUTHORITATIVE ARCHITECTURAL SPECIFICATION**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Multi-Layered Defense-in-Depth for Tenant Isolation

Tenant isolation is never treated as a single, unprovable absolute. The platform implements an engineered **Four-Tier Defense-in-Depth Architecture** where each layer operates independently:

```mermaid
flowchart TD
    subgraph Layer1 ["Tier 1: Application Layer (Immutable Scope)"]
        Req[Incoming Request] --> ResolveScope[Resolve Immutable Scope(tenant_id, user_id, role)]
        ResolveScope --> Propagate[Explicit scope: Scope argument passed to every function]
    end

    subgraph Layer2 ["Tier 2: Data Access Layer (Base Repository)"]
        Propagate --> BaseRepo[Base SQLAlchemy Repository]
        BaseRepo --> QueryInject[Mandatory WHERE tenant_id = scope.tenant_id query binding]
    end

    subgraph Layer3 ["Tier 3: Relational Database Layer (Composite Keys)"]
        QueryInject --> RelationalDB[(PostgreSQL 17 Relational Engine)]
        RelationalDB --> SchemaConstraints[PRIMARY KEY (tenant_id, id) & Foreign Key Cascade scoping]
    end

    subgraph Layer4 ["Tier 4: Tool Execution Sandboxing"]
        Propagate --> ToolRunner[Sandboxed Tool Execution Runner]
        ToolRunner --> EntityVerify[Pre-Execution Tenant Ownership Verification on Target Resources]
    end
```

### 1.1 Tier 1: Immutable Execution `Scope`
Relying solely on Python's `contextvars` risks silent context loss across thread pools, background Celery workers, or async event loops. In accordance with RagLeap Core's verified security model (`core/security/scope.py`):
```python
@dataclass(frozen=True)
class Scope:
    tenant_id: str
    subject_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None

    def __post_init__(self):
        if not self.tenant_id or not _VALID_IDENTIFIER.match(self.tenant_id):
            raise InvalidScopeError(f"Invalid tenant_id format: {self.tenant_id}")
```
- **Architectural Rule:** Every repository method, database service, tool execution wrapper, and background worker **must accept an explicit `scope: Scope` argument**.

### 1.2 Tier 2: Repository-Level Automated Scoping
All data access operations inherit from `BaseTenantRepository`:
```python
class BaseTenantRepository(Generic[T]):
    async def get_by_id(self, entity_id: UUID, scope: Scope) -> T | None:
        stmt = select(self.model_class).where(
            self.model_class.id == entity_id,
            self.model_class.tenant_id == scope.tenant_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
```

### 1.3 Tier 3: Relational Schema Composite Keys
Every relational table holding tenant data enforces composite primary or unique constraints containing `tenant_id` (e.g., `PRIMARY KEY (tenant_id, id)`), making cross-tenant relational joins or foreign key cascades structurally impossible at the database engine level.

### 1.4 Tier 4: Tool Sandboxing & Pre-Dispatch Validation
Before executing any tool that acts on an external resource (e.g. sending a message or charging a card), the tool runner verifies that the target customer or account belongs to `tool_context.scope.tenant_id`.

---

## 2. Secrets Management & Hardening (`SecretStr`)

Sensitive credentials (WhatsApp tokens, Telegram bot tokens, AI API keys) are secured using RagLeap Core's `SecretStr` primitive (`ragleap-security/secrets.py`):
1. **Accidental Leakage Prevention:** `str(secret)`, `repr(secret)`, and f-string interpolation return strictly `[REDACTED]`.
2. **Serialization Safety:** Cannot be serialized to JSON, pickled, or emitted in logging traces.
3. **Decryption at Rest:** Integration secrets are stored encrypted in PostgreSQL using **AES-256-GCM** with authenticated associated data (AAD) bound to `tenant_id`.
4. **Timing-Attack Resistance:** Secret equality checks use constant-time `hmac.compare_digest`.
5. **Dashboard Masking:** API endpoints return `******` for secret values; plaintext is never transmitted back to the browser.

---

## 3. Tamper-Evident SHA-256 HMAC Audit Chain & External WORM Anchoring

All administrative actions, Level 2 approvals, and tool executions are recorded in an append-only cryptographic audit chain:

$$\text{CurrentHash} = \text{HMAC-SHA256}(K_{\text{audit}}, \text{PrevHash} \parallel \text{Timestamp} \parallel \text{TenantID} \parallel \text{Action} \parallel \text{PayloadDigest})$$

```sql
CREATE TABLE audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    sequence_number BIGINT NOT NULL,
    action VARCHAR(128) NOT NULL,
    actor_id VARCHAR(64) NOT NULL,
    payload_digest VARCHAR(64) NOT NULL,
    previous_hash VARCHAR(64) NOT NULL,
    current_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT uq_tenant_sequence UNIQUE (tenant_id, sequence_number)
);
```

### 3.1 External Anchoring on WORM Storage
- **Boundary Reality:** An internal database hash chain detects row alteration or insertion, but an adversary with direct database write access could delete or recompute the entire table.
- **WORM Anchoring Solution:** Every hour, a background job calculates the root Merkle hash of all audit records in that window and commits it to an **external Write-Once-Read-Many (WORM) storage target** (e.g. AWS S3 Object Lock in Compliance Mode or an append-only signed Git audit repository). Once written, the external root cannot be overwritten or deleted by database administrators.

---

## 4. Human Approval Security: Context Binding & Replay Protection

To prevent parameter tampering, race conditions, or replay attacks on Level 2 approvals:

### 4.1 Canonical Input Serialization (RFC 8785 / JCS)
Before suspending an approval request, arguments are serialized to canonical JSON (lexicographical sorting, no whitespace):
$$\text{inputs\_digest} = \text{HMAC-SHA256}(K_{\text{approval\_hmac}}, \text{ContextPayload})$$
Where:
$$\text{ContextPayload} = \text{approval\_id} \parallel \text{tenant\_id} \parallel \text{execution\_id} \parallel \text{step\_index} \parallel \text{tool\_name} \parallel \text{CanonicalJSON}(\text{arguments}) \parallel \text{required\_role} \parallel \text{expires\_at}$$

### 4.2 Atomic State Resumption Protocol
1. **Row Lock Acquisition:** The resumption query executes `SELECT ... FOR UPDATE` on `approval_requests WHERE approval_id = :id`.
2. **Strict FSM State Check:** Status must be `PENDING`. As part of the same transaction, status updates immediately to `CONSUMED`. Subsequent replay attempts see `status == CONSUMED` and are rejected.
3. **Digest Re-verification:** Recomputes the digest and verifies it matches `inputs_digest` using constant-time comparison.
4. **Live Entitlement Re-check:** Verifies the resolving user possesses the `required_role` and the tenant's account is currently active.

---

## 5. Security Boundaries of Controlled Self-Extension

The platform strictly decouples self-extension into six isolated phases:

```
[ Phase 1: Generation ] ──> [ Phase 2: UV Sandbox Validation ] ──> [ Phase 3: Authorization Gate ]
                                                                                │
[ Phase 6: Production ] <── [ Phase 5: Runtime Activation ] <── [ Phase 4: Staged Registration ]
```

1. **Zero Autonomous Write Authority on Production Code:** Autonomous agents and The Godfather have **ZERO write authority** to modify core platform framework files, alter production database schemas, or execute un-sandboxed code.
2. **Explicit Human Gate:** Every newly synthesized tool, skill, or business module requires explicit human approval (Founder for system capabilities; Tenant Owner for business modules) before transitioning from `STAGED` to `ACTIVE`.
3. **Instant Revocation:** Any capability can be revoked instantly via the dashboard, setting `status = 'REVOKED'`, which terminates ongoing instances and expels the tool from runtime memory.
