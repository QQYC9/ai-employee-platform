# Open-Source Intelligence Deep Dive: 7 Reference Architectures

**Authoritative Technical Investigation — AI Employee Platform**  
**Working Directory**: `D:\AI-Employee-Platform-Research\`  
**Target Milestone**: Digital Employee Autonomous Evolution  

---

## 1. Memento-Skills (Qwen / Alibaba)

- **Repository Path**: `D:\AI-Employee-Platform-Research\memento-skills`
- **Git Commit**: `ee9b9a45efd093d669c06fe318b4b1dceb246d19`
- **License**: Apache-2.0
- **Architectural Focus**: Transactional Skill Evolution, Failure Attribution, Empirical Utility Tracking, Pre-Execution Hallucination Guard.

### 1.1 Core File & Class Architecture
| File Path | Primary Classes / Functions | Responsibility |
|---|---|---|
| `core/skill/evolution/engine.py` | `SkillEvolutionEngine`, `_AttributionPayload`, `_RewritePayload`, `_JudgePayload`, `EvolutionResult` | Transactional skill mutation, failure attribution, candidate generation, 3-gate verification, and atomic disk deployment. |
| `core/memento_s/skill_dispatch/hallucination_guard.py` | `HallucinationGuard` | Intercepts hallucinated tool calls from the LLM, resolves valid vs invalid skills, and computes fuzzy suggestions via `difflib.get_close_matches`. |
| `core/skill/execution/error_recovery.py` | `ErrorRecoveryHandler` | Categorizes runtime execution faults into recoverable vs fatal errors, triggers contextual retry or skill evolution. |
| `core/skill/execution/loop_detector.py` | `LoopDetector` | Prevents infinite tool execution cycles by hashing parameter sequences. |
| `shared/security/policy.py` | `SecurityPolicy` | Sandboxing restrictions, path boundaries, and disallowed shell operations. |

### 1.2 In-Depth Mechanism Analysis

#### 1. Failure Attribution Pipeline
When an agent task fails after executing one or more skills, `SkillEvolutionEngine.evolve_failure` isolates the fault:
```python
class _AttributionPayload(BaseModel):
    skill_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    failure_mode: str
    rationale: str
    evidence: list[str] = Field(default_factory=list)
```
The engine passes the complete execution trace, task objective, and list of executed skills to an LLM judge using `ATTRIBUTION_PROMPT`. The model attributes the root cause to a single responsible skill with confidence scoring and concrete evidence lines.

#### 2. Three-Gate Transactional Verification
Before any modified or newly evolved skill is deployed, Memento-Skills enforces three sequential verification gates:
1. **Structural Gate**: Static AST validation, checking function signatures, docstrings, schema compliance, and prohibited imports.
2. **Local Unit Tests**: Executes isolated unit tests bundled in `tests/` within an isolated temporary directory.
3. **Synthetic Execution Gate**: Generates a synthetic task request matching the edge case (`_SyntheticTest`) and evaluates the candidate output using an LLM judge (`_JudgePayload(passed: bool, score: float, rationale: str)`).

Only if all three gates pass is the candidate atomically deployed via directory replacement (`os.replace`). If any gate fails, the original skill folder remains completely untouched, and the failed candidate is retained in `.evolution/failed_candidates/` for offline inspection.

#### 3. Empirical Utility Scoring (`utility.json`)
Memento tracks real-world performance per skill:
```python
entry["utility"] = entry["success"] / total if total else 0.5
```
Skills with declining utility are dynamically deprioritized or queued for evolution, while protected core skills (`evolution_protected_skills`) are safeguarded against accidental mutation.

#### 4. Hallucination Interception
In `HallucinationGuard.intercept`, if the LLM attempts to call a non-existent skill:
```python
if tool_name not in installed_names:
    close = get_close_matches(tool_name, installed_names, n=3, cutoff=0.5)
    suggestion = f" Did you mean one of: {', '.join(close)}?" if close else " Use search_skill..."
    return json.dumps({
        "ok": False,
        "status": "failed",
        "error_code": "UNKNOWN_TOOL",
        "summary": f"'{tool_name}' is not a valid tool or installed skill.{suggestion}"
    })
