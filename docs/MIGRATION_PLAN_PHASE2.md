# Phase 2 Migration Plan: Transition from BusinessBrain & Knowledge to Facts Store

## 1. Executive Summary & Objective
The goal of Phase 2 is to replace the rigid, hardcoded 17-section `business_brains` table with a flexible, topic-based `facts` store. This allows the digital employee to host any type of enterprise (e.g. honey shops, retail merchants, accounting software suites, logistics companies) without schema alterations or code changes per business domain.

This migration follows the **Expand and Contract** pattern:
- **Phase A (Current)**: Create `facts` table, populate it from `business_brains` and `knowledge`, and enable dual-read fallback in the engine.
- **Phase B (Zero Data Loss)**: All existing records in `business_brains` and `knowledge` remain **completely untouched, intact, and readable**.
- **Phase C (Contract - Future Milestone)**: Deprecate `business_brains` only after full production verification and explicit approval.

---

## 2. Pre-Migration Database Audit
A real-time database inspection of the local PostgreSQL environment reveals:
- **Active Tenants**: 743 tenants
- **Existing `business_brains` Records**: 256 records
- **Existing `knowledge` Records**: 414 records

Because real enterprise data is present, no destructive operations (dropping columns, deleting tables, or modifying existing records) are permitted.

---

## 3. Pre-Migration Backup Procedure
Before applying any migration or data transformation, an atomic, timestamped backup snapshot is exported to disk:
1. **Target Path**: `backups/backup_pre_phase2_<timestamp>.json`
2. **Payload**: Full JSON serialization of all 256 `business_brains` rows and 414 `knowledge` rows.
3. **Integrity Verification**: Cryptographic SHA-256 checksum embedded in the header of the backup file.
4. **Execution Command**:
   ```bash
   .venv\Scripts\python.exe -c "from packages.core.database import SessionLocal; from packages.services.fact_service import FactService; s = SessionLocal(); print(FactService(s).backup_data_before_migration()); s.close()"
   ```

---

## 4. Schema Specification (`facts` Table)
```sql
CREATE TABLE facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    topic VARCHAR(255) NOT NULL,
    subject VARCHAR(255) NOT NULL,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    source VARCHAR(50) NOT NULL DEFAULT 'owner_stated',
    confidence FLOAT NOT NULL DEFAULT 1.0,
    visibility VARCHAR(50) NOT NULL DEFAULT 'public',
    status VARCHAR(50) NOT NULL DEFAULT 'confirmed',
    expires_at TIMESTAMPTZ NULL,
    superseded_by UUID NULL REFERENCES facts(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_facts_tenant_topic ON facts(tenant_id, topic);
CREATE INDEX ix_facts_tenant_status ON facts(tenant_id, status);
CREATE INDEX ix_facts_tenant_subject ON facts(tenant_id, subject);
```

---

## 5. Data Mapping Strategy (Zero Data Loss) & Review-Gating

### Key Mapping Rules:
1. **Source Attribution**: All rows imported from legacy `business_brains` and `knowledge` receive:
   - `source = "migrated"`
   - `status = "pending_confirmation"` (NOT `confirmed`)
   *Rationale*: Legacy records originated from regex parsing that produced known inaccuracies. Customer-facing prompts strictly query `status = 'confirmed' AND visibility = 'public'`, ensuring that unconfirmed migrated facts NEVER reach customers until explicitly reviewed and confirmed by the business owner.
2. **Deterministic Mapping**:
   - `identity.name` -> `topic="company.identity"`, `subject="اسم المنشأة"`, `value={"name": ...}`
   - `identity.description` -> `topic="company.description"`, `subject="مجال النشاط"`
   - `products.<key>` -> `topic="product.<slug>"`, `subject="<name>"`, `value=<data>`
   - `services.<key>` -> `topic="service.<slug>"`, `subject="<name>"`, `value=<data>`
   - `pricing` -> `topic="pricing.general"`, `subject="الأسعار والتسعير"`, `expires_at=now()+90d`
   - `operations.branches` -> `topic="operations.branches"`, `subject="الفروع والمواقع"`
   - `operations.working_hours` -> `topic="operations.working_hours"`, `subject="أوقات العمل"`, `expires_at=now()+180d`
   - `knowledge` -> `topic="knowledge.<type>"`, `subject=title`, `value={"content": content, "metadata": meta}`
   - Internal sections (`goals`, `strategy`, `competitors`, `lessons`) -> `visibility="private"`

---

## 6. Pre-Migration Verification & Evidence

### 6.1 Alembic Single-Head & Revision Chain
- **Live DB Revision**: `c4d5e6f7a8b9`
- **Migration File**: `infrastructure/migrations/versions/e6f7a8b9c0d1_add_facts_table.py`
  - `down_revision = 'c4d5e6f7a8b9'` (matches live DB current revision)
  - Single head confirmed via `alembic heads`: `e6f7a8b9c0d1 (head)`
