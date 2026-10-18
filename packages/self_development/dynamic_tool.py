from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from packages.self_development.sandbox import ExecutionSandbox
from packages.self_development.specification import CapabilitySpecification
from packages.tools.base import BaseRealTool
from packages.tools.contract import (
    StandardToolResult,
    ToolContract,
    ToolExecutionContext,
    ToolRiskLevel,
)

logger = logging.getLogger(__name__)


class DynamicCapabilityTool(BaseRealTool):
    """
    Adapter that wraps an approved and activated dynamic capability version,
    presenting it as a standard platform tool compatible with ToolRegistry and ToolExecutor.
    """

    def __init__(
        self,
        tenant_id: UUID,
        slug: str,
        name: str,
        description: str,
        implementation_code: str,
        spec: CapabilitySpecification,
        sandbox: ExecutionSandbox | None = None,
    ):
        self.tenant_id = tenant_id
        self.implementation_code = implementation_code
        self.spec = spec
        self.sandbox = sandbox or ExecutionSandbox(
            timeout_seconds=spec.execution_limits.timeout_seconds,
            max_output_chars=spec.execution_limits.max_output_chars,
        )

        risk_enum = ToolRiskLevel.MEDIUM
        if spec.risk_level == "low":
            risk_enum = ToolRiskLevel.LOW
        elif spec.risk_level == "high":
            risk_enum = ToolRiskLevel.HIGH

        self._contract = ToolContract(
            slug=slug,
            name=name,
            version="1.0.0",
            description=description,
            risk_level=risk_enum,
            requires_approval=(spec.risk_level == "high"),
            input_schema=spec.inputs,
            output_schema=spec.outputs,
            default_timeout=float(spec.execution_limits.timeout_seconds),
            max_timeout=30.0,
            supports_idempotency=True,
        )

    @property
    def contract(self) -> ToolContract:
        return self._contract

    def run(self, context: ToolExecutionContext, **parameters: Any) -> Any:
        """
        Executes the dynamic capability within the contained sandbox, enforcing
        tenant scoping and input validation against the verified specification.
        """
        if context.tenant_id != self.tenant_id:
            raise PermissionError(
                f"Cross-tenant execution denied: tool belongs to tenant {self.tenant_id}"
            )

        exec_res = self.sandbox.run_code(self.implementation_code, input_data=parameters)
        if not exec_res.success:
            raise RuntimeError(exec_res.error or "Dynamic capability execution failed")

        return exec_res.output

    def execute(
        self,
        context_or_params: Any = None,
        **parameters: Any,
    ) -> StandardToolResult:
        """
        Flexible execution interface: accepts either (context, **params)
        or directly (params_dict) for direct test / script invocations.
        """
        if isinstance(context_or_params, ToolExecutionContext):
            return super().execute(context_or_params, **parameters)
        elif isinstance(context_or_params, dict):
            params = dict(context_or_params)
            params.update(parameters)
            ctx = ToolExecutionContext(tenant_id=self.tenant_id, agent_id=None)
            return super().execute(ctx, **params)
        else:
            ctx = ToolExecutionContext(tenant_id=self.tenant_id, agent_id=None)
            return super().execute(ctx, **parameters)
