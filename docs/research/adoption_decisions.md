# Architectural Adoption Decisions: Audited Decision Record (ADR)

**Authoritative Technical Decision Record — AI Employee Platform**  
**Repository Working Directory**: `D:\AI-Employee-Platform`  
**Audit Status**: Verified via Empirical Audit & Live Pytest Execution (`tests/test_evidence_audit_priority_risks.py`)  
**Target Milestone**: Digital Employee Autonomous Evolution  

---

## 1. Audit Framework & Classification Standards

Every architectural decision is evaluated across six rigorous operational criteria:
1. **Current Decision**: The proposed architectural posture (**Adopt**, **Adapt**, **Reject**, or **Needs Experiment**).
2. **Supporting Evidence**: Concrete repository commits, inspected code lines, or live test results.
3. **Risks and Assumptions**: Unverified hypotheses, failure modes, or edge cases.
4. **Required Modification**: Specific architectural adjustments identified during the audit.
5. **Acceptance Test**: Concrete test cases required for sign-off.
6. **Rollback Conditions**: Triggers that necessitate immediate reverting to the prior stable mechanism.
7. **Confidence Level**: **High**, **Medium**, or **Low**, strictly tied to the completeness of verified empirical evidence.

---

## 2. Granular Audited Decisions

### Decision 1: Adapt LangGraph StateGraph (Native Python/SQLAlchemy Implementation)
- **Current Decision**: **ADAPT**
- **Supporting Evidence**:
  - `libs/langgraph/langgraph/graph/state.py` and `libs/langgraph/types.py` (`interrupt()`, `Command(resume=...)`).
  - Empirical proof in `tests/test_evidence_audit_priority_risks.py::test_risk_6_multi_step_resumption_state_drift_and_side_effects`: Popping `pending_goal` from `conversation.metadata_json` erases intermediate state for multi-step tasks, proving the need for a dedicated checkpoint engine.
- **Risks and Assumptions**:
  - *Risk*: Implementing a full Pregel execution loop natively could introduce concurrency race conditions if multiple messages arrive on the same thread simultaneously.
  - *Assumption*: PostgreSQL row locking (`SELECT FOR UPDATE`) on the thread's checkpoint record is sufficient to serialize turn execution.
- **Required Modification**:
  - Do NOT import `langgraph` or `langchain` packages into `.venv` (avoids 350 MB dependency bloat and Python 3.14 C-extension build issues).
  - Implement a lightweight `StateGraph` in `packages/orchestration/state_graph.py` with two PostgreSQL tables: `agent_task_checkpoints` and `agent_task_writes`.
  - Enforce `SELECT ... FOR UPDATE` row-level locks on the checkpoint record during resumption.
- **Acceptance Test**:
  - Suspend a 3-node workflow at Node 2 via `interrupt()`, simulate 48-hour delay, resume via `Command(resume=...)`. Verify Node 1 is not re-executed and outbox events are not duplicated.
- **Rollback Conditions**:
  - Any deadlock or concurrency lock timeout exceeding 5 seconds in staging benchmarks.
- **Confidence Level**: **High** (Underlying mathematical model verified; necessity proven by Risk Test 6).

---

### Decision 2: Adopt Memento-Skills 3-Gate Transactional Skill Evolution
- **Current Decision**: **ADOPT**
- **Supporting Evidence**:
  - `memento-skills/core/skill/evolution/engine.py` (Commit `ee9b9a4`).
  - Empirical proof in `tests/test_evidence_audit_priority_risks.py::test_risk_7_dynamic_tool_sandbox_security_blocks_malicious_code`: Static AST analysis successfully blocks OS commands, `open()`, `eval()`, and subclass traversal.
  - Empirical proof in `test_risk_12_deterministic_test_gate_overrides_llm_judge`: Proved that deterministic Gates 1 & 2 must strictly gate Gate 3 (LLM Judge), preventing synthetic hallucinations from deploying broken code.
- **Risks and Assumptions**:
  - *Risk*: Running Docker containers on Windows during skill verification introduces 4–5 second latency spikes.
  - *Audit Finding*: Discovered that `packages/self_development/sandbox.py` calls `MemorySanitizer.mask_secrets`, which was not yet implemented in `packages/memory/sanitizer.py`.
- **Required Modification**:
  - Implement `MemorySanitizer.mask_secrets(cls, text: str) -> str` in `packages/memory/sanitizer.py` using its compiled regex patterns.
  - Wrap candidate execution in `def run(inputs):` inside the sandbox runner to prevent Python local variable scope collision with module-level `import json`.
  - Use isolated subprocess execution (`backend="subprocess"`) with strict sanitized environment variables (`HOST_SECRET_DENYLIST`) for fast test execution.
- **Acceptance Test**:
  - Candidate with AST violation rejected at Gate 1; candidate with runtime crash rejected at Gate 2; synthetic LLM judge evaluates only candidates passing Gates 1 & 2.
- **Rollback Conditions**:
  - Any dynamic capability execution timeout or sandbox escape attempt.
- **Confidence Level**: **High** (Core AST and sandbox behavior verified; missing helper identified and scoped).

---

### Decision 3: Adopt RAGLeap Dual-Mode Approval Correlation Tokens (`APP-XXXX`)
- **Current Decision**: **ADOPT**
- **Supporting Evidence**:
  - `ragleap-core/core/autonomy.py` and `tests/test_approval_message.py` (Commit `b9bb6fb`).
  - Empirical proof in `tests/test_evidence_audit_priority_risks.py::test_risk_1_generic_affirmation_in_conversation_without_pending_approval`: Generic affirmation with no pending approval safely rejected.
  - Empirical proof in `test_risk_3_cross_tenant_approval_attack_blocked`: Proved cross-tenant approval attempts raise `PermissionError`.
  - Audit of `packages/models/domain.py`: Verified that `Approval` currently lacks `token` and `expires_at` columns!
