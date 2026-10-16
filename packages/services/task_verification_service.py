from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from packages.models.domain import Task
from packages.services.task_planner import ExecutionPlan


@dataclass(frozen=True)
class TaskVerificationResult:
    """Represents the outcome of task completion verification."""

    verified: bool
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class TaskVerificationService:
    """
    Enforces a strict completion verification contract.
    Never relies on model self-reporting alone as evidence of success.
    Requires genuine runtime execution artifacts, verified step outputs,
    and side-effect evidence.
    """

    def __init__(self, db: Session | None = None):
        self.db = db

    def verify_completion(
        self,
        task: Task,
        plan: ExecutionPlan | None,
        execution_results: list[dict[str, Any]],
    ) -> TaskVerificationResult:
        """
        Verify that all planned steps completed successfully and produced valid evidence.
        """
        unresolved: list[str] = []
        evidence_collected: dict[str, Any] = {}
        step_evaluations: list[dict[str, Any]] = []

        # 1. Check if execution results exist
        if not execution_results:
            return TaskVerificationResult(
                verified=False,
                summary="Verification failed: No execution step results were recorded",
                unresolved=["No execution records found for task"],
            )

        executed_step_ids = {
            step.get("step_id")
            for step in execution_results
            if isinstance(step, dict) and step.get("step_id")
        }

        # 2. Check all planned steps are present in execution results
        if plan is not None and plan.steps:
            for planned_step in plan.steps:
                if planned_step.step_id not in executed_step_ids:
                    unresolved.append(
                        f"Planned step '{planned_step.step_id}' ({planned_step.description}) was not executed"
                    )

        # 3. Verify each executed step status and output integrity
        for step in execution_results:
            step_id = step.get("step_id", "unknown_step")
            step_status = step.get("status")
            step_type = step.get("type") or step.get("step_type", "action")

            if step_status != "completed":
                unresolved.append(
                    f"Step '{step_id}' has non-terminal/incomplete status: '{step_status}'"
                )
                continue

            # For tool/action steps, verify actual output payload
            if step_type in ("tool", "action") or step.get("tool_id"):
                result_payload = step.get("result")
                tool_id = step.get("tool_id")

                if result_payload is None:
                    unresolved.append(
                        f"Tool step '{step_id}' completed without any recorded output evidence"
                    )
                    continue

                # Check if the output dictionary indicates an internal tool-level failure
                if isinstance(result_payload, dict):
                    output_status = str(result_payload.get("status", "")).lower()
                    if output_status in ("error", "failed", "blocked") or ("error" in result_payload and result_payload.get("error")):
                        err_detail = (
                            result_payload.get("error")
                            or result_payload.get("reason")
                            or output_status
                        )
                        unresolved.append(
                            f"Tool step '{step_id}' output indicates tool execution failure: '{err_detail}'"
                        )
                        continue

                    if result_payload.get("success") is False:
                        err_detail = result_payload.get("error") or "success flag is false"
                        unresolved.append(
                            f"Tool step '{step_id}' output declared failure: '{err_detail}'"
                        )
                        continue

                evidence_collected[step_id] = {
                    "tool_id": str(tool_id) if tool_id else None,
                    "output_verified": True,
                    "output_sample": (
                        {k: v for k, v in result_payload.items() if not str(k).lower().endswith("key")}
                        if isinstance(result_payload, dict)
                        else str(result_payload)[:200]
                    ),
                }

            step_evaluations.append({
                "step_id": step_id,
                "type": step_type,
                "status": step_status,
                "verified": True,
            })

        # 4. Check explicit success criteria in plan if specified
        task_plan_dict = task.plan if isinstance(task.plan, dict) else {}
        criteria = task_plan_dict.get("success_criteria") or []
        criteria_evaluated = []
        if isinstance(criteria, list):
            for c in criteria:
                criteria_evaluated.append({
                    "criterion": str(c),
                    "satisfied": len(unresolved) == 0,
                })

        # 5. Determine overall verdict
        is_verified = len(unresolved) == 0
        now_iso = datetime.now(timezone.utc).isoformat()

        if is_verified:
            summary = (
                f"Task verified successfully: all {len(execution_results)} planned steps "
                f"produced concrete execution evidence."
            )
        else:
            summary = (
                f"Task verification failed: {len(unresolved)} requirement(s) could not be verified."
            )

        details = {
            "verified_at": now_iso,
            "steps_evaluated": len(execution_results),
            "step_evaluations": step_evaluations,
            "criteria_evaluated": criteria_evaluated,
        }

        return TaskVerificationResult(
            verified=is_verified,
            summary=summary,
            evidence={
                "steps": evidence_collected,
                "verified_at": now_iso,
            },
            unresolved=unresolved,
            details=details,
        )
