# AI-Employee-Platform — 15 Master Architectural System Maps

**Document ID:** `ARCHITECTURE_VISUAL_MAPS`  
**Governing Standard:** Section 11 (Required Architecture Maps Protocol)  
**System Designation:** AI Employee Platform (Enterprise Digital Employee Operating System)  
**Target Repository:** `QQYC9/ai-employee-platform`  
**Status:** **ACTIVE & AUDITED**  
**Date:** 2026-11-04  
**Master Architect:** AI-Employee-Platform Core Architecture Group  

---

## 1. Whole-Platform Subsystem Map

```mermaid
flowchart TD
    subgraph ClientChannels["Omni-Channel Client Ingress"]
        TG["Telegram Bot API"]
        WA["WhatsApp Cloud API"]
        WH["Custom Inbound Webhooks"]
        EM["Email / SMTP Ingress"]
    end

    subgraph EdgeIngress["Reverse Proxy & Edge Ingress"]
        CAD["Caddy 2 Proxy (SSL Termination)"]
        RT["Rate Limiter & Request Deduplicator"]
    end

    subgraph APIGateway["FastAPI Core Application Tier"]
        AUTH["Auth & JWT Scope Injector"]
        ROUT["API Routers (/api/v1)"]
        UI_REG["Declarative UI Schema Compiler"]
    end

    subgraph CoreEngine["Pregel Execution Engine Runtime"]
        DISP["Turn Dispatcher & Task Claimer"]
        GRAPH["Pregel StateGraph Turn Loop"]
        HANDOFF["Handoff Router (input_filter)"]
        TOOL_EXEC["Tool Sandbox Executor"]
        CHECK["Superstep Checkpointer"]
    end

    subgraph CapabilityEvolution["Autonomous Self-Development"]
        DREAM["Offline Dream Daemon (Idle Cycles)"]
        GATE["Memento 6-Gate Verification Pipeline"]
        UV_SANDBOX["UV Virtualenv Isolated Sandbox"]
        CATALOG["Global Capability Catalog"]
    end

    subgraph SupervisoryTier["Central Supervisory Guardian"]
        GODFATHER["The Godfather (الأب الروحي)"]
        TELEMETRY["Central Anomaly & Audit Consumer"]
        FOUNDER_TG["Founder Telegram Dedicated Channel"]
    end

    subgraph StorageTier["State & Data Persistence Layer"]
        PG[("PostgreSQL 17 + pgvector")]
        REDIS[("Redis 7 (Tokens & Queues)")]
        WORM[("External WORM Storage (HMAC Anchors)")]
    end

    subgraph AsyncOutboxTier["Async Outbox & Workers"]
        OUTBOX["Transactional Outbox (SKIP LOCKED)"]
        WORKER["OutboxWorker Dispatcher"]
        WAIT["n8n-style WaitTracker (Approval Resume)"]
    end

    ClientChannels --> CAD
    CAD --> RT
    RT --> APIGateway
    AUTH --> ROUT
    ROUT --> DISP
    DISP --> GRAPH
    GRAPH --> HANDOFF
    GRAPH --> TOOL_EXEC
    GRAPH --> CHECK
    CHECK --> PG
    TOOL_EXEC --> DREAM
    DREAM --> GATE
    GATE --> UV_SANDBOX
    UV_SANDBOX --> CATALOG
    GRAPH --> OUTBOX
    OUTBOX --> WORKER
    WORKER --> ClientChannels
    WORKER --> WAIT
    PG --> TELEMETRY
    TELEMETRY --> GODFATHER
    GODFATHER --> FOUNDER_TG
    REDIS --> DISP
    PG --> WORM
```

---

## 2. Agent Generation Lifecycle

