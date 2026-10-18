from __future__ import annotations

from abc import ABC, abstractmethod
import time
from typing import Any

from pydantic import ValidationError

from packages.tools.contract import (
    StandardToolResult,
    ToolContract,
    ToolExecutionContext,
)


class BaseRealTool(ABC):
    """
    Abstract base class for all production-grade tools.
    Encapsulates validation, execution, error categorization, and metrics.
    """

    @property
    @abstractmethod
    def contract(self) -> ToolContract:
        """The formal contract defining this tool."""
        raise NotImplementedError

    @abstractmethod
    def run(self, context: ToolExecutionContext, **parameters: Any) -> Any:
        """Core tool logic to be implemented by concrete tools."""
        raise NotImplementedError

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Validate input parameters against contract or override in subclass."""
        return parameters

    def execute(
        self,
        context: ToolExecutionContext,
        **parameters: Any,
    ) -> StandardToolResult:
        """
        Execute tool with parameter validation, execution timing, and exception safety.
        """
        start_time = time.perf_counter()
        try:
            validated_params = self.validate_parameters(parameters)
            output = self.run(context, **validated_params)
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return StandardToolResult(
                success=True,
                data=output,
                latency_ms=duration_ms,
                metadata={
                    "tool_slug": self.contract.slug,
                    "tenant_id": str(context.tenant_id),
                },
            )
        except ValidationError as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return StandardToolResult(
                success=False,
                error=f"Invalid tool arguments: {str(exc)}",
                error_code="VALIDATION_ERROR",
                latency_ms=duration_ms,
                metadata={"tool_slug": self.contract.slug},
            )
        except TimeoutError as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return StandardToolResult(
                success=False,
                error=f"Tool execution timed out: {str(exc)}",
                error_code="TIMEOUT",
                latency_ms=duration_ms,
                metadata={"tool_slug": self.contract.slug},
            )
        except PermissionError as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return StandardToolResult(
                success=False,
                error=f"Permission denied: {str(exc)}",
                error_code="PERMISSION_DENIED",
                latency_ms=duration_ms,
                metadata={"tool_slug": self.contract.slug},
            )
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return StandardToolResult(
                success=False,
                error=str(exc),
                error_code=type(exc).__name__,
                latency_ms=duration_ms,
                metadata={"tool_slug": self.contract.slug},
            )
