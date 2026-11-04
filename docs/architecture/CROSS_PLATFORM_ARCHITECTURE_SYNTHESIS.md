# Cross-Platform Architecture Synthesis — Master Subsystem Integration

**Document ID:** `CROSS_PLATFORM_ARCHITECTURE_SYNTHESIS`  
**Governing Standard:** Section 8 (Cross-Reference Synthesis Protocol)  
**System Designation:** AI Employee Platform (Enterprise Digital Employee Operating System)  
**Target Repository:** `QQYC9/ai-employee-platform`  
**Status:** **ACTIVE & AUDITED**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Executive Synthesis & Architectural Coherence

The ultimate objective of this architecture mission is not to present isolated summaries of external codebases, but to synthesize their verified mechanisms into a unified, resilient, multi-tenant digital employee platform.

This document establishes the authoritative cross-reference matrices connecting the 7 reference platforms to our platform subsystems, followed by the 12 comprehensive lifecycle matrices governing every operational state from ingress to long-term evolution.

---

## 2. Master Platform Subsystem Cross-Reference Matrix

| Platform Subsystem | Relevant References | Extracted Concepts | Verified Source Evidence | Target Design Implication | Boundaries & Limitations |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Execution Runtime & State Engine** | LangGraph, Dify | Pregel state graphs, superstep checkpoints, connection pool release. | `langgraph/pregel/`, `dify/api/core/agent/fc_agent_runner.py` | StateGraph turn loop bounded by `MAX_SUPERSTEPS=10`. DB session closed prior to LLM streaming. | Dify code cannot be imported (Clause 1.a); implemented natively in clean Python 3.14. |
| **Autonomous Capability & Tool Synthesis** | Memento-Skills | 6-Gate verification engine, UV isolated virtualenv sandboxing, Dream Daemon. | `memento-skills/core/skill/evolution/engine.py` | Tools synthesized offline in idle cycles; verified through AST, Pydantic, Security, and Unit test gates. | Dream Daemon must not run in the interactive request path. High CPU/RAM during test synthesis. |
| **Multi-Agent Coordination & Handoffs** | OpenAI Agents SDK, Microsoft Agent Framework | Declarative `Handoff`, `input_filter` context sanitization, UTF-16 code units. | `openai-agents-python/src/agents/handoffs/`, Microsoft Agent Framework connectors. | Frontline Triage agent handoffs with context pruning; Telegram chunks measured in UTF-16 code units. | Max 5 handoff hops (`config.MAX_HANDOFF_HOPS=5`) to prevent cyclic loops. |
| **Human-in-the-Loop Approvals** | n8n, RagLeap Core | `WaitTracker` execution suspension, webhook resumption, canonical JSON signatures. | `n8n` execution wait triggers, `ragleap-core/core/security/` | Level 2 tool execution suspends state to DB, frees worker thread, resumes upon signed owner webhook. | Requires external webhook or callback listener. Incomplete approvals expire after 72-hour TTL. |
| **Security, Tenancy & Audit Chaining** | RagLeap Core | Immutable `Scope` dataclass, leak-proof `SecretStr`, SHA-256 HMAC audit chaining. | `ragleap-core/core/security/scope.py`, `ragleap-core/core/security/audit.py` | Immutable Scope passed across all async worker threads. Append-only tamper-evident audit log. | HMAC secret keys must be isolated and rotated per tenant. |
| **Declarative UI & Dashboards** | Dify, React Hook Form | JSONSchema / Pydantic dynamic form schema generation. | `dify/web/app/components/base/form/`, Tenant Dashboard API client. | Shared `DynamicFormRenderer.tsx` renders dynamic forms in both Admin and Tenant Dashboards. | Zero-waterfall rendering; form state preserved across tab navigation. |
| **Supervisory Oversight (The Godfather)** | RagLeap Core, Platform Vision | Out-of-band audit consumer, root-cause anomaly detection, Telegram digest. | `docs/PROJECT_VISION.md` Sections 10–14. | Guardian daemon consumes telemetry asynchronously; sends instant P0 emergency alerts and 21:00 digest. | Strictly read-only for production code and live tenant state. Founder authorization required. |

---

## 3. The 12 Foundational Lifecycle Matrices

