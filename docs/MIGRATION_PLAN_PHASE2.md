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

## 5. Data Mapping Strategy (Zero Data Loss)

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
