# Dashboard Generation Architecture — Schema-Driven Declarative Interfaces

**Document ID:** `DASHBOARD_GENERATION_ARCHITECTURE`  
**Governing Standard:** Full-Platform Target Vision (`docs/PROJECT_VISION.md` Section 9; User Request Section 9)  
**Target Repository:** `QQYC9/ai-employee-platform`  
**Dashboards Covered:** `apps/tenant-dashboard` & `apps/admin-dashboard`  
**Status:** **AUTHORITATIVE ARCHITECTURAL SPECIFICATION**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Vision & The Dynamic UI Problem

In a platform capable of autonomously generating digital employees, tools, skills, and business modules, a critical bottleneck arises:
> *If every new capability, external API integration, or business workflow requires frontend software engineers to manually design, code, test, and deploy a new React page or modal, the entire premise of autonomous platform scalability collapses.*

The **Dashboard Generation Architecture** solves this bottleneck by introducing a **Schema-Driven Declarative Interface Engine**. Whenever a digital employee, tool, or dynamic module requires human input, credential entry, policy tuning, or ongoing management:
1. The backend capability registers a declarative **UI Schema Contract**.
2. Both the **Tenant Dashboard** and **Admin Dashboard** embed a shared, high-performance **Dynamic Schema Form Renderer (`DynamicFormRenderer.tsx`)**.
3. The renderer validates inputs on the client, respects field dependencies and conditional visibility, securely masks secrets, and submits payloads to authenticated backend endpoints without requiring a single line of new frontend code.

---

## 2. Declarative UI Schema Architecture & Data Model

Every declarative interface is modeled as an immutable Pydantic v2 schema stored in the relational database:

```sql
CREATE TABLE ui_interface_declarations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    interface_key VARCHAR(128) NOT NULL, -- e.g., 'tools.whatsapp_cloud.config', 'modules.inventory.settings'
    version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    owner_scope VARCHAR(32) NOT NULL,    -- 'ADMIN' (Platform Admin) or 'TENANT' (Subscriber)
    required_role VARCHAR(64) NOT NULL DEFAULT 'OWNER',
    title VARCHAR(255) NOT NULL,
    description TEXT NULL,
    category VARCHAR(64) NOT NULL,       -- 'INTEGRATION', 'AGENT_CONFIG', 'APPROVAL', 'MODULE_SETTINGS'
    schema_definition JSONB NOT NULL,    -- Complete Declarative Form Schema
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT uq_interface_key_version UNIQUE (interface_key, version)
);

CREATE TABLE tenant_ui_configurations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    interface_id UUID NOT NULL REFERENCES ui_interface_declarations(id),
    configuration_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_completed BOOLEAN NOT NULL DEFAULT FALSE,
    last_updated_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT uq_tenant_interface UNIQUE (tenant_id, interface_id)
);
```

---

## 3. The Declarative UI Schema Specification (Pydantic v2 Contract)

```python
class FieldType(str, Enum):
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    SELECT = "select"
    MULTI_SELECT = "multi_select"
    SECRET = "secret"          # Rendered as password with reveal toggle; masked on read
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    FILE_UPLOAD = "file_upload"
    JSON_SCHEMA = "json_schema"

class ValidationRule(BaseModel):
    required: bool = False
    min_length: int | None = None
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    regex_pattern: str | None = None
    custom_error_message: str | None = None

class ConditionalVisibility(BaseModel):
    depends_on_field: str
    condition_operator: Literal["equals", "not_equals", "in", "is_true", "is_false"]
    condition_value: Any

class FormFieldDeclaration(BaseModel):
    name: str
    label_en: str
    label_ar: str
    field_type: FieldType
    default_value: Any | None = None
    placeholder_en: str | None = None
    placeholder_ar: str | None = None
    help_text_en: str | None = None
    help_text_ar: str | None = None
    options: list[dict[str, str]] | None = None  # For select / multi_select
    validation: ValidationRule = Field(default_factory=ValidationRule)
    conditional_visibility: ConditionalVisibility | None = None
    is_secret: bool = False
    is_readonly: bool = False

class InterfaceDeclarationSchema(BaseModel):
    interface_key: str
    version: str = "1.0.0"
    owner_scope: Literal["ADMIN", "TENANT"]
    required_role: str = "OWNER"
    title_en: str
    title_ar: str
    description_en: str
    description_ar: str
    category: str
    submit_endpoint: str
    fields: list[FormFieldDeclaration]
```

---

## 4. Frontend Dynamic Form Rendering Engine (`DynamicFormRenderer`)

Deployed in both `apps/tenant-dashboard` and `apps/admin-dashboard`:

```mermaid
flowchart TD
    Fetch[1. Fetch Declarative Schema from /api/v1/ui-schemas/:key] --> ValidateSchema[2. Validate Schema Contract]
    ValidateSchema --> InitState[3. Initialize Form State & Populate Existing Values]
    InitState --> DependencyEval[4. Evaluate Conditional Visibility DAG]
    DependencyEval --> RenderComponents[5. Render Typed Tailwind/Lucide Components (RTL Arabic Support)]
    
    RenderComponents --> UserInput[6. User Input / Secret Entry]
    UserInput --> ClientValidate[7. Real-time Client-Side Schema Validation]
    ClientValidate -- Invalid --> ShowInlineErrors[Display Localized Error Toasts]
    ClientValidate -- Valid --> Submit[8. Submit Encrypted Payload to Endpoint]
    Submit --> UpdateState[9. Update Completion Status & Refresh Active Agent Scope]
```

### 4.1 Strict Frontend Performance & Ergonomics (React Best Practices)
1. **Zero-Waterfall Form Fetching:** Schemas and existing tenant values are retrieved in a single batched API call (`GET /api/v1/ui-schemas/{interface_key}/configuration`).
2. **Secret Input Masking:** Secret fields (API keys, webhook tokens) render with `******` placeholders if already configured. New values are sent directly over HTTPS; the client never receives the unmasked plaintext secret back from the server.
3. **RTL Arabic First:** All form labels, placeholders, validation warnings, and directionalities dynamically adapt to Arabic (`dir="rtl"`) with native typography.

---

## 5. Security & Isolation Boundaries for Generated Interfaces

1. **Strict Ownership Scope Enforcement:**
   - **`ADMIN` Interfaces:** Only accessible to authenticated platform administrators with the `SUPERADMIN` role via `apps/admin-dashboard`. Attempting to load an admin schema from the tenant dashboard yields an immediate `403 Forbidden`.
   - **`TENANT` Interfaces:** Explicitly bound to `scope.tenant_id`. A tenant administrator cannot query, inspect, or modify another tenant's dynamic form configurations.
2. **Payload Sanitization & Server-Side Contract Re-Verification:**
   - The server **NEVER** trusts client-side validation. When a dynamic form is submitted, the payload is re-validated against the server-side Pydantic schema with `extra="forbid"`.
   - Any injected attributes or unexpected fields cause an immediate transaction abort with `422 Unprocessable Entity`.
3. **Audit Trail Logging:**
   - Every modification to a configuration interface records a tamper-evident audit event: who modified what field, timestamp, IP address, and payload digest (with secrets cryptographically redacted).