```mermaid
stateDiagram-v2
    [*] --> BusinessRequirementIngress: Tenant Profile & Goals Provided
    BusinessRequirementIngress --> RoleAndResponsibilityInference: LLM Semantic Domain Analyzer
    RoleAndResponsibilityInference --> CapabilityGapAnalysis: Match against Global Catalog
    
    state CapabilityGapAnalysis {
        [*] --> CheckExistingCatalog
        CheckExistingCatalog --> ReusableCapabilitiesFound: Catalog Match
        CheckExistingCatalog --> MissingCapabilitiesIdentified: Gaps Detected
        MissingCapabilitiesIdentified --> SynthesizeNewTools: Queue for Dream Daemon
        ReusableCapabilitiesFound --> CapabilityBinding
        SynthesizeNewTools --> CapabilityBinding: 6-Gate Passed
    }

    CapabilityGapAnalysis --> AutonomyTierAssignment: Level 1, 2, or 3
    AutonomyTierAssignment --> DeclarativeContractCompilation: Compile Agent Pydantic Spec
    DeclarativeContractCompilation --> DynamicUIProvisioning: Generate UI Config Schema
    DynamicUIProvisioning --> HumanOwnerReview: Tenant Dashboard Approval Modal
    HumanOwnerReview --> SandboxValidation: Owner Signs Configuration
    SandboxValidation --> ActiveProduction: Deployed to Tenant Execution Pool
    HumanOwnerReview --> Rejected: Owner Declines
    Rejected --> [*]
    ActiveProduction --> [*]
```

---

## 3. Capability Discovery and Generation Lifecycle

```mermaid
flowchart LR
    A["Agent Operational Failure / Gap"] --> B["Capability Need Detected"]
    B --> C{"Exists in Global Catalog?"}
    C -- "Yes" --> D["Bind Tool & Apply Tenant Permissions"]
    C -- "No" --> E["Queue for Offline Dream Daemon"]
    E --> F["Generate Python Pydantic Tool Contract"]
    F --> G["Gate 1: AST Structural Validator"]
    G --> H["Gate 2: Pydantic Extra=Forbid Schema"]
    H --> I["Gate 3: Security & Ban Scanner"]
    I --> J["Gate 4: UV Isolated Pytest Execution"]
    J --> K["Gate 5: Mock LLM Integration Run"]
    K --> L["Gate 6: Smoke Profiler & Latency Check"]
    L --> M{"All 6 Gates Passed?"}
    M -- "Yes" --> N["Register in Catalog & Await Owner Activation"]
    M -- "No" --> O["Quarantine, Record Failure & Alert Godfather"]
```

---

## 4. Self-Development and Approval Lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant Agent as Digital Employee
    participant Engine as Pregel Runtime
    participant Dream as Dream Daemon (Idle Cycles)
    participant SixGate as Memento 6-Gate Sandbox
    participant Owner as Business Owner (Tenant)
    participant Godfather as The Godfather (Founder)
    participant DB as PostgreSQL 17

    Agent->>Engine: Capability Missing (e.g. Tax Invoicing)
    Engine->>DB: Record Missing Capability Telemetry
    DB->>Dream: Ingest Telemetry during low-traffic window
    Dream->>Dream: Synthesize Pydantic Tool & Schema
    Dream->>SixGate: Execute 6-Gate Isolated Verification
    SixGate-->>Dream: All 6 Gates Passed (Unit & Mock Tests Green)
    Dream->>DB: Store in Catalog (Status: PENDING_APPROVAL)
    Dream->>Godfather: Dispatch Diagnostic Report to Founder
    Dream->>Owner: Render Dynamic Approval Form in Tenant Portal
    Owner->>DB: Digitally Sign Approval (HMAC Token)
    DB->>Engine: Activate Tool for Tenant Agents
