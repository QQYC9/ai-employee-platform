# Primary Source Evidence Index: Verified File Paths & Line Locations

**Document ID:** `PRIMARY_SOURCE_EVIDENCE_INDEX`  
**Package:** Second-Order Review Evidence Package  
**Audit Baseline Commit:** `1b3eb775d0c963fc18d9004ea20a2dc1255d5e46`  
**Remote Base URL:** `https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/`

---

## 1. Primary Codebase Files Inspected

The following table lists every primary source code file inspected during the investigation, with exact line numbers and direct links to GitHub at the baseline commit:

| Component / Subsystem | Local Repository Path | Exact Line Numbers | Direct GitHub URL | Key Evidence Element |
| :--- | :--- | :---: | :--- | :--- |
| **FastAPI Ingress Gateway** | `apps/agent/main.py` | Lines 136–163 | [`apps/agent/main.py#L136-L163`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/apps/agent/main.py#L136-L163) | Router registration without tenant middleware. |
| **Tenant Context Definition** | `packages/tenants/context.py` | Lines 10–35 | [`packages/tenants/context.py#L10-L35`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/packages/tenants/context.py#L10-L35) | `get_current_tenant_id()` raises `RuntimeError`. |
| **Auth Tenant Dependency** | `packages/auth/context.py` | Lines 8–20 | [`packages/auth/context.py#L8-L20`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/packages/auth/context.py#L8-L20) | `get_tenant_context` wraps `tenant_context`. |
| **AES-256-GCM Encryption** | `packages/core/crypto.py` | Lines 44–46, 103–107, 136–140 | [`packages/core/crypto.py#L44-L140`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/packages/core/crypto.py#L44-L140) | Static `ASSOCIATED_DATA` byte string. |
| **Approval HMAC Service** | `packages/services/approval_service.py` | Lines 110–116 | [`packages/services/approval_service.py#L110-L116`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/packages/services/approval_service.py#L110-L116) | Hardcoded fallback HMAC secret key string. |
| **Outbox Claim Query** | `packages/services/outbox_service.py` | Lines 180–205 | [`packages/services/outbox_service.py#L180-L205`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/packages/services/outbox_service.py#L180-L205) | SQL `order_by(scheduled_at, created_at)` without tenant partitioning. |
| **Domain Models & Audit Schema**| `packages/models/domain.py` | Lines 635–665 | [`packages/models/domain.py#L635-L665`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/packages/models/domain.py#L635-L665) | `AuditEvent` table schema with unencrypted JSONB payload. |
| **Database Migrations** | `infrastructure/migrations/versions/` | All files | [`infrastructure/migrations/versions/`](https://github.com/QQYC9/ai-employee-platform/tree/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/infrastructure/migrations/versions) | Confirmed zero instances of `ROW LEVEL SECURITY`. |

---

## 2. Primary Documentation Files Inspected

| Document Title | Local Repository Path | Exact Section / Heading | Direct GitHub URL | Key Evidence Element |
| :--- | :--- | :---: | :--- | :--- |
| **Master Architecture Blueprint** | `docs/architecture/MASTER_ARCHITECTURE_BLUEPRINT.md` | §3.2, §5.3, §11.2, §12.2, ADR-05 | [`MASTER_ARCHITECTURE_BLUEPRINT.md`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/docs/architecture/MASTER_ARCHITECTURE_BLUEPRINT.md) | `input_filter: Callable`, missing `version_id`, `MAX_HANDOFF_HOPS=5`. |
| **Architectural Conflicts** | `docs/architecture/ARCHITECTURAL_CONFLICTS_AND_OPEN_QUESTIONS.md` | Conflict 4, Mitigations 1–5 | [`ARCHITECTURAL_CONFLICTS_AND_OPEN_QUESTIONS.md`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/docs/architecture/ARCHITECTURAL_CONFLICTS_AND_OPEN_QUESTIONS.md) | 60s WhatsApp re-dispatch, 5s Telegram window, `ef_search=100`, `version_id`. |
| **Research Evidence Gaps** | `docs/architecture/RESEARCH_EVIDENCE_GAPS.md` | Gap 1, Gap 2, Gap 4, Gap 6 | [`RESEARCH_EVIDENCE_GAPS.md`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/docs/architecture/RESEARCH_EVIDENCE_GAPS.md) | Composite HNSW proposal, WhatsApp 24h window inversion. |
| **Security & Multi-Tenancy** | `docs/architecture/SECURITY_AND_MULTI_TENANCY.md` | §1, §3, §3.1 | [`SECURITY_AND_MULTI_TENANCY.md`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/docs/architecture/SECURITY_AND_MULTI_TENANCY.md) | Claim of tenant-bound AAD, composite keys without RLS. |
| **Knowledge & Memory** | `docs/architecture/KNOWLEDGE_AND_MEMORY_ARCHITECTURE.md` | §1, §3.1, §4 | [`KNOWLEDGE_AND_MEMORY_ARCHITECTURE.md`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/docs/architecture/KNOWLEDGE_AND_MEMORY_ARCHITECTURE.md) | Omission of episodic memory, soft deletion `status = 'DELETED'`. |
| **Platform Self-Development** | `docs/architecture/PLATFORM_SELF_DEVELOPMENT_RESEARCH.md` | Section 2 (Table 2) | [`PLATFORM_SELF_DEVELOPMENT_RESEARCH.md`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/docs/architecture/PLATFORM_SELF_DEVELOPMENT_RESEARCH.md) | Table 2 line 27: Tier 3 Skill Synthesis marked "Automated". |
| **Project Master Vision** | `docs/PROJECT_VISION.md` | §1, §5, §6, §9, §10, §17 | [`docs/PROJECT_VISION.md`](https://github.com/QQYC9/ai-employee-platform/blob/1b3eb775d0c963fc18d9004ea20a2dc1255d5e46/docs/PROJECT_VISION.md) | Digital employee definition, approval invariant, Godfather role. |

---
*End of PRIMARY_SOURCE_EVIDENCE_INDEX.md.*
