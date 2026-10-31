# Comprehensive Source Evidence Index (Audited & Verified)

**Authoritative Technical Evidence Ledger — AI Employee Platform**  
**Repository Working Directory**: `D:\AI-Employee-Platform`  
**Research Working Directory**: `D:\AI-Employee-Platform-Research`  
**Audit Status**: Verified via Code Inspection & Live Pytest Execution  
**Target Milestone**: Digital Employee Autonomous Evolution  

---

## 1. Cloned Open-Source Repositories Evidence

| Repository Name | Local Cloned Path | Verified Git Commit | Declared License | Verified Legal Terms & Restrictions |
|---|---|---|---|---|
| **memento-skills** | `D:\AI-Employee-Platform-Research\memento-skills` | `ee9b9a45efd093d669c06fe318b4b1dceb246d19` | Apache-2.0 | Standard Apache 2.0 (Yangtze AI Lab). Permissive commercial use with attribution. |
| **langgraph** | `D:\AI-Employee-Platform-Research\langgraph` | `4c52e129eb1ab69a3da58b799f67929f77d81149` (v1.2.17) | MIT | Standard MIT (LangChain, Inc.). Permissive commercial use. |
| **openai-agents-python** | `D:\AI-Employee-Platform-Research\openai-agents-python` | `0dc4cf152bff1f50bdc0e41f28808563406545b2` | MIT | Standard MIT (OpenAI). Permissive commercial use. |
| **microsoft-agent-framework** | `D:\AI-Employee-Platform-Research\microsoft-agent-framework` | `67ba500ec1fd312606a5d585a42335cd8631e851` | MIT | Standard MIT (Microsoft Corporation). Permissive commercial use. |
| **ragleap-core** | `D:\AI-Employee-Platform-Research\ragleap-core` | `b9bb6fbc1f7c8ef0427cb817ffc495578ab0531b` (v0.6.2) | MIT | Standard MIT (RagLeap). Permissive commercial use. |
| **dify** | `D:\AI-Employee-Platform-Research\dify` | `89cdc0c7a9c78027d4e15112e420f6570ae783ab` | **Modified Apache-2.0** | **CRITICAL AUDIT FINDING**: Section 1.a explicitly prohibits operating a multi-tenant environment without written commercial license from Dify. **Zero code adoption allowed.** |
| **n8n** | `D:\AI-Employee-Platform-Research\n8n` | `9a489b65ed539a042e819012558cfc6985aab78d` | **Sustainable Use License v1.0** | **CRITICAL AUDIT FINDING**: Prohibits commercial hosted/managed services. **Zero code adoption allowed.** |

---

## 2. Platform Source Files & Key Function Evidence (Audited Corrections)

| Subsystem | Real Verified File Path | Real Verified Class & Methods | Audited Line Range | Verified Findings & Corrections |
|---|---|---|---|---|
| **Inbound Message Flow** | `apps/agent/api/v1/webhooks.py` | `whatsapp_webhook`, `telegram_webhook` | Lines 45–140 | Webhook ingress with HMAC signature validation. |
| **Channel Routing & Outbox** | `packages/services/channel_service.py` | `ChannelService.process_inbound_message` | Lines 120–210 | Computes idempotency hash, creates `Message`, enqueues `OutboxEvent`. |
| **Transactional Outbox Worker** | `packages/services/outbox_worker.py` | `OutboxWorker.process_event`<br>`calculate_backoff` | Lines 105–220 | Implements `calculate_backoff` with exponential backoff (`2s, 4s, 8s... max 60s/300s`). |
| **Agent Engine (Current)** | `packages/services/conversational_agent_engine.py` | `process_incoming_message`<br>`_process_owner_message` | Lines 200–375<br>Lines 720–1350 | Monolithic linear flow (~2,588 lines). Approvals, capability gaps, and knowledge teaching sequentially evaluated. |
| **Owner Intent Router** | `packages/services/owner_intent_router.py` | `OwnerIntentRouter.parse_intent`<br>`execute_plan` | Lines 120–280<br>Lines 450–620 | Pydantic contracts for `bulk_destructive_operation` and `multi_step_workflow`. |
| **Approvals Service** | `packages/services/approval_service.py` | `create_approval`<br>`approve`<br>`reject`<br>`list_approvals` | Lines 22–200 | Manages approvals. Requires `user_role` and `decision_by_user_id`. Verified cross-tenant rejection. |
| **Dynamic Capabilities Engine** | `packages/self_development/engine.py` | `SelfDevelopmentEngine.process_request`<br>`activate_version` | Lines 75–230 | Sandboxed code generation, testing, and database versioning. |
| **AST Security Verifier** | `packages/self_development/verifier.py` | `CapabilitySecurityVerifier.static_analysis` | Lines 30–120 | **CORRECTION**: Returns dict with keys `valid` (bool) and `violations` (list). Blocks `os.system`, `open`, `eval`, subclass traversal. |
| **Execution Sandbox** | `packages/self_development/sandbox.py` | `ExecutionSandbox.execute(code, inputs)`<br>`run_code(code, input_data)` | Lines 64–180 | **CORRECTION**: Takes `(code: str, inputs: dict | None)`. Discovered missing `mask_secrets` call on `MemorySanitizer`. |
| **Context Retrieval & RAG** | `packages/context/retriever.py` | `ContextRetriever.get_knowledge`<br>`ContextRetriever.get_memories` | Lines 33–180 | **CORRECTION**: Real file is `retriever.py` (not `context_retriever.py`), real method is `get_knowledge` (not `retrieve_knowledge`). Strictly filters on `tenant_id`. |
| **Execution Tracing** | `packages/services/tracing_service.py` | `TracingService.start_trace`<br>`record_step`<br>`complete_trace` | Lines 45–190 | Records observability spans in `execution_traces` and `execution_steps`. |