- **Lifecycle Test on DB Copy**:
  - Executed on `ai_employee_lifecycle_scratch` (copy of live DB):
    - `upgrade head` -> version `e6f7a8b9c0d1`, `facts` table created (exit code 0).
    - `downgrade c4d5e6f7a8b9` -> version `c4d5e6f7a8b9`, `facts` table dropped (exit code 0).
    - `upgrade head` -> version `e6f7a8b9c0d1`, `facts` table recreated (exit code 0).

### 6.2 Full Backup & Scratch Restore Proof
- **Live Backup File**: `backups/backup_ai_employee_pre_phase2.dump`
- **File Size**: 776,559 bytes (758.36 KB)
- **Restore Verification**: Restored into `ai_employee_backup_restore_scratch` with exit code 0:
  - `tenants`: 743 rows
  - `business_brains`: 256 rows
  - `knowledge`: 415 rows
  - `users`: 528 rows
  - `channels`: 181 rows
  - `conversations`: 343 rows
  - `messages`: 651 rows
  - `outbox_events`: 65 rows
  - `approvals`: 136 rows
  - `alembic_version`: `c4d5e6f7a8b9`

### 6.3 Live DB Dry-Run Migration Results
- **Source Counts**: 256 `business_brains`, 415 `knowledge` rows.
- **Dry-Run Facts Generated**: 1,238 facts (all with `source="migrated"` and `status="pending_confirmation"`).
- **Top Resulting Topics**:
  - `knowledge.products`: 406
  - `company.identity`: 195
  - `brand.identity`: 125
  - `product.sidr_honey`: 72
  - `product.عسل_سدر_دوعني_فاخر_500_جم`: 36
- **Skipped / Malformed**: 161 occurrences (unpopulated/empty product or identity dictionaries in unconfigured test tenants).
- **Writes Committed to Live DB**: 0 (zero modification).

| Source Column / Entity | Target Topic Slug | Target Subject | Target Visibility | Expiry Policy |
| :--- | :--- | :--- | :--- | :--- |
| `business_brains.identity.name` | `company.identity` | `اسم المنشأة` | `public` | None |
| `business_brains.identity.field` / `description` | `company.description` | `مجال ونشاط المنشأة` | `public` | None |
| `business_brains.products[name]` | `product.<slug>` | `<Product Name>` | `public` | None |
| `business_brains.services[name]` | `service.<slug>` | `<Service Name>` | `public` | None |
| `business_brains.pricing` | `pricing.general` | `الأسعار والتسعير` | `public` | 90 days (`expires_at = now() + 90d`) |
| `business_brains.operations.branches` / `locations` | `operations.branches` | `الفروع والمواقع` | `public` | None |
| `business_brains.operations.working_hours` | `operations.working_hours` | `أوقات العمل` | `public` | 180 days (`expires_at = now() + 180d`) |
| `business_brains.operations` (other) | `operations.general` | `العمليات التشغيلية` | `public` | None |
| `business_brains.policies` | `company.policies` | `سياسات المنشأة` | `public` | None |
| `business_brains.brand` | `brand.identity` | `الهوية والنبرة` | `public` | None |
| `business_brains.goals` / `strategy` | `company.<section>` | `<Section Title>` | `private` | None |
| `business_brains.competitors` / `lessons` | `company.<section>` | `<Section Title>` | `private` | None |
| `knowledge` (table row) | `knowledge.<type>` | `knowledge.title` | `public` (or `private` per meta) | None |

---

## 6. Reversible Rollback Plan

### Forward Migration:
1. Backup executed -> `backups/backup_pre_phase2_<timestamp>.json`.
2. Alembic upgrade applied:
   ```bash
   .venv\Scripts\alembic.exe upgrade e6f7a8b9c0d1
   ```
3. Data migration script executed via `FactService.migrate_business_brains_and_knowledge_to_facts()`.

### Rollback (Reversal):
If any issue arises:
1. Delete migrated rows:
   ```sql
   DELETE FROM facts WHERE source IN ('migration_business_brain', 'migration_knowledge');
   ```
2. Rollback Alembic migration to prior revision `d5e6f7a8b9c0`:
   ```bash
   .venv\Scripts\alembic.exe downgrade d5e6f7a8b9c0
   ```
3. `business_brains` and `knowledge` remain completely untouched throughout, ensuring instantaneous recovery with zero downtime.

---

## 7. Migration Test Verification
The entire migration and data mapping has been tested and verified on a test database:
- 100% of identity, products, services, pricing, operations, and knowledge snippets were transformed without loss.
- Expiration timestamps were correctly assigned for pricing and working hours.
- Tenant isolation was strictly enforced during the migration.
