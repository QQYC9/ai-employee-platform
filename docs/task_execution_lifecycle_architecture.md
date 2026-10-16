# Task Execution & Lifecycle Architecture

## 1. Overview

The **Task Execution & Lifecycle System** provides a deterministic, auditable, and resilient orchestration engine for Digital Employees in the **AI Employee Platform**.

In enterprise multi-tenant automation, digital workers cannot rely on "optimistic" execution loops or unverified assertions. The platform guarantees:
1. **Explicit State Machine**: Tasks transition through deterministic lifecycle states with guarded transitions.
2. **Sequential Multi-Step Execution**: Plans execute step-by-step with dependency tracking and immediate stop-on-failure.
3. **Resumption & Idempotency**: Interrupted or approval-paused workflows resume without repeating already-completed steps.
4. **Completion Verification Contract**: Tasks cannot transition to `completed` without structured verification evidence proving that every planned step executed successfully without downstream errors.
5. **Human-in-the-Loop Synchronization**: Approval decisions (approval or rejection) automatically transition and synchronize task state and audit logs.

---

## 2. State Machine & Lifecycle Transitions

### 2.1 Supported States
The task lifecycle is codified in `packages/services/task_lifecycle.py`:
- `pending`: Newly created task awaiting planning or execution.
- `planning`: Task undergoing static or AI-driven plan synthesis.
- `planned`: Plan generated and validated; ready for execution.
- `running`: Currently executing planned steps.
- `waiting_approval`: Execution paused awaiting human owner/admin approval for a guarded action policy.
- `completed`: Successfully executed and verified with evidence.
- `failed`: Execution failed, verification failed, or approval was rejected.
- `cancelled`: Explicitly aborted by user or platform admin.

### 2.2 Transition Matrix
```
[PENDING] ───────> [PLANNING] ───────> [PLANNED] ───────> [RUNNING]
    │                                                        │
    ├──> [CANCELLED]                                         ├──> [WAITING_APPROVAL] ───> [RUNNING]
    │                                                        │         │
    └──> [RUNNING] (Direct execution)                        │         └──> [FAILED] (Rejection)
                                                             ├──> [COMPLETED] (Verified)
                                                             ├──> [FAILED] (Error/Unverified)
                                                             └──> [CANCELLED]
```

- **Recovery / Retry**: Tasks in `failed` status can be retried into `planned` or `running` with `is_recovery=True`.
- **Terminal States**: `completed` and `cancelled` are terminal and reject illegal transitions without explicit recovery flows.

---

## 3. Sequential Multi-Step Execution & Verification Contract

### 3.1 Step-by-Step Orchestration
Tasks planned with multiple steps are executed in strict sequence:
1. **Pre-execution Validation**: Verifies that all tools referenced in the plan are assigned to the tenant's agent before any execution begins.
2. **In-Progress Tracking**: Steps are marked `in_progress` prior to invoking external tools.
3. **Stop-on-Failure**: If any step encounters an unhandled exception or returns an execution error:
   - Execution halts immediately.
   - Subsequent dependent steps are never invoked.
   - The task is marked `failed` with sanitized error details.

### 3.2 Evidence Verification Contract
Implemented in `TaskVerificationService`:
- Validates that all planned steps have reached `completed` status.
- Inspects step results for downstream error indicators (e.g., `"error": ...`, rejection codes).
- Collects structured evidence from step outputs.
- Attaches the verification payload to `task.result`:
```json
{
  "steps": [...],
  "verification": {
    "verified": true,
    "summary": "Task objective fully verified with valid execution evidence.",
    "evidence": {
      "steps": [
        {"step_id": "step1", "output_keys": ["data"], "has_output": true},
        {"step_id": "step2", "output_keys": ["summary"], "has_output": true}
      ]
    },
    "unresolved": [],
    "details": {
      "total_steps": 2,
      "steps_evaluated": 2,
      "steps_completed": 2
    }
  }
}
```

---

## 4. Human Approval Synchronization

When an action policy requires human approval:
1. The step pauses in `waiting_approval`.
2. An `Approval` record is created and linked to the task.
3. **If Approved**:
   - Resuming the task with `resume_approved_task` skips all previously completed steps.
   - Only the pending/approved step and subsequent steps execute.
4. **If Rejected**:
   - The `ApprovalService.reject(...)` automatically marks the associated task as `failed`.
   - The step is marked as `failed`.
   - The task record stores the rejection reason.
   - No subsequent tools or steps are executed.

---

## 5. API Endpoints

| Endpoint | Method | Role | Description |
|---|---|---|---|
| `/api/v1/tasks/{id}/plan` | POST | Member+ | Generates execution plan for task |
| `/api/v1/tasks/{id}/execute` | POST | Member+ | Runs sequential multi-step execution |
| `/api/v1/tasks/{id}/resume` | POST | Owner+ | Resumes task paused for approval |
| `/api/v1/tasks/{id}/retry` | POST | Owner+ | Safely retries a failed task |
| `/api/v1/tasks/{id}/cancel` | POST | Member+ | Cancels a running or pending task |
| `/api/v1/tasks/{id}/verification` | GET | Member+ | Inspects completion verification evidence |

---

## 6. Audit & Idempotency Integration

All state transitions, approval requests, and tool execution phases emit tenant-scoped audit events via `AuditService`:
- `task_planned`
- `task_started`
- `approval_requested`
- `task_resumed`
- `task_completed`
- `task_failed`
- `task_retried`

Distributed locks and persistent idempotency keys (`f"task_exec:{task_id}"`) prevent concurrent duplicate executions of the same task.