---

## 3. Database Models & Schema Evidence (Audited Schema)

| Table Name | Model Class | Declared File Path | Real Columns Verified | Audited Gap / Notes |
|---|---|---|---|---|
| `tenants` | `Tenant` | `packages/models/tenant.py` | `id`, `name`, `slug`, `status`, `config_json`, `created_at` | **CORRECTION**: Model is defined in `tenant.py` (not `domain.py`). |
| `conversations` | `Conversation` | `packages/models/domain.py` | `id`, `tenant_id`, `channel_id`, `customer_id`, `subject`, `status`, `metadata_json` | Stores `metadata_json["pending_goal"]`. |
| `messages` | `Message` | `packages/models/domain.py` | `id`, `tenant_id`, `conversation_id`, `sender_type`, `sender_id`, `content`, `metadata_json` | Idempotency hash in `metadata_json`. |
| `approvals` | `Approval` | `packages/models/domain.py` | `id`, `tenant_id`, `task_id`, `requested_by_agent_id`, `requested_for`, `action`, `description`, `status`, `decision_by_user_id`, `decision_reason`, `created_at`, `decided_at` | **CRITICAL AUDIT VERIFICATION**: Columns `token` and `expires_at` do NOT exist currently! Action and description are single text fields. |
| `knowledge` | `Knowledge` | `packages/models/domain.py` | `id`, `tenant_id`, `provenance_id`, `title`, `content`, `knowledge_type`, `status`, `metadata_json`, `version` | **CORRECTION**: Column is `knowledge_type` (not `category`). |
| `capabilities` | `Capability` | `packages/models/domain.py` | `id`, `tenant_id`, `slug`, `name`, `description`, `risk_level`, `status`, `created_at` | Registered dynamic capability roots. |
| `capability_versions` | `CapabilityVersion` | `packages/models/domain.py` | `id`, `capability_id`, `version_number`, `implementation_code`, `specification`, `test_results`, `status`, `approval_id` | Immutable code revisions. |
| `execution_traces` | `ExecutionTrace` | `packages/models/domain.py` | `id`, `tenant_id`, `conversation_id`, `trigger_type`, `status`, `started_at`, `completed_at` | Root observability trace. |
| `execution_steps` | `ExecutionStep` | `packages/models/domain.py` | `id`, `trace_id`, `step_name`, `step_type`, `step_order`, `status`, `started_at`, `completed_at` | Granular step execution trace. |

---

## 4. Live Verification Test Evidence (`tests/test_evidence_audit_priority_risks.py`)

All 12 priority risk tests were executed against `ai_employee_test` (Port 5433) using pytest:
- **Command**: `.venv\Scripts\pytest.exe tests/test_evidence_audit_priority_risks.py -v`
- **Verified Output**: `12 passed, 1 warning in 9.28s`

### Test-by-Test Evidence Log:
1. `test_risk_1_generic_affirmation_in_conversation_without_pending_approval`: **PASSED**. Returns *"لا توجد حالياً أي طلبات موافقة معلقة"* without error.
2. `test_risk_2_approval_expiry_behavior_and_gap_verification`: **PASSED**. Confirmed `expires_at` does not exist on `Approval`, proving architectural gap.
3. `test_risk_3_cross_tenant_approval_attack_blocked`: **PASSED**. Tenant B approving Tenant A's request raised `PermissionError("Cross-tenant access prohibited...")`.
4. `test_risk_4_concurrent_or_duplicate_approval_prevention`: **PASSED**. Second approval attempt raised `ValueError("Only pending approvals can be approved")`.
5. `test_risk_5_outbox_side_effect_idempotency_and_crash_safety`: **PASSED**. Verified exponential backoff calculation (2.0s $\rightarrow$ 4.0s $\rightarrow$ 8.0s capped at 60.0s).
6. `test_risk_6_multi_step_resumption_state_drift_and_side_effects`: **PASSED**. Proved that popping `pending_goal` from `metadata_json` erases intermediate workflow state.
7. `test_risk_7_dynamic_tool_sandbox_security_blocks_malicious_code`: **PASSED**. AST verifier blocked `os.system`, `open('/etc/passwd')`, `eval`, and subclass traversal.
8. `test_risk_8_unknown_tool_and_contract_validation_rejection`: **PASSED**. `ToolRegistry.get("unknown_tool")` returned `None`, proving need for HallucinationGuard.
9. `test_risk_9_cross_tenant_knowledge_retrieval_strict_isolation`: **PASSED**. Tenant A searching for confidential Tenant B knowledge returned 0 items.
10. `test_risk_10_dynamic_tool_regression_failure_keeps_previous_version_active`: **PASSED**. Broken candidate code (ZeroDivisionError) failed execution; valid version succeeded.
11. `test_risk_11_external_service_downtime_handling`: **PASSED**. Verified `is_transient_error` classifies timeouts and 503s as transient.
12. `test_risk_12_deterministic_test_gate_overrides_llm_judge`: **PASSED**. Proved deterministic sandbox failure cannot be overridden by mock LLM judge.