- **Risks and Assumptions**:
  - *Risk*: Users might mistype the 4-character token on mobile keyboards.
  - *Assumption*: Providing both chat reply (`موافق APP-4821`) and single-click dashboard authorization link provides complete UX flexibility.
- **Required Modification**:
  - Add `token: Mapped[str] = mapped_column(String(16), nullable=True, index=True)` to `Approval` model.
  - Add `expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)` to `Approval` model.
  - Reject approvals where `datetime.now(timezone.utc) > approval.expires_at`.
- **Acceptance Test**:
  - Chat message "موافق APP-4821" approves request; chat message "نعم نحن جاهزون" in normal business chat leaves approval pending; expired token rejected.
- **Rollback Conditions**:
  - Any regression in existing tenant approval workflows.
- **Confidence Level**: **High** (Architectural gap verified in DB schema; security benefits proven).

---

### Decision 4: Adopt Memento-Skills Pre-Execution Hallucination Guard
- **Current Decision**: **ADOPT**
- **Supporting Evidence**:
  - `memento-skills/core/memento_s/skill_dispatch/hallucination_guard.py`.
  - Empirical proof in `tests/test_evidence_audit_priority_risks.py::test_risk_8_unknown_tool_and_contract_validation_rejection`: Querying `ToolRegistry.get("non_existent_tool")` returns `None`, which in `ConversationalAgentEngine` causes an unhandled failure or conversational abort.
- **Risks and Assumptions**:
  - *Risk*: Fuzzy matching cutoff too low might map to the wrong tool.
- **Required Modification**:
  - Set fuzzy match cutoff strictly to $\ge 0.65$. If match confidence is between $0.65$ and $0.85$, prompt user for confirmation: *"Did you mean [Tool Name]?"*. If $< 0.65$, inform user that capability is not available.
- **Acceptance Test**:
  - Tool call `customer_search` mapped to `customer_lookup`; tool call `completely_alien_action` returns structured `UNKNOWN_TOOL` status.
- **Rollback Conditions**:
  - False tool remapping rate $> 1\%$ in benchmark evaluations.
- **Confidence Level**: **High** (Directly prevents unhandled exceptions in engine).

---

### Decision 5: Strictly Reject Direct Dify Source Code Ingestion (Legal Multi-Tenant Restriction)
- **Current Decision**: **REJECT CODE / ADAPT CONCEPT ONLY**
- **Supporting Evidence**:
  - Forensic inspection of `D:\AI-Employee-Platform-Research\dify\LICENSE`:
    > *"Unless explicitly authorized by Dify in writing, you may not use the Dify source code to operate a multi-tenant environment. Tenant Definition: Within the context of Dify, one tenant corresponds to one workspace."*
- **Risks and Assumptions**:
  - *Risk*: Using Dify source code or packages in our multi-tenant enterprise platform creates legal copyright liability.
- **Required Modification**:
  - **ZERO Dify source code files, dependencies, or modules may be imported or copied.**
  - We adapt ONLY the architectural concept: passing an immutable `ToolExecutionContext(tenant_id, user_id, db)` to tools to enforce multi-tenant isolation, implemented 100% natively in Python/SQLAlchemy.
- **Acceptance Test**:
  - License audit script verifies 0 Dify copyright headers or code snippets in repository.
- **Rollback Conditions**:
  - N/A (Preventative compliance).
- **Confidence Level**: **Absolute / Verified Fact** (Explicit license clause in `dify/LICENSE` Section 1.a).

---

### Decision 6: Strictly Reject n8n Core Code & Packages (Commercial SaaS Restriction)
- **Current Decision**: **STRICTLY REJECT**
- **Supporting Evidence**:
  - `D:\AI-Employee-Platform-Research\n8n\LICENSE.md`: Sustainable Use License v1.0 explicitly forbids offering the software as a managed commercial service.
- **Risks and Assumptions**:
  - *Risk*: Severe commercial copyright infringement.
- **Required Modification**:
  - Zero code, zero npm packages, zero n8n components in repository.
- **Acceptance Test**:
  - Verification that no n8n code or dependencies exist.
- **Confidence Level**: **Absolute / Verified Fact**.

---

### Decision 7: Needs Experiment — Magentic-One Multi-Agent Loop
- **Current Decision**: **NEEDS EXPERIMENT**
- **Supporting Evidence**:
  - `microsoft-agent-framework/python/samples/autogen-migration/orchestrations/04_magentic_one.py`.
- **Risks and Assumptions**:
  - *Risk*: Multi-agent iterative loops (WebSurfer, Coder, Orchestrator) consume 5x–10x more LLM tokens and increase response latency to 15–30 seconds, unacceptable for real-time customer WhatsApp/Telegram interactions.
- **Required Modification**:
  - Do NOT deploy Magentic-One to production customer channels.
  - Implement an isolated benchmark in staging to compare single-agent StateGraph vs Magentic-One on 50 complex enterprise tasks.
- **Acceptance Test**:
  - Task completion quality vs token cost and latency benchmarks.
- **Rollback Conditions**:
  - P95 latency $> 5,000\text{ ms}$ or token cost $> \$0.05$ per turn.
- **Confidence Level**: **Medium / Hypothesis Requiring Experiment**.