```

---

## 2. LangGraph (LangChain)

- **Repository Path**: `D:\AI-Employee-Platform-Research\langgraph`
- **Git Commit**: `4c52e129eb1ab69a3da58b799f67929f77d81149` (Release 1.2.17)
- **License**: MIT
- **Architectural Focus**: Stateful Cyclic Multi-Agent Workflows, Durable Checkpointing (PostgreSQL), Human-in-the-Loop Interruptions, Deterministic Replay.

### 2.1 Core File & Class Architecture
| File Path | Primary Classes / Functions | Responsibility |
|---|---|---|
| `libs/langgraph/langgraph/graph/state.py` | `StateGraph`, `CompiledStateGraph` | Core cyclic graph definition, state channel schema, and node/edge registration. |
| `libs/langgraph/langgraph/types.py` | `interrupt()`, `Command`, `Interrupt` | Halts execution graph at any step; enables resumption via `Command(resume=...)`. |
| `libs/langgraph/langgraph/pregel/_checkpoint.py` | `BaseCheckpointSaver`, `Checkpoint` | Snapshotting channel values, versioning, and parent pointer lineage to durable storage. |
| `libs/checkpoint-postgres/` | `PostgresSaver`, `AsyncPostgresSaver` | Production PostgreSQL backend saving state blobs, writes, and metadata. |
| `libs/langgraph/langgraph/pregel/_loop.py` | `PregelLoop` | Deterministic superstep execution, channel resolution, parallel node triggers. |

### 2.2 In-Depth Mechanism Analysis

#### 1. The `interrupt()` and `Command(resume=...)` Primitives
LangGraph cleanly decouples execution suspension from application transport. When a node requires human approval:
```python
def ask_owner_node(state: AgentState):
    decision = interrupt({
        "question": "Do you approve sending outbound campaign to 500 customers?",
        "action": "send_campaign",
        "recipients_count": 500
    })
    return {"owner_approval": decision["approved"]}