### 3.1 Agent Lifecycle Matrix
| Phase | Trigger | Owning Subsystem | Subsystem Dependencies | Shared Data | Isolated Data | Human Decision | Recovery Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Specification** | Tenant Onboarding / Need | Agent Provisioner | LLM Domain Analyzer | Tenant Profile | Other Tenant Profiles | Owner approves role | Rollback to draft |
| **2. Capability Binding**| Role Defined | Capability Registry | Catalog, RBAC | Tool Schemas | Secret API Keys | Owner assigns tools | Unbind missing tool |
| **3. Validation** | Binding Complete | Sandbox Validator | UV Virtualenv | Test Inputs | Production DB | Automated 6-Gate | Quarantine tool |
| **4. Deployment** | Validation Passed | Runtime Engine | Docker, Database | Agent Spec | Private Memory | Owner signs activation | Revert to previous rev |
| **5. Active Execution** | Inbound Message | Pregel StateGraph | Channels, Memory | Turn Context | Cross-Tenant State | Level 2 Approvals | Fallback degradation |
| **6. Retirement** | Owner Command | Agent Registry | Task Queue | Archival Record | Active Credentials | Owner confirms delete | Soft-delete / Archive |

---

### 3.2 Capability & Tool Lifecycle Matrix
| Phase | Trigger | Owning Subsystem | Subsystem Dependencies | Shared Data | Isolated Data | Human Decision | Recovery Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Gap Discovery** | Agent Execution Failure | Dream Daemon | Telemetry Logger | Error Trace | Tenant PII | None (Autonomous) | Log gap telemetry |
| **2. Synthesis** | Dream Daemon Sweep | Code Generator | LLM Code Model | Tool Contract | Host Environment | None (Offline) | Discard syntax errors |
| **3. 6-Gate Sandbox** | Code Synthesized | Memento 6-Gate | AST, UV Pytest | Test Fixtures | Production Storage | Automated AST scan | Quarantine to DLQ |
| **4. Owner Proposal** | 6 Gates Passed | UI Compiler | DynamicFormRenderer | Form Schema | Integration Secrets | Owner signs approval | Discard candidate |
| **5. Runtime Activation**| Owner Signature | Tool Registry | Runtime Engine | Active Spec | Internal State | Owner can disable | Rollback to v(n-1) |

---

### 3.3 Workflow & Turn Execution Lifecycle Matrix
| Phase | Trigger | Owning Subsystem | Subsystem Dependencies | Shared Data | Isolated Data | Human Decision | Recovery Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Ingress** | Webhook Received | FastAPI Router | Caddy 2, Dedup | Payload Hash | Tenant Secret Key | None (Automated) | 400 Bad Request |
| **2. Task Claim** | Worker Available | Turn Dispatcher | PostgreSQL MVCC | Fencing Token | Other Worker State | None (Automated) | SKIP LOCKED retry |
| **3. Superstep Loop** | Task Claimed | Pregel StateGraph | AI Providers | Channel State | DB Connection Pool | Level 2 Interruption | Graceful Degradation |
| **4. Checkpoint** | Superstep End | BaseCheckpointSaver | PostgreSQL 17 | Checkpoint State| Ephemeral Memory | None (Automated) | Rollback to Superstep |
| **5. Outbox Dispatch** | Turn Complete | OutboxWorker | Omni-Connectors | Outbox Payload | Delivery Secrets | None (Automated) | 4-Tier Idempotency |

---

### 3.4 Knowledge & Memory Lifecycle Matrix
| Phase | Trigger | Owning Subsystem | Subsystem Dependencies | Shared Data | Isolated Data | Human Decision | Recovery Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Extraction** | Inbound Fact | FactService | Scoped Fact Analyzer | Fact Text | Non-Tenant Context | None (Automated) | Skip noisy input |
| **2. Vector Embedding** | Fact Scoped | Embedding Pipeline | `text-embedding-3` | 1536d Vector | Other Tenant Vectors| None (Automated) | Retry embedding API |
| **3. Conflict Check** | Vector Indexed | Conflict Resolver | pgvector HNSW | Overlap Score | Private Annotations | Owner Resolves | Flag Contradiction |
| **4. Supersession** | Explicit Update | FactService | PostgreSQL MVCC | Status: ACTIVE | Old Status: ARCHIVED| Owner Confirms | Revert Supersession |
| **5. Erasure** | Tenant Offboarding | Data Lifecycle Mgr | Audit Logger | Erasure Cert | Erased Vectors | Tenant Admin Request | Cryptographic Wipe |

