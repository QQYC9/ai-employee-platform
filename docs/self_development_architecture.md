# Self-Development Engine & Dynamic Capabilities Architecture (Phase 17)

## 1. Overview & Architectural Goals

Phase 17 implements the **Self-Development Engine & Dynamic Capabilities** subsystem for the AI Employee Platform. It empowers autonomous AI employees to identify functional gaps during operational workflows, synthesize rigorous capability specifications, implement and verify code in a contained sandbox, submit changes through a risk-governed approval pipeline, dynamically bind new capabilities into the tool runtime, and feed operational failure metrics into continuous improvement loops.

### Key Architectural Tenets
1. **Safety First & Defense-in-Depth**: Dynamic code generation is strictly quarantined. Dynamic code never executes with direct access to host process memory, host network sockets, or host platform secrets.
2. **Deterministic Specification Before Code**: AI employees cannot author implementation code until a structured specification (`CapabilitySpecification`) with input/output schemas, execution limits, and acceptance tests has been validated and risk-classified.
3. **Multi-Tenant Isolation**: Every development request, version, run, and registered dynamic tool is strictly scoped to a single `tenant_id`. Cross-tenant capability leakage or execution is strictly prohibited.
4. **Policy-Enforced Human Approval**: Capabilities classified as medium or high risk (or requiring sensitive permissions/secrets) strictly require human administrator review. Agents are cryptographically and logically prohibited from approving their own development requests.
5. **Zero Downtime Activation & Safe Rollback**: Dynamic capabilities bind directly to `ToolRegistry` via `DynamicCapabilityTool` without requiring server restarts. Any version can be instantly rolled back or disabled while preserving complete audit history.
6. **Continuous Improvement Without Autonomous Chaos**: Operational failures and recurring capability gaps are aggregated into structured diagnostic reports. The platform recommends improvements to tenant and platform operators, but never auto-mutates production without approval.

---

## 2. Self-Development Lifecycle State Machine

```
      ┌──────────────────────────────────────────────────────────┐
      │ 1. Need Discovery (Agent / Task / Operational Gap)       │
      └────────────────────────────┬─────────────────────────────┘
                                   │
                                   ▼
      ┌──────────────────────────────────────────────────────────┐
      │ 2. Duplicate Check (Existing Tools / Active Capabilities)│
      └───────┬──────────────────────────────────────────┬───────┘
              │ [Duplicate Found]                        │ [Unique Need]
              ▼                                          ▼
     [already_satisfied]               ┌─────────────────────────────────┐
                                       │ 3. Specification & Risk Class.  │
                                       └────────────────┬────────────────┘
                                                        │
                                                        ▼
                                       ┌─────────────────────────────────┐
                                       │ 4. AST Security & Secret Scan   │
                                       └───────┬─────────────────┬───────┘
                               [Violations]    │                 │ [Clean]
                                       ┌───────┘                 ▼
                                       ▼               ┌─────────────────┐
                                   [failed]            │ 5. Sandbox Test │
                                                       └───────┬─────────┘
                                               [Failed]│       │[All Passed]
                                               ┌───────┘       ▼
                                               ▼      ┌──────────────────┐
                                           [failed]   │ 6. Review Gate   │
                                                      └────────┬─────────┘
                                                [Rejected]     │ [Approved]
                                                       ┌───────┘ (Human Admin)
                                                       ▼       ▼
                                                  [rejected] ┌──────────────────┐
                                                             │ 7. Activation    │
                                                             │ (Dynamic Tool)   │
                                                             └────────┬─────────┘
                                                                      │
                                                       [Incident / Operator Action]
                                                                      ▼
                                                             ┌──────────────────┐
                                                             │ 8. Rollback / Off│
                                                             └──────────────────┘
```

---

## 3. Database Schema & Data Models