```
- Calling `interrupt()` immediately suspends the Pregel execution loop.
- The complete graph state, channel values, and pending interrupt payloads are committed to PostgreSQL (`checkpoints` and `checkpoint_writes` tables) tied to `thread_id` and `checkpoint_id`.
- The HTTP worker terminates and yields control back to the client.

#### 2. Resumption Without Duplication
When the user responds hours or days later (e.g. from WhatsApp or the Tenant Dashboard):
```python
graph.invoke(Command(resume={"approved": True}), config={"configurable": {"thread_id": "thread_123"}})
```
- The checkpointer loads the exact checkpoint snapshot from PostgreSQL.
- Only the suspended node resumes from the point of `interrupt()`.
- Upstream nodes (which already executed database writes or API calls) are **never re-executed**, preventing duplicate side effects and redundant LLM billing.

#### 3. Schema-Validated Resume
As verified in `libs/langgraph/tests/test_interruption.py`, LangGraph validates the type and structure of the resumption payload against Pydantic models. Passing invalid payloads raises a `ValidationError` without modifying graph state.

---

## 3. OpenAI Agents SDK Python

- **Repository Path**: `D:\AI-Employee-Platform-Research\openai-agents-python`
- **Git Commit**: `0dc4cf152bff1f50bdc0e41f28808563406545b2`
- **License**: MIT
- **Architectural Focus**: Declarative Guardrails, Granular Tool Approvals, Agent Handoffs, Sandboxed Runtime Execution.

### 3.1 Core File & Class Architecture
| File Path | Primary Classes / Functions | Responsibility |
|---|---|---|
| `src/agents/agent.py` | `Agent` | Agent definition containing instructions, model settings, tools, handoffs, and guardrails. |
| `src/agents/util/_approvals.py` | `evaluate_function_tool_approval`, `FunctionToolApproval` | Dynamic policy evaluation determining if a tool call requires human confirmation before execution. |
| `src/agents/guardrail.py` | `InputGuardrail`, `OutputGuardrail` | Pre-execution sanitization and post-generation safety constraints. |
| `src/agents/run.py` | `Runner`, `RunContextWrapper` | Orchestrates the agent execution turn, streaming events, and tool invocations. |
| `tests/sandbox/` | `ExecutionSandbox`, `WorkspaceManager` | Local and Docker-based process sandboxing for code execution capabilities. |

### 3.2 In-Depth Mechanism Analysis

#### 1. Dynamic Tool Approval Policies
In `_approvals.py`, OpenAI Agents SDK provides a sophisticated policy evaluator:
```python
async def evaluate_function_tool_approval(
    function_tool: FunctionTool,
    context: RunContextWrapper[Any],
    arguments: str,
    call_id: str,
    *,
    strict: bool = True,
) -> FunctionToolApproval:
```
- `needs_approval` can be a static boolean or a dynamic callable/coroutine:
  `needs_approval(context, params, call_id) -> bool`
- For example, an `order_tool` may require approval only if `amount > $1000` or if `customer.risk_tier == "high"`.
- If approval is needed, the tool execution is deferred into a `FunctionToolApproval(outcome="require_approval")` event without touching external systems.

#### 2. Input & Output Guardrails
The SDK enforces multi-layer guardrails that execute independently of the main LLM instructions:
- **Input Guardrails**: Screen incoming messages for prompt injection, sensitive PII, or policy violations before invoking the model.
- **Output Guardrails**: Inspect candidate LLM responses before delivery to ensure no unauthorized commitments or hallucinations are communicated.

---

## 4. Microsoft Agent Framework

- **Repository Path**: `D:\AI-Employee-Platform-Research\microsoft-agent-framework`
- **Git Commit**: `67ba500ec1fd312606a5d585a42335cd8631e851`
- **License**: MIT
- **Architectural Focus**: Enterprise Agent Orchestration, Event-Driven Workflows, Magentic-One Multi-Agent Patterns, Declarative State.

### 4.1 Core File & Class Architecture
| File Path | Primary Classes / Functions | Responsibility |
|---|---|---|
| `python/packages/core/agent_framework/_agents.py` | `BaseAgent`, `ChatAgent` | Base abstraction for stateful conversational agents with hook interceptors. |
| `python/packages/core/agent_framework/_agent_hooks.py` | `AgentHooks` | Pre/post invocation hooks for logging, token counting, and policy enforcement. |
| `python/packages/core/agent_framework/_workflows/_workflow_builder.py` | `WorkflowBuilder`, `Workflow` | Declarative directed graph workflow orchestrator. |
| `python/samples/03-workflows/human-in-the-loop/` | `agents_with_approval_requests.py` | Production sample implementing asynchronous approval gates in multi-agent workflows. |

### 4.2 In-Depth Mechanism Analysis
- **Interchangeable Execution Harnesses**: Separates agent reasoning logic from the execution runtime, allowing the same agent definition to run in local CLI, cloud functions, or long-lived background workers.
- **Hook Lifecycle**: `AgentHooks` provides `on_agent_start`, `on_tool_call_started`, `on_tool_call_completed`, and `on_agent_end`, enabling uniform tenant auditing and telemetry without polluting business code.

---

## 5. RAGLeap Core

- **Repository Path**: `D:\AI-Employee-Platform-Research\ragleap-core`
- **Git Commit**: `b9bb6fbc1f7c8ef0427cb817ffc495578ab0531b` (Release 0.6.2)
- **License**: MIT
- **Architectural Focus**: Production Enterprise Digital Employees, Dual-Channel Approval Dispatch, Role-Based Autonomy.

### 5.1 Core File & Class Architecture
| File Path | Primary Classes / Functions | Responsibility |
|---|---|---|
| `core/autonomy.py` | `request_approval`, `get_autonomy_settings` | Semi-autonomous permission checks, approval token generation, and multi-channel routing. |
| `core/employees/channel_roles.py` | `ChannelRoleManager` | Scopes which team roles and channels (e.g. Telegram, Dashboard) have authority to grant approvals. |
| `packages/ragleap-tools/src/ragleap_tools/toolkit.py` | `Toolkit`, `ToolDecorator` | Clean Pythonic tool binding with parameter validation and automatic OpenAPI schema extraction. |
| `tests/test_approval_message.py` | Test suite | Verifies dual-mode approval messages (Chat Replies with Correlation IDs vs Dashboard Inbox URLs). |

### 5.2 In-Depth Mechanism Analysis

#### 1. Dual-Mode Approval Correlation Token
RAGLeap solves the critical problem of approval hijacking:
When an autonomous agent requires approval for a sensitive action, it generates a unique cryptographic confirmation token (e.g. `"AB12CD34"`):
- **Mode 1 (Chat Reply)**: Sends message: `Reply "YES AB12CD34" to approve or "NO AB12CD34" to reject`.
- **Mode 2 (Dashboard Inbox)**: If chat replies are disabled, points the owner to `POST /autonomy/pending/AB12CD34/approve`.

This pattern ensures that a generic "نعم" or "موافق" uttered by the user in an unrelated conversational context **cannot** accidentally trigger pending high-risk approvals.

---

## 6. Dify (LangGenius)

- **Repository Path**: `D:\AI-Employee-Platform-Research\dify`
- **Git Commit**: `89cdc0c7a9c78027d4e15112e420f6570ae783ab`
- **License**: Apache-2.0
- **Architectural Focus**: Visual DAG Workflows, Tool Execution Engines, Enterprise Multi-Tenancy Isolation, Sandboxed Script Runtimes.

### 6.1 Core File & Class Architecture
| File Path | Primary Classes / Functions | Responsibility |
|---|---|---|
| `api/core/tools/tool_engine.py` | `ToolEngine` | Centralized tool runtime manager handling schema validation, execution callbacks, and tenant scoping. |
| `api/core/workflow/workflow_entry.py` | `WorkflowEntry` | Multi-node DAG workflow runner supporting parallel branching, condition loops, and node retries. |
| `api/services/app/agent_app_sandbox_service.py` | `AgentAppSandboxService` | Manages external isolated sandbox environments for running tenant-provided code and Python transforms. |
| `api/models/agent_sandbox_usage.py` | `AgentSandboxUsage` | Database tracking of CPU, memory, and duration consumed by sandboxed code execution per tenant. |

### 6.2 In-Depth Mechanism Analysis
- **Strict Tenant Scoping in Tool Execution**: `ToolEngine.agent_invoke(session, tool, tool_parameters, user_id, tenant_id, ...)` forces every tool call to receive database session and `tenant_id` context, preventing any tool from accessing records across tenant boundaries.
- **Granular Exception Taxonomy**: Distinct classes for `ToolNotFoundError`, `ToolParameterValidationError`, `ToolProviderCredentialValidationError`, and `ToolEngineInvokeError`. This allows the orchestrator to know whether to ask the user for clarification, re-try with corrected parameters, or notify the admin about credential failure.

---

## 7. n8n

- **Repository Path**: `D:\AI-Employee-Platform-Research\n8n`
- **Git Commit**: `9a489b65ed539a042e819012558cfc6985aab78d`
- **License**: **Sustainable Use License v1.0** (Non-commercial / Source-available restrictions)
- **Architectural Focus**: Visual Node-Based Automation Workflows, Webhook Ingestion, Third-Party Connectors.

### 7.1 Key Findings & Legal Classification
- **License Restriction**: n8n is published under the **Sustainable Use License**, which explicitly forbids using the source code to provide a competing commercial SaaS or managed platform.
- **Engineering Verdict**: **NO SOURCE CODE OR NPM PACKAGES FROM N8N MAY BE COPIED OR DIRECTLY IMPORTED INTO THE PLATFORM.**
- **Architectural Value**: n8n provides valuable conceptual references for:
  - Declarative node schema contracts (Input types, Output types, Default values).
  - Webhook normalization and execution queue handling.
  - Granular node execution error recovery (Continue on Fail, Retry with Backoff).

---

## 8. Cross-Framework Synthesis: Key Capabilities Matrix

| Architectural Capability | Memento-Skills | LangGraph | OpenAI Agents | Microsoft Agent | RAGLeap Core | Dify | AI Employee Platform (Current) |
|---|---|---|---|---|---|---|---|
| **Durable Execution Checkpointing** | ❌ (Disk folder) | ✅ (Postgres CheckpointSaver) | ❌ (In-memory/custom) | ⚠️ (Cosmos/Custom) | ❌ (Session state) | ✅ (DB State) | ⚠️ (Ad-hoc JSON metadata) |
| **Resumable Human Interrupts** | ❌ | ✅ (`interrupt()` + `Command`) | ⚠️ (Approval event) | ⚠️ (HITL Sample) | ✅ (Approval Token) | ⚠️ (Pause node) | ⚠️ (Regex matching) |
| **Self-Evolution & Dynamic Skills** | ✅ (3-gate transactional) | ❌ | ❌ | ❌ | ❌ | ⚠️ (Python node) | ⚠️ (AST Verifier + Sandbox) |
| **Pre-Execution Hallucination Guard** | ✅ (`HallucinationGuard`) | ❌ | ⚠️ (Tool schema) | ❌ | ❌ | ⚠️ (Registry check) | ❌ (Raw exception) |
| **Empirical Utility Tracking** | ✅ (`utility.json`) | ❌ | ❌ | ❌ | ❌ | ⚠️ (Execution logs) | ❌ (None) |
| **Dynamic Tool Approval Policy** | ❌ | ⚠️ (Node logic) | ✅ (`needs_approval` callable) | ⚠️ (Hook) | ✅ (Dual-Mode Token) | ⚠️ (Manual flag) | ⚠️ (Risk enum + Regex) |
| **Multi-Tenant Row Isolation** | ❌ (Single user) | ⚠️ (thread_id) | ❌ (Single user) | ⚠️ (App context) | ⚠️ (Role based) | ✅ (tenant_id in engine) | ✅ (Strict tenant_id in ORM) |
| **Commercial License Viability** | ✅ Apache-2.0 | ✅ MIT | ✅ MIT | ✅ MIT | ✅ MIT | ✅ Apache-2.0 | ✅ Proprietary Enterprise |