---

### 3.5 Human Configuration & UI Lifecycle Matrix
| Phase | Trigger | Owning Subsystem | Subsystem Dependencies | Shared Data | Isolated Data | Human Decision | Recovery Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Schema Export** | Tool Registered | UI Schema Compiler | Pydantic Models | Form Definition | Backend Logic | None (Automated) | Fallback to Default |
| **2. Schema Serving** | Dashboard Request | REST API Router | Auth & Scope Guard | Schema JSON | Integration Secrets | None (Automated) | 403 Forbidden |
| **3. Dynamic Render** | Schema Loaded | DynamicFormRenderer | React 18, Tailwind | Form Fields | Uncommitted State | User Edits Fields | Reset Form |
| **4. Client Validate** | Form Submit | Client Validator | Zod / JSONSchema | Clean Payload | Validation Errors | User Corrects | Highlight Field Error |
| **5. Persistence** | Form Verified | BaseRepository | AES-256 Crypto | Plain Attributes | Encrypted Secrets | None (Automated) | Transaction Rollback |

---

### 3.6 Approval & Wait/Resume Lifecycle Matrix
| Phase | Trigger | Owning Subsystem | Subsystem Dependencies | Shared Data | Isolated Data | Human Decision | Recovery Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Interruption** | Level 2 Tool Call | Pregel StateGraph | Tool Registry | Action Spec | Execution State | None (System Gate) | Abort Tool Call |
| **2. JCS Hashing** | Action Suspended | Approval Subsystem | RFC 8785 Canonical | Canonical Digest | Signing Key | None (Automated) | Re-hash Payload |
| **3. Suspension** | Digest Generated | n8n WaitTracker | PostgreSQL DB | Suspension Key | Worker Thread Memory| None (Thread Freed) | Auto-expire after TTL |
| **4. Resolution** | Owner Clicks Action | Webhook Receiver | Auth & HMAC Guard | Status: RESOLVED | Rejection Reason | Owner Approves/Rejects | Reject cancels turn |
| **5. Resumption** | Status Approved | Pregel Dispatcher | Checkpoint Saver | Injected Result | Previous State | None (Automated) | Resume from Checkpoint |

---

### 3.7 Platform Self-Development Lifecycle Matrix
| Phase | Trigger | Owning Subsystem | Subsystem Dependencies | Shared Data | Isolated Data | Human Decision | Recovery Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Gap Ingestion** | Multiple Failures | Telemetry Analyzer | Central Audit Queue | Aggregated Error | Tenant User Identity | None (Automated) | Log telemetry gap |
| **2. Dream Synthesis** | Low Traffic Window | Dream Daemon | LLM Code Model | Synthesized AST | Production Envs | None (Automated) | Discard code |
| **3. 6-Gate Test** | Code Synthesized | Memento Sandbox | UV, Pytest | Test Matrix | Production Storage | None (Automated) | Quarantine & Alert |
| **4. Founder Review** | Gates Passed | The Godfather | Founder Telegram Bot | Improvement Spec | Production DB | Founder Approves | Reject Proposal |
| **5. Safe Rollout** | Founder Approved | Deployment Engine | Docker, Catalog | Versioned Tool | Old Version State | Founder Signoff | One-click Rollback |

---

### 3.8 The Godfather Observation & Authority Matrix
| Phase | Trigger | Owning Subsystem | Subsystem Dependencies | Shared Data | Isolated Data | Human Decision | Recovery Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Telemetry Ingest**| Platform Event | Guardian Daemon | PostgreSQL / Redis | Event Metadata | Raw Tenant PII | None (Read-Only) | Buffer to Disk |
| **2. Anomaly Match** | Rule / Spike Hit | Root Cause Engine | Pattern Matcher | Correlated Error | Active State | None (Read-Only) | Suppress Duplicate |
| **3. P0 Paging** | Critical Anomaly | Emergency Notifier | Founder Telegram | Incident Details | System Core Secrets | Founder Investigates | Resend Alert |
| **4. Daily Digest** | 21:00 Wall Clock | Digest Compiler | Analytics Store | Executive Summary | Tenant Records | Founder Reviews | Regenerate Digest |
| **5. Command Exec** | Founder Callback | Command Executor | HMAC Signed Webhook| Command Token | Unauthorized Actions| Founder Signed Only | Command Rejection |