```

---

## 5. Godfather Observation and Escalation Architecture

```mermaid
flowchart TD
    subgraph DataProducers["Platform Data Producers"]
        AUDIT["HMAC-SHA256 Audit Log Events"]
        OUTBOX_FAIL["Outbox Dead-Letter Failures"]
        EXEC_ANOM["Pregel Task Zombie Leases & Fencing Violations"]
        TOOL_QUAR["6-Gate Capability Quarantine Alerts"]
        REG_REJECT["Regex & Semantic Tripwire Breaches"]
    end

    subgraph GodfatherCore["The Godfather Supervisory Subsystem"]
        INGEST["Central Telemetry Ingestion Queue"]
        CORRELATE["Root Cause Cross-Correlator"]
        CLASSIFY{"Severity Classifier"}
        EMERGENCY["Instant Emergency Alert Builder"]
        DIGEST["21:00 Evening Health Digest Compiler"]
        ADVISORY["Architectural Improvement Advisor"]
    end

    subgraph FounderChannel["Exclusive Founder Communication"]
        TG_BOT["Dedicated Telegram Bot (Direct to Founder)"]
        TG_CALLBACK["Inline Keyboard Authorization Callbacks"]
    end

    DataProducers --> INGEST
    INGEST --> CORRELATE
    CORRELATE --> CLASSIFY
    CLASSIFY -- "P0 Critical Anomaly" --> EMERGENCY
    CLASSIFY -- "P1 / P2 Degraded" --> DIGEST
    CLASSIFY -- "Optimization Proposal" --> ADVISORY
    EMERGENCY --> TG_BOT
    DIGEST --> TG_BOT
    ADVISORY --> TG_BOT
    TG_BOT --> TG_CALLBACK
    TG_CALLBACK --> IngestAction["Execute Signed System Command"]
```

---

## 6. End-to-End Incoming Message Execution Path

```mermaid
sequenceDiagram
    autonumber
    participant User as Customer (Telegram/WhatsApp)
    participant Caddy as Caddy 2 Reverse Proxy
    participant Gateway as FastAPI Ingestion Router
    participant DB as PostgreSQL 17
    participant Redis as Redis 7 (CFS Scheduler)
    participant Engine as Pregel StateGraph Worker
    participant Outbox as OutboxWorker

    User->>Caddy: Inbound Message Webhook
    Caddy->>Gateway: Forward with Client IP & Headers
    Gateway->>DB: Ingest Message & Create Execution Task (Idempotent UUIDv7)
    Gateway->>Redis: Enqueue Task ID to tenant_interactive_queue
    Gateway-->>Caddy: 200 OK (Instant Acknowledgement)
    Redis->>Engine: Dequeue Task
    Engine->>DB: BEGIN Transaction -> UPDATE execution_tasks SET fence_token = fence_token + 1 FOR UPDATE SKIP LOCKED
    Engine->>DB: Load 5-Tier Memory & Working Buffer
    Engine->>DB: COMMIT & Release Connection (Connection Pool Preservation)
    Engine->>Engine: Execute LLM Streaming & Supersteps
    Engine->>DB: BEGIN Transaction -> Persist Checkpoint & OutboxEvent
    Engine->>DB: COMMIT
    Outbox->>DB: Claim OutboxEvent (FOR UPDATE SKIP LOCKED)
    Outbox->>User: Dispatch Normalized Outbound Response
```

---

## 7. Tool Execution and Permission Path

```mermaid
flowchart TD
    A["Agent Evaluates Superstep"] --> B{"Requires Tool Call?"}
    B -- "No" --> C["Generate Direct Turn Response"]
    B -- "Yes" --> D["Check Agent Tool Permissions (RBAC Scope)"]
    D --> E{"Tool Bound to Agent?"}
    E -- "No" --> F["Raise PermissionDeniedError & Record Audit"]
    E -- "Yes" --> G{"Autonomy Level of Tool?"}
    G -- "Level 1: Read-Only Assistant" --> H["Execute Tool Immediately"]
    G -- "Level 2: Approval Gated" --> I["Create Signed ApprovalRequest & Suspend Execution"]
    G -- "Level 3: Autonomous Within Bounds" --> J{"Parameters within Bounds?"}
    J -- "Yes" --> H
    J -- "No" --> I
    H --> K["Execute in UV Subprocess Sandbox"]
    K --> L["Sanitize Output & Strip Secrets"]
    L --> M["Return ToolResult to Pregel StateGraph"]
    I --> N["Wait for Owner Webhook / Callback"]