### 3.1 `development_requests`
Tracks functional gaps discovered by agents or users:
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id`, CASCADE)
- `agent_id` (UUID, FK -> `agents.id`, SET NULL)
- `request_type` (VARCHAR(100), default: `"capability"`)
- `title` (VARCHAR(500))
- `reason` (TEXT)
- `requirements` (JSONB)
- `expected_benefit` (TEXT)
- `requested_from` (VARCHAR(100), `"agent"` or `"user"`)
- `status` (VARCHAR(50): `"requested"`, `"already_satisfied"`, `"specified"`, `"in_progress"`, `"completed"`, `"rejected"`)
- `created_at`, `updated_at` (TIMESTAMPTZ)

### 3.2 `capability_versions`
Maintains immutable versioning for dynamic capability code and specifications:
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id`, CASCADE)
- `capability_id` (UUID, FK -> `capabilities.id`, CASCADE, nullable)
- `request_id` (UUID, FK -> `development_requests.id`, SET NULL, nullable)
- `version_number` (INT, default: 1)
- `slug` (VARCHAR(150), indexed)
- `name` (VARCHAR(255))
- `description` (TEXT)
- `specification` (JSONB)
- `implementation_code` (TEXT)
- `risk_level` (VARCHAR(50): `"low"`, `"medium"`, `"high"`)
- `status` (VARCHAR(50): `"draft"`, `"specified"`, `"developing"`, `"awaiting_approval"`, `"approved"`, `"active"`, `"disabled"`, `"rolled_back"`, `"rejected"`, `"failed"`)
- `approval_id` (UUID, FK -> `approvals.id`, SET NULL)
- `created_by_user_id` (UUID, FK -> `users.id`, SET NULL)
- `test_results` (JSONB)
- `activated_at`, `rolled_back_at` (TIMESTAMPTZ, nullable)
- `rollback_reason` (TEXT, nullable)
- `created_at`, `updated_at` (TIMESTAMPTZ)

### 3.3 `development_runs`
Captures test and security validation runs within the isolated sandbox:
- `id` (UUID, PK)
- `tenant_id` (UUID, FK -> `tenants.id`, CASCADE)
- `request_id` (UUID, FK -> `development_requests.id`, CASCADE, nullable)
- `capability_version_id` (UUID, FK -> `capability_versions.id`, CASCADE, nullable)
- `run_type` (VARCHAR(100), default: `"sandbox_test"`)
- `status` (VARCHAR(50): `"running"`, `"passed"`, `"failed"`, `"timed_out"`)
- `test_summary` (JSONB)
- `security_verdict` (JSONB)
- `logs` (TEXT)
- `error_message` (TEXT)
- `duration_ms` (INT)
- `created_at` (TIMESTAMPTZ)

---

## 4. Contained Execution Sandbox & Security Architecture

### 4.1 Process & Filesystem Isolation (`ExecutionSandbox`)
- **Disposable Working Directory**: Every execution runs inside a unique, temporary directory created with `tempfile.mkdtemp(prefix="sd_sandbox_")`.
- **Strict Cleanup**: The temporary directory is unconditionally deleted in a `finally` block using `shutil.rmtree(..., ignore_errors=True)`.
- **Environment Sanitization**: The child process runs with a whitelisted environment containing only essential OS runtime keys (`SYSTEMROOT`, `PATH`, `PYTHONPATH`, `TEMP`). Host platform secrets (`DATABASE_URL`, `JWT_SECRET_KEY`, `OPENAI_API_KEY`, cloud credentials) are completely stripped.
- **Output Masking**: Standard output and error streams pass through `MemorySanitizer.mask_secrets()` to ensure no host secrets or token fragments leak into logs or API responses.
- **Resource Constraints**:
  - `timeout_seconds`: Hard execution timeout enforced via `subprocess.run(timeout=...)`. Default: 10s, max: 30s.
  - `max_output_chars`: Output stream truncation (default: 20,000 characters) to prevent memory exhaustion attacks.

### 4.2 Static AST Verification (`CapabilitySecurityVerifier`)
Before executing any code in the sandbox, Python's `ast` module inspects the source code:
- **Forbidden Built-in Calls**: `eval`, `exec`, `compile`, `__import__`, `open` (raw filesystem access).
- **Forbidden Modules**: `ctypes`, `socket`, `pty`, `multiprocessing`, `threading`, `posix`, `nt`, `subprocess`, `sys`, `shutil`.
- **Dangerous Attributes**: `system`, `popen`, `spawn`, `kill`, `remove`, `rmdir`, `unlink`.
- **Secret Scanning**: Scanned via `MemorySanitizer.scan_for_secrets()`. Any embedded API keys, JWTs, or private keys immediately fail verification.