---

### 3.9 Tenant Lifecycle Matrix
| Phase | Trigger | Owning Subsystem | Subsystem Dependencies | Shared Data | Isolated Data | Human Decision | Recovery Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Provisioning** | Registration | Tenant Provisioner | Auth, Database | Tenant UUID | Other Tenant Data | Admin Approval | Abort Provisioning |
| **2. Channel Binding** | Integration Setup | Channel Connector | AES-256 Crypto | Channel Config | Integration Secrets | Owner Inputs Keys | Mask Secrets |
| **3. Active Ops** | Normal Traffic | Entire Platform | All Subsystems | Usage Metrics | Tenant Knowledge | Owner Configures | Rate Limiting |
| **4. Suspension** | Quota Exceeded | Governance Engine | CFS Redis Queue | Suspended Flag | Customer Messages | Admin Re-activates | Queue / Reject Turns |
| **5. Offboarding** | Contract End | Erasure Service | Database, S3/WORM | Erasure Audit Hash | Deleted DB Records | Owner Requests | Cryptographic Wipe |

---

### 3.10 Data & Entity Lifecycle Matrix
| Phase | Trigger | Owning Subsystem | Subsystem Dependencies | Shared Data | Isolated Data | Human Decision | Recovery Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Creation** | Business Action | Business Entity Svc | PostgreSQL 17 | Entity Record | Private Attributes | Owner Validates | Transaction Rollback |
| **2. Indexing** | Record Committed | GIN Indexer | pgvector, Postgres | GIN Search Token | Unindexed Data | None (Automated) | Rebuild GIN Index |
| **3. Mutation** | Update Requested | Entity Repository | Row-Level Lock | Updated Fields | Historical Rev | Owner Confirms | Read Committed Rollback |
| **4. Archival** | Status: INACTIVE | Retention Manager | Cold Storage | Archived Entity | Active Search Pool | None (Automated) | Restore from Archive |
| **5. Purge** | Retention Expired | Cleanup Worker | Audit Logger | Purge Audit Record | Erased Data | Compliance Policy | Permanent Deletion |

---

### 3.11 Operational Concurrency & Locking Lifecycle Matrix
| Phase | Trigger | Owning Subsystem | Subsystem Dependencies | Shared Data | Isolated Data | Human Decision | Recovery Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Claim Attempt** | Task Dequeued | Worker Instance | PostgreSQL MVCC | Task Record | Worker ID | None (Automated) | SKIP LOCKED |
| **2. Lease Granted** | Lock Acquired | Worker Instance | `locked_until` | Fence Token + 1 | Worker Context | None (Automated) | Wait on lock_timeout |
| **3. Heartbeat** | Long Execution | Lease Maintainer | Redis / Postgres | Lease Expiry + 30s | Worker Thread | None (Automated) | Worker Suicide |
| **4. Zombie Recovery** | Lease Expired | Watchdog Daemon | Watchdog Query | Fencing Token | Zombie State | None (Automated) | Monotonic Invalidation |
| **5. Commit Release** | Task Completed | Outbox Committer | Transaction Manager| DELIVERED State | Released Connection | None (Automated) | Transaction Retry |

---

### 3.12 Failure Recovery Lifecycle Matrix
| Phase | Trigger | Owning Subsystem | Subsystem Dependencies | Shared Data | Isolated Data | Human Decision | Recovery Path |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Detection** | Exception Raised | Runtime Supervisor | Sentry / Telemetry | Error Class | Customer PII | None (Automated) | Catch in Try/Except |
| **2. Classification** | Error Captured | Recovery Dispatcher| Error Registry | Transient vs Fatal | Execution Stack | None (Automated) | Classify Category |
| **3. Transient Retry** | Network Glitch | Exponential Backoff| Redis Retry Queue | Attempt Counter | Previous Payload | None (Automated) | Max 5 Attempts |
| **4. Circuit Breaker** | Provider 429/500 | ResilientProvider | AI Factory | Fallback Provider | Dead API Endpoint | None (Automated) | Failover to Gemini |
| **5. Dead-Letter** | Max Retries Hit | DLQ Manager | PostgreSQL / DLQ | Poison Payload | Active Queue | Godfather Notified | Manual Founder Action |