```

---

## 8. Human Approval and Wait/Resume Path

```mermaid
sequenceDiagram
    autonumber
    participant Engine as Pregel Runtime
    participant DB as PostgreSQL 17
    participant Owner as Business Owner (Tenant)
    participant WaitTracker as n8n-Style WaitTracker
    participant Worker as Execution Worker

    Engine->>DB: Level 2 Tool Call Detected
    Engine->>DB: Generate RFC 8785 Canonical JSON Digest
    Engine->>DB: Insert into approval_requests (Status: SUSPENDED)
    Engine->>DB: Save Execution State Checkpoint
    Engine->>Owner: Dispatch Approval Request (Telegram / Dashboard Notification)
    Engine-->>WaitTracker: Register Suspension Key (Wait on Webhook)
    Note over Engine,WaitTracker: Worker Thread is 100% Freed (No Memory Pinned)
    Owner->>DB: Click "Approve" (POST /api/v1/approvals/resolve)
    DB->>DB: Validate HMAC Signature & Transition Status: APPROVED
    DB->>WaitTracker: Emit Resume Signal (Webhook Trigger)
    WaitTracker->>Worker: Enqueue Resumption Task
    Worker->>DB: Load Checkpoint & Inject Approved Tool Result
    Worker->>Worker: Resume Pregel StateGraph from Next Superstep
```

---

## 9. Tenant Configuration and Dynamic UI Path

```mermaid
flowchart LR
    subgraph BackendRegistration["Backend Capabilities"]
        TOOL["Newly Generated Tool / Module"]
        PYDANTIC["Pydantic v2 UI Model Declaration"]
        SCHEMA_COMP["Declarative UI Schema Compiler"]
    end

    subgraph APITier["REST Schema Serving"]
        ENDPOINT["GET /api/v1/ui-schemas/:module_id"]
        ACL["Role-Based Access Guard (Admin vs Tenant)"]
    end

    subgraph FrontendRendering["React 18 Dynamic Render Tier"]
        RENDERER["DynamicFormRenderer.tsx"]
        VALIDATOR["Client-Side Zod / JSONSchema Validator"]
        SECRET_MASK["SecretStr Masking (******)"]
        RTL_ARABIC["Tailwind RTL Arabic Ergonomics"]
    end

    subgraph UserAction["Tenant Business Owner"]
        FORM["Interactive Configuration Form"]
        SUBMIT["Submit Signed Configuration"]
    end

    TOOL --> PYDANTIC
    PYDANTIC --> SCHEMA_COMP
    SCHEMA_COMP --> ENDPOINT
    ENDPOINT --> ACL
    ACL --> RENDERER
    RENDERER --> VALIDATOR
    RENDERER --> SECRET_MASK
    RENDERER --> RTL_ARABIC
    RTL_ARABIC --> FORM
    FORM --> SUBMIT
    SUBMIT --> BackendRegistration
```

---

## 10. Knowledge and Memory Lifecycle

```mermaid
stateDiagram-v2
    [*] --> InboundFact: Customer Statement / Owner Configuration
    InboundFact --> ScopedExtraction: Extract Subject, Predicate, Object
    
    state ScopedExtraction {
        [*] --> DimensionTagging: Spatial, Temporal, Audience Scopes
        DimensionTagging --> SemanticEmbedding: text-embedding-3-small (1536d)
    }

    ScopedExtraction --> ConflictDetector: Query Existing Facts in pgvector
    ConflictDetector --> NoConflict: No Overlap Detected
    ConflictDetector --> SupersedesExisting: Newer Explicit Fact from Owner
    ConflictDetector --> ContradictionFound: Irreconcilable Contradiction

    NoConflict --> PersistFact: Status: ACTIVE
    SupersedesExisting --> ArchiveOldFact: Old Status: SUPERSEDED
    ArchiveOldFact --> PersistFact
    ContradictionFound --> EscalateToOwner: Generate Clarification Task
    EscalateToOwner --> PersistFact: Owner Resolves
    
    PersistFact --> FactStorage: Insert into tenant_facts
    FactStorage --> ExpirationSweep: TTL & Periodic Freshness Audit
    ExpirationSweep --> [*]: Fact Expired / Erased (GDPR/PDPL)