---

## 5. Risk-Based Approval & Self-Approval Prevention

### 5.1 Automated Risk Classification (`validate_and_classify_specification`)
The engine inspects capability specifications and escalates risk to `high` if:
- Required permissions or tools include administrative, shell, or file manipulation capabilities.
- The capability requests explicit external secrets (`secrets_required`).
- The capability description, name, or slug contains sensitive keywords (e.g., `transfer`, `financial`, `payment`, `delete`, `root`, `execute`, `credential`).

### 5.2 Approval Gates & RBAC Policy
- **Low Risk**: May be reviewed according to tenant policy.
- **Medium & High Risk**: Strictly require human tenant administrator or platform owner approval.
- **Self-Approval Bar**: If a development request originated from an agent (`request.agent_id`), the reviewing user cannot be that agent (`user.id != request.agent_id`). An agent attempting to approve its own capability is rejected with `HTTP 403 Forbidden`.

---

## 6. Dynamic Tool Registration (`DynamicCapabilityTool`)

Activated capability versions are dynamically registered in the runtime `ToolRegistry`:
- Inherits from `BaseRealTool`.
- Generates a valid `ToolContract` dynamically from the `CapabilitySpecification` schema.
- Executes capability entrypoint (`def run(inputs: dict) -> dict`) within the `ExecutionSandbox`.
- Tenant context is validated during execution: tools only execute within their provisioned `tenant_id`.

---

## 7. Version Rollback & Continuous Improvement

### 7.1 Disabling & Rollback
- Tenant administrators can disable an active capability version or rollback to any previously verified version number (`POST /api/v1/self-development/capabilities/{slug}/rollback`).
- Target versions must have passed sandbox verification tests.
- Full audit records (`AuditEvent`) are written to the database for every rollback and disable event.

### 7.2 Continuous Improvement Service (`ContinuousImprovementService`)
- Aggregates metrics from failed tasks (`Task.status == 'failed'`), failed sandbox development runs (`DevelopmentRun.status == 'failed'`), and recurring development requests.
- **Tenant Report**: Redacts cross-tenant metadata and presents localized actionable recommendations to optimize agent efficiency.
- **Platform Report**: Provides platform superadmins with multi-tenant aggregates, capability adoption rates, and systemic failure bottlenecks.

---

## 8. REST API Reference

| Method | Endpoint | Description | Role Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/self-development/requests` | Register development request (auto-duplicate check) | Authenticated User / Agent |
| `GET` | `/api/v1/self-development/requests` | List tenant development requests (paginated) | Authenticated User |
| `GET` | `/api/v1/self-development/requests/{id}` | Get development request details | Authenticated User |
| `POST` | `/api/v1/self-development/requests/{id}/spec` | Prepare and validate specification (evaluates risk) | Authenticated User |
| `POST` | `/api/v1/self-development/versions/{id}/develop`| Run AST verification and sandbox tests | Authenticated User |
| `GET` | `/api/v1/self-development/versions/{id}/runs` | List test and development runs for version | Authenticated User |
| `POST` | `/api/v1/self-development/versions/{id}/approve` | Approve or reject capability version | Tenant Admin / Platform Admin |
| `POST` | `/api/v1/self-development/versions/{id}/activate`| Activate approved version (bind to ToolRegistry) | Tenant Admin / Platform Admin |
| `POST` | `/api/v1/self-development/capabilities/{slug}/rollback` | Rollback to version or disable capability | Tenant Admin / Platform Admin |
| `GET` | `/api/v1/self-development/capabilities/{slug}/versions` | List all versions for a capability slug | Authenticated User |
| `GET` | `/api/v1/self-development/reports/continuous-improvement`| Continuous improvement report (tenant or platform) | Authenticated User (Platform Admin for platform_wide) |
