from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified


def _safe_flag_modified(instance: Any, key: str) -> None:
    try:
        flag_modified(instance, key)
    except Exception:
        pass

from packages.ai_providers.gemini_provider import GeminiProvider
from packages.context.builder import ContextBuilder
from packages.core.config import settings
from packages.context.models import AgentContext, TaskContext
from packages.context.retriever import ContextRetriever
from packages.services.agent_capability_service import AgentCapabilityService
from packages.services.idempotency_service import ConcurrencyConflictError, IdempotencyService
from packages.services.capability_tool_service import CapabilityToolService
from packages.services.gemini_task_planner import GeminiTaskPlanner
from packages.services.task_execution_service import TaskExecutionService
from packages.services.task_lifecycle import TaskStatus
from packages.services.task_planner import (
    ExecutionPlan,
    PlanStep,
    TaskPlanner,
)
from packages.services.task_verification_service import TaskVerificationService
from packages.tools.executor import ToolExecutor


@dataclass(frozen=True)
class OrchestrationResult:
    status: str
    task_id: UUID
    plan: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None


class AgentOrchestrator:
    """
    Coordinates the Digital Employee execution lifecycle.

    Responsibilities:
        1. Build task context.
        2. Build and persist a plan.
        3. Execute each planned step.
        4. Respect DecisionEngine and approvals.
        5. Aggregate the final result.
    """

    def __init__(
        self,
        db: Session,
        planner: TaskPlanner | None = None,
        executor: ToolExecutor | None = None,
        context_builder: ContextBuilder | None = None,
        ai_planner: GeminiTaskPlanner | None = None,
    ):
        self.db = db
        self.planner = planner or TaskPlanner()
        self.executor = TaskExecutionService(db)
        self.tool_executor = executor
        self.ai_planner = ai_planner
        self.context_builder = context_builder or ContextBuilder(
            ContextRetriever(db)
        )
        self.last_context: AgentContext | None = None

    def _resolve_ai_planner(self, tenant_id: UUID | None = None) -> GeminiTaskPlanner | None:
        if not settings.ai_planning_enabled:
            return None

        if self.ai_planner is not None:
            return self.ai_planner

        decision_engine = None
        if self.tool_executor is not None and hasattr(self.tool_executor, "decision_engine"):
            decision_engine = self.tool_executor.decision_engine
        elif self.db is not None and hasattr(self.db, "query"):
            from packages.services.decision_engine import DecisionEngine
            try:
                decision_engine = DecisionEngine(self.db)
            except Exception:
                decision_engine = None

        from packages.ai_providers.factory import AIProviderFactory
        provider = AIProviderFactory.create_provider(
            tenant_id=tenant_id,
            db=self.db,
        )

        return GeminiTaskPlanner(
            provider=provider,
            decision_engine=decision_engine,
        )

    def _get_available_tools(
        self,
        tenant_id: UUID,
        agent_id: UUID | None,
    ) -> list[dict[str, Any]]:
        if agent_id is None or self.tool_executor is None:
            return []

        handler_slugs = {
            slug.strip().lower()
            for slug in self.tool_executor.handlers
            if slug.strip()
        }
        if not handler_slugs:
            return []

        capability_service = AgentCapabilityService(self.db)
        tool_service = CapabilityToolService(self.db)
        available: dict[str, dict[str, Any]] = {}

        capabilities = capability_service.list_capabilities(
            tenant_id=tenant_id,
            agent_id=agent_id,
        )

        for capability in capabilities:
            tools = tool_service.list_tools(
                tenant_id=tenant_id,
                capability_id=capability.id,
            )

            for tool in tools:
                slug = tool.slug.strip().lower()
                if slug not in handler_slugs:
                    continue

                tool_id = str(tool.id)
                available[tool_id] = {
                    "id": tool_id,
                    "name": tool.name,
                    "slug": slug,
                    "description": tool.description or "",
                    "tool_type": tool.tool_type,
                }

        return list(available.values())

    def build_task_context(
        self,
        tenant_id: UUID,
        task_id: UUID,
    ) -> AgentContext:
        task = self.executor._get_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )

        task_context = TaskContext(
            task_id=task.id,
            agent_id=task.agent_id,
            objective=task.objective,
            title=task.title,
            priority=task.priority,
            status=task.status,
        )

        context = self.context_builder.build(
            tenant_id=tenant_id,
            task=task_context,
        )

        if context.tenant_id != tenant_id:
            raise ValueError(
                "Context tenant does not match requested tenant"
            )

        self.last_context = context
        return context

    def plan_task(
        self,
        tenant_id: UUID,
        task_id: UUID,
        steps: list[PlanStep] | None = None,
    ) -> ExecutionPlan:
        task = self.executor._get_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )

        if task.status not in (TaskStatus.PENDING, TaskStatus.PLANNED):
            raise ValueError(
                f"Task cannot be planned from status: {task.status}"
            )

        context = self.build_task_context(
            tenant_id=tenant_id,
            task_id=task_id,
        )

        if steps is None:
            ai_planner = self._resolve_ai_planner(tenant_id=tenant_id)

            if ai_planner is None:
                plan = self.planner.create_basic_plan(
                    task,
                    context=context,
                )
            else:
                available_tools = self._get_available_tools(
                    tenant_id=tenant_id,
                    agent_id=task.agent_id,
                )
                decision_engine = None
                if self.tool_executor is not None and hasattr(self.tool_executor, "decision_engine"):
                    decision_engine = self.tool_executor.decision_engine
                elif self.db is not None and hasattr(self.db, "query"):
                    from packages.services.decision_engine import DecisionEngine
                    try:
                        decision_engine = DecisionEngine(self.db)
                    except Exception:
                        decision_engine = None

                plan = ai_planner.create_plan(
                    task=task,
                    context=context,
                    available_tools=available_tools,
                    decision_engine=decision_engine,
                )
        else:
            plan = self.planner.create_plan(
                task=task,
                steps=steps,
                context=context,
            )

        task.plan = plan.to_dict()
        task.status = TaskStatus.PLANNED
        self.db.flush()

        return plan

    def _validate_execution_plan(
        self,
        tenant_id: UUID,
        task: Task,
        plan: ExecutionPlan,
    ) -> None:
        """
        Programmatically validates an execution plan prior to running any steps.
        Checks:
            1. Tool assignment to agent under tenant.
        """
        for step in plan.steps:
            if step.step_type == "tool":
                if not step.tool_id:
                    raise ValueError(
                        f"Tool step requires tool_id: {step.step_id}"
                    )
                if not step.action or not step.action.strip():
                    raise ValueError(
                        f"Tool step requires action: {step.step_id}"
                    )
                if task.agent_id is not None:
                    self.executor._ensure_tool_assigned_to_agent(
                        tenant_id=tenant_id,
                        agent_id=task.agent_id,
                        tool_id=step.tool_id,
                    )

    def execute_task(
        self,
        tenant_id: UUID,
        task_id: UUID,
    ) -> OrchestrationResult:
        task = self.executor._get_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )

        if task.status not in (TaskStatus.PENDING, TaskStatus.PLANNED, TaskStatus.RUNNING):
            raise ValueError(
                f"Task cannot be executed from status: {task.status}"
            )

        # Concurrency protection
        idempotency_service = getattr(self.tool_executor, "idempotency_service", None)
        if idempotency_service is None and self.db is not None:
            try:
                idempotency_service = IdempotencyService(self.db)
            except Exception:
                idempotency_service = None

        exec_lock_key = f"task_exec:{task_id}"
        lock_acquired = False
        if idempotency_service is not None:
            try:
                lock_status, _ = idempotency_service.acquire_or_check(
                    tenant_id=tenant_id,
                    idempotency_key=exec_lock_key,
                    action="execute_task",
                    resource="task",
                    parameters={"task_id": str(task_id)},
                    timeout_seconds=300,
                )
                lock_acquired = True
            except ConcurrencyConflictError:
                raise
            except Exception:
                pass

        if not task.plan or not task.plan.get("steps"):
            plan = self.plan_task(
                tenant_id=tenant_id,
                task_id=task_id,
            )
        else:
            self.build_task_context(
                tenant_id=tenant_id,
                task_id=task_id,
            )
            plan = ExecutionPlan(
                objective=task.plan.get(
                    "objective",
                    task.objective,
                ),
                steps=self._deserialize_steps(
                    task.plan["steps"],
                ),
            )

        if task.status in (TaskStatus.PENDING, TaskStatus.PLANNED):
            self.executor.start_task(
                tenant_id=tenant_id,
                task_id=task_id,
            )

        execution_results: list[dict[str, Any]] = []
        plan_steps_dict = {
            step.get("step_id"): step
            for step in (task.plan.get("steps") or [])
            if isinstance(step, dict)
        }

        try:
            # Pre-execution plan validation
            self._validate_execution_plan(tenant_id, task, plan)

            for step in plan.steps:
                existing_step = plan_steps_dict.get(step.step_id, {})
                if existing_step.get("status") == "completed":
                    saved_result = existing_step.get("result")
                    execution_results.append(
                        {
                            "step_id": step.step_id,
                            "status": "completed",
                            "step_type": step.step_type,
                            "type": step.step_type,
                            "description": step.description,
                            **({"tool_id": str(step.tool_id)} if step.tool_id else {}),
                            **({"result": saved_result} if saved_result is not None else {}),
                        }
                    )
                    continue

                if step.step_type != "tool":
                    execution_results.append(
                        {
                            "step_id": step.step_id,
                            "status": "completed",
                            "step_type": step.step_type,
                            "description": step.description,
                        }
                    )
                    if step.step_id in plan_steps_dict:
                        plan_steps_dict[step.step_id]["status"] = "completed"
                        task.plan = {
                            "objective": plan.objective,
                            "steps": list(plan_steps_dict.values()),
                        }
                        _safe_flag_modified(task, "plan")
                        self.db.flush()
                    continue

                if step.tool_id is None:
                    raise ValueError(
                        f"Tool step requires tool_id: {step.step_id}"
                    )

                if not step.action:
                    raise ValueError(
                        f"Tool step requires action: {step.step_id}"
                    )

                idempotency_key = (
                    (step.parameters or {}).get("idempotency_key")
                    or f"{task.id}:{step.step_id}"
                )
                step_params = step.parameters or {}

                # Detect interrupted execution from crash before save
                if existing_step.get("status") == "in_progress":
                    reconciled_output = None
                    if hasattr(self.tool_executor, "check_idempotent_result"):
                        reconciled_output = self.tool_executor.check_idempotent_result(
                            tenant_id=tenant_id,
                            tool_id=step.tool_id,
                            idempotency_key=idempotency_key,
                        )
                    if reconciled_output is not None:
                        execution_results.append(
                            {
                                "step_id": step.step_id,
                                "status": "completed",
                                "type": "tool",
                                "tool_id": str(step.tool_id),
                                "result": reconciled_output,
                            }
                        )
                        if step.step_id in plan_steps_dict:
                            plan_steps_dict[step.step_id]["status"] = "completed"
                            plan_steps_dict[step.step_id]["result"] = reconciled_output
                            task.plan = {
                                "objective": plan.objective,
                                "steps": list(plan_steps_dict.values()),
                            }
                            _safe_flag_modified(task, "plan")
                            self.db.flush()
                        continue
                    else:
                        err_msg = (
                            f"Step '{step.step_id}' was interrupted in-progress. "
                            f"External execution status cannot be verified automatically. "
                            f"Manual reconciliation required to prevent duplicate actions."
                        )
                        task.status = "failed"
                        task.error = err_msg
                        if step.step_id in plan_steps_dict:
                            plan_steps_dict[step.step_id]["status"] = "reconciliation_required"
                            task.plan = {
                                "objective": plan.objective,
                                "steps": list(plan_steps_dict.values()),
                            }
                            _safe_flag_modified(task, "plan")
                        self.db.flush()
                        return OrchestrationResult(
                            status="failed",
                            task_id=task.id,
                            plan=plan.to_dict(),
                            result={"steps": execution_results},
                            error=err_msg,
                        )

                # Persist in_progress status before external tool invocation
                if step.step_id in plan_steps_dict:
                    plan_steps_dict[step.step_id]["status"] = "in_progress"
                    task.plan = {
                        "objective": plan.objective,
                        "steps": list(plan_steps_dict.values()),
                    }
                    _safe_flag_modified(task, "plan")
                    self.db.flush()

                exec_tool_kwargs = {
                    "tenant_id": tenant_id,
                    "task_id": task_id,
                    "tool_id": step.tool_id,
                    "action": step.action,
                    "resource": step.resource or "",
                    "parameters": step_params,
                    "executor": self.tool_executor,
                    "task_already_running": True,
                }
                try:
                    sig = inspect.signature(self.executor.execute_tool)
                    if "idempotency_key" in sig.parameters or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD
                        for p in sig.parameters.values()
                    ):
                        exec_tool_kwargs["idempotency_key"] = idempotency_key
                except (ValueError, TypeError):
                    pass

                task = self.executor.execute_tool(**exec_tool_kwargs)

                if task.status == "waiting_approval":
                    if step.step_id in plan_steps_dict:
                        plan_steps_dict[step.step_id]["status"] = "waiting_approval"
                        task.plan = {
                            "objective": plan.objective,
                            "steps": list(plan_steps_dict.values()),
                        }
                        _safe_flag_modified(task, "plan")
                        self.db.flush()
                    if lock_acquired and idempotency_service is not None:
                        try:
                            idempotency_service.fail(tenant_id, exec_lock_key, "waiting_approval")
                        except Exception:
                            pass
                    return OrchestrationResult(
                        status="waiting_approval",
                        task_id=task.id,
                        plan=plan.to_dict(),
                        result={"steps": execution_results},
                    )

                if task.status == "failed":
                    if step.step_id in plan_steps_dict:
                        plan_steps_dict[step.step_id]["status"] = "failed"
                        task.plan = {
                            "objective": plan.objective,
                            "steps": list(plan_steps_dict.values()),
                        }
                        _safe_flag_modified(task, "plan")
                        self.db.flush()
                    if lock_acquired and idempotency_service is not None:
                        try:
                            idempotency_service.fail(tenant_id, exec_lock_key, task.error or "step_failed")
                        except Exception:
                            pass
                    return OrchestrationResult(
                        status="failed",
                        task_id=task.id,
                        plan=plan.to_dict(),
                        result={"steps": execution_results},
                        error=task.error,
                    )

                execution_results.append(
                    {
                        "step_id": step.step_id,
                        "status": "completed",
                        "type": "tool",
                        "tool_id": str(step.tool_id),
                        "result": task.result,
                    }
                )

                if step.step_id in plan_steps_dict:
                    plan_steps_dict[step.step_id]["status"] = "completed"
                    plan_steps_dict[step.step_id]["result"] = task.result
                    task.plan = {
                        "objective": plan.objective,
                        "steps": list(plan_steps_dict.values()),
                    }
                    _safe_flag_modified(task, "plan")
                    self.db.flush()

            current_task = self.executor._get_task(
                tenant_id=tenant_id,
                task_id=task_id,
            )

            if current_task.status == "running":
                # Workstream 4: Completion verification using evidence contract
                verification_service = TaskVerificationService(self.db)
                verification = verification_service.verify_completion(
                    task=current_task,
                    plan=plan,
                    execution_results=execution_results,
                )

                if not verification.verified:
                    err_msg = f"Task verification failed: {verification.summary}"
                    self.executor.fail_task(
                        tenant_id=tenant_id,
                        task_id=task_id,
                        error=err_msg,
                    )
                    current_task.result = {
                        "steps": execution_results,
                        "verification": {
                            "verified": False,
                            "summary": verification.summary,
                            "unresolved": verification.unresolved,
                            "details": verification.details,
                        },
                    }
                    _safe_flag_modified(current_task, "result")
                    self.db.flush()
                    if lock_acquired and idempotency_service is not None:
                        try:
                            idempotency_service.fail(tenant_id, exec_lock_key, err_msg)
                        except Exception:
                            pass
                    return OrchestrationResult(
                        status="failed",
                        task_id=task_id,
                        plan=plan.to_dict(),
                        result=current_task.result,
                        error=err_msg,
                    )

                final_result = {
                    "steps": execution_results,
                    "verification": {
                        "verified": True,
                        "summary": verification.summary,
                        "evidence": verification.evidence,
                        "unresolved": [],
                        "details": verification.details,
                    },
                }
                self.executor.complete_task(
                    tenant_id=tenant_id,
                    task_id=task_id,
                    result=final_result,
                )
                if lock_acquired and idempotency_service is not None:
                    try:
                        idempotency_service.complete(tenant_id, exec_lock_key, result=final_result)
                    except Exception:
                        pass

            return OrchestrationResult(
                status="completed",
                task_id=task_id,
                plan=plan.to_dict(),
                result=current_task.result if current_task and current_task.result else {"steps": execution_results},
            )

        except ConcurrencyConflictError:
            raise

        except Exception as exc:
            if lock_acquired and idempotency_service is not None:
                try:
                    idempotency_service.fail(tenant_id, exec_lock_key, str(exc))
                except Exception:
                    pass

            current_task = self.executor._get_task(
                tenant_id=tenant_id,
                task_id=task_id,
            )

            if current_task.status == "running":
                self.executor.fail_task(
                    tenant_id=tenant_id,
                    task_id=task_id,
                    error=str(exc),
                )

            raise

    def resume_approved_task(
        self,
        tenant_id: UUID,
        task_id: UUID,
        approval_id: UUID,
    ) -> OrchestrationResult:
        """
        Resume a task that was paused in waiting_approval status after approval.
        Revalidates approval record, transitions task to running, and continues execution.
        """
        self.executor.resume_approved_task(
            tenant_id=tenant_id,
            task_id=task_id,
            approval_id=approval_id,
        )
        return self.execute_task(
            tenant_id=tenant_id,
            task_id=task_id,
        )

    @staticmethod
    def _deserialize_steps(
        steps: list[dict[str, Any]],
    ) -> list[PlanStep]:
        result: list[PlanStep] = []

        for step in steps:
            tool_id = step.get("tool_id")

            result.append(
                PlanStep(
                    step_id=step["step_id"],
                    step_type=step["step_type"],
                    description=step["description"],
                    action=step.get("action"),
                    resource=step.get("resource"),
                    tool_id=UUID(tool_id) if tool_id else None,
                    parameters=step.get("parameters") or {},
                    requires_approval=bool(step.get("requires_approval", False)),
                    approval_for=step.get("approval_for"),
                )
            )

        return result