```

---

## 11. Database and Domain Ownership Map

```mermaid
erDiagram
    TENANTS ||--o{ CHANNELS : owns
    TENANTS ||--o{ AGENTS : configures
    TENANTS ||--o{ CUSTOMERS : records
    TENANTS ||--o{ BUSINESS_ENTITIES : maintains
    TENANTS ||--o{ AUDIT_LOGS : isolates

    AGENTS ||--o{ EXECUTION_TASKS : executes
    EXECUTION_TASKS ||--o{ EXECUTION_CHECKPOINTS : records
    EXECUTION_TASKS ||--o{ APPROVAL_REQUESTS : triggers
    EXECUTION_TASKS ||--o{ OUTBOX_EVENTS : emits

    CUSTOMERS ||--o{ CONVERSATIONS : participates
    CONVERSATIONS ||--o{ MESSAGES : contains
    CHANNELS ||--o{ CONVERSATIONS : routes

    TENANTS {
        uuid id PK
        string name
        string plan
        jsonb security_config
        timestamp created_at
    }

    AGENTS {
        uuid id PK
        uuid tenant_id FK
        string name
        string role
        int autonomy_level
        jsonb tool_registry
    }

    EXECUTION_TASKS {
        uuid id PK
        uuid tenant_id FK
        uuid agent_id FK
        int fence_token
        string status
        timestamp locked_until
    }

    BUSINESS_ENTITIES {
        uuid id PK
        uuid tenant_id FK
        string entity_type
        decimal balance_due
        jsonb dynamic_attributes
    }

    AUDIT_LOGS {
        uuid id PK
        uuid tenant_id FK
        string previous_hash
        string entry_hash
        jsonb payload
    }
```

---

## 12. Cross-Agent Handoff and Workflow Map

```mermaid
sequenceDiagram
    autonumber
    participant Customer as Customer
    participant Triage as Triage Agent (Frontline)
    participant Router as Pregel Handoff Router
    participant Sales as Sales Specialist Agent
    participant Ops as Operations Agent

    Customer->>Triage: "I want to purchase 50 units and schedule delivery"
    Triage->>Triage: Classify Intent: Commercial Inquiry
    Triage->>Router: Handoff(target="sales_agent", input_filter=sanitized_intent)
    Note over Router: Enforce MAX_HANDOFF_HOPS = 5 & Strip Raw History
    Router->>Sales: Activate Sales Agent with Filtered Context
    Sales->>Sales: Check Inventory Tool & Calculate Price
    Sales->>Customer: "50 units reserved. Would you like standard or express dispatch?"
    Customer->>Sales: "Express dispatch to Riyadh warehouse"
    Sales->>Router: Handoff(target="operations_agent", input_filter=delivery_spec)
    Router->>Ops: Activate Operations Agent
    Ops->>Ops: Create Dispatch Record & Confirm to Customer
```

---

## 13. Deployment and Operational Topology

```mermaid
flowchart TD
    subgraph PublicInternet["Public Internet"]
        WEB_TRAFFIC["Web Traffic (HTTPS :443)"]
        WEBHOOK_TRAFFIC["Channel Webhooks (:443)"]
    end

    subgraph CaddyLayer["Ingress & Edge Security Tier"]
        CADDY["Caddy 2 Proxy (Auto Let's Encrypt SSL)"]
    end

    subgraph ApplicationCluster["Docker Compose Application Cluster"]
        API_SERVER["apps/agent (FastAPI ASGI :8000)"]
        OUTBOX_WORKER["packages/services/outbox_worker.py"]
        DREAM_DAEMON["packages/self_development/dream_daemon.py"]
        GODFATHER_DAEMON["packages/godfather/guardian_daemon.py"]
        TENANT_UI["apps/tenant-dashboard (Nginx / Static :3000)"]
        ADMIN_UI["apps/admin-dashboard (Nginx / Static :3001)"]
    end

    subgraph InfrastructureTier["Stateful Infrastructure Services"]
        POSTGRES["PostgreSQL 17 + pgvector (:5433)"]
        REDIS["Redis 7 (In-Memory Scheduler :6379)"]
        BACKUP["Automated Hourly pg_dump & HMAC Anchor"]
    end

    subgraph ExternalServices["External Cloud APIs"]
        TELEGRAM_API["Telegram Bot API"]
        META_GRAPH["Meta WhatsApp Cloud API"]
        LLM_GATEWAY["OpenRouter / Gemini Pro / Groq"]
    end

    PublicInternet --> CADDY
    CADDY --> API_SERVER
    CADDY --> TENANT_UI
    CADDY --> ADMIN_UI
    API_SERVER --> POSTGRES
    API_SERVER --> REDIS
    OUTBOX_WORKER --> POSTGRES
    OUTBOX_WORKER --> REDIS
    DREAM_DAEMON --> POSTGRES
    GODFATHER_DAEMON --> POSTGRES
    OUTBOX_WORKER --> ExternalServices
    API_SERVER --> ExternalServices
    POSTGRES --> BACKUP
```

---

## 14. Failure and Recovery Paths

```mermaid
flowchart TD
    A["Inbound Message / Task Failure"] --> B{"Failure Classification"}
    
    B -- "Transient Network Glitch" --> C["Exponential Backoff Retry (Max 5 attempts)"]
    C --> D{"Retry Successful?"}
    D -- "Yes" --> E["Complete Task & Mark Outbox DELIVERED"]
    D -- "No" --> F["Move to Dead-Letter Queue (DLQ)"]

    B -- "Worker Crash / Zombie Timeout" --> G["PostgreSQL Lease Expires (locked_until < NOW())"]
    G --> H["Clean Worker Claims Task with fence_token = fence_token + 1"]
    H --> I["Load Superstep Checkpoint & Resume Execution"]

    B -- "External LLM Rate Limit (429)" --> J["Trigger ResilientProvider Failover Chain"]
    J --> K["Switch to Gemini Pro / Secondary OpenRouter Model"]
    K --> L["Resume Superstep without User-Facing Error"]

    B -- "Tool Code Exception" --> M["Contain in UV Sandbox & Record ToolError"]
    M --> N["Agent Synthesizes Graceful Degradation Response"]

    F --> O["Alert The Godfather via Founder Telegram Bot"]
    N --> O
```

---

## 15. Major Subsystem Dependencies

```mermaid
flowchart TD
    CORE["packages/core (Config, DB, AES-256 Crypto)"]
    MODELS["packages/models (SQLAlchemy Domain & Tenant Entities)"]
    AUTH["packages/auth (JWT, Immutable Scope, RBAC)"]
    CONNECTORS["packages/connectors (Telegram, WhatsApp, Webhooks)"]
    ENGINE["packages/engine (Pregel StateGraph, Turn Execution)"]
    OUTBOX["packages/services/outbox_worker (Async Delivery)"]
    KNOWLEDGE["packages/memory & context (5-Tier Fact Engine)"]
    SELF_DEV["packages/self_development (Dream Daemon, 6-Gate Sandbox)"]
    UI_ENGINE["packages/ui_engine (Declarative Schema Compiler)"]
    GODFATHER["packages/godfather (Founder Telemetry Guardian)"]
    DASHBOARDS["apps/*-dashboard (Tenant & Admin Portals)"]

    MODELS --> CORE
    AUTH --> CORE
    CONNECTORS --> CORE
    CONNECTORS --> MODELS
    ENGINE --> CORE
    ENGINE --> MODELS
    ENGINE --> AUTH
    ENGINE --> KNOWLEDGE
    OUTBOX --> MODELS
    OUTBOX --> CONNECTORS
    SELF_DEV --> ENGINE
    SELF_DEV --> MODELS
    UI_ENGINE --> MODELS
    DASHBOARDS --> UI_ENGINE
    DASHBOARDS --> AUTH
    GODFATHER --> CORE
    GODFATHER --> MODELS
```
