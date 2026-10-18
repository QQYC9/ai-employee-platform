from __future__ import annotations

import ast
import logging
from typing import Any

from packages.memory.sanitizer import MemorySanitizer
from packages.self_development.sandbox import ExecutionSandbox
from packages.self_development.specification import CapabilitySpecification

logger = logging.getLogger(__name__)


class CapabilitySecurityVerifier:
    """
    Automated security verification and test harness for dynamic capabilities.
    Combines static AST analysis, secrets scanning, and isolated test execution.
    """

    # Whitelist of safe modules permitted for pure computational capabilities
    ALLOWED_MODULES = {
        "math",
        "json",
        "re",
        "datetime",
        "decimal",
        "fractions",
        "statistics",
        "random",
        "hashlib",
        "base64",
        "collections",
        "itertools",
        "functools",
        "typing",
        "string",
        "copy",
        "bisect",
        "heapq",
        "uuid",
    }

    FORBIDDEN_CALLS = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "breakpoint",
        "input",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
    }

    FORBIDDEN_ATTRIBUTES = {
        "__subclasses__",
        "__bases__",
        "__base__",
        "__mro__",
        "__globals__",
        "__code__",
        "__class__",
        "__dict__",
        "__reduce__",
        "__reduce_ex__",
        "__builtins__",
        "system",
        "popen",
        "spawn",
        "kill",
        "remove",
        "rmdir",
        "unlink",
        "rename",
        "replace",
        "chmod",
        "chown",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
    }

    def __init__(self, sandbox: ExecutionSandbox | None = None):
        self.sandbox = sandbox or ExecutionSandbox()

    def static_analysis(self, code: str) -> dict[str, Any]:
        """
        Parses code into an AST and analyzes for dangerous operations, forbidden modules,
        and embedded credentials.
        """
        violations: list[str] = []

        # 1. Secret scanning
        try:
            MemorySanitizer.scan_for_secrets(code)
        except Exception as exc:
            violations.append(f"Secret or credential detected in source code: {str(exc)}")

        # 2. AST parsing
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return {
                "valid": False,
                "error": f"SyntaxError in capability implementation code: {str(exc)}",
                "violations": ["Code fails Python syntax validation"],
            }

        # 3. AST Walker
        for node in ast.walk(tree):
            # Check module imports against strict computational allowlist
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_mod = alias.name.split(".")[0].lower()
                    if top_mod not in self.ALLOWED_MODULES:
                        violations.append(f"Import of forbidden dangerous module: '{alias.name}'")

            elif isinstance(node, ast.ImportFrom):
                top_mod = (node.module or "").split(".")[0].lower()
                if top_mod not in self.ALLOWED_MODULES:
                    violations.append(f"Import from forbidden dangerous module: '{node.module}'")

            # Check calls
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in self.FORBIDDEN_CALLS:
                    violations.append(f"Call to forbidden built-in function: '{func.id}'")

            # Check attribute access (both in calls and expressions)
            elif isinstance(node, ast.Attribute):
                attr_name = node.attr.lower()
                if attr_name in self.FORBIDDEN_ATTRIBUTES:
                    violations.append(f"Call to dangerous OS operation: '{node.attr}'")

        is_clean = len(violations) == 0
        return {
            "valid": is_clean,

            "violations": violations,
        }

    def verify_ast(self, code: str) -> dict[str, Any]:
        """Alias for static_analysis."""
        return self.static_analysis(code)

    def run_acceptance_tests(
        self,
        code: str,
        spec: CapabilitySpecification,
    ) -> dict[str, Any]:
        """
        Executes capability test cases defined in the specification inside the sandbox.
        """
        test_results = []
        passed_count = 0
        failed_count = 0

        test_cases = spec.acceptance_tests or [
            {
                "name": "default_smoke_test",
                "input": {},
                "expect_success": True,
            }
        ]

        sandbox = ExecutionSandbox(
            timeout_seconds=spec.execution_limits.timeout_seconds,
            max_output_chars=spec.execution_limits.max_output_chars,
        )

        for idx, tc in enumerate(test_cases, start=1):
            tc_name = tc.get("name", f"test_case_{idx}")
            tc_input = tc.get("input", {})
            expect_success = tc.get("expect_success", True)
            expected = tc.get("expected")
            expected_keys = tc.get("expected_keys", [])

            run_res = sandbox.run_code(code, input_data=tc_input)

            case_passed = True
            failure_reason = None

            if expect_success and not run_res.success:
                case_passed = False
                failure_reason = f"Test failed with error: {run_res.error}"
            elif not expect_success and run_res.success:
                case_passed = False
                failure_reason = "Test expected failure, but code succeeded unexpectedly"
            elif run_res.success and expected is not None:
                if isinstance(expected, dict) and isinstance(run_res.output, dict):
                    for exp_k, exp_v in expected.items():
                        if exp_k not in run_res.output or run_res.output[exp_k] != exp_v:
                            case_passed = False
                            failure_reason = f"Expected {exp_k}={exp_v}, got {run_res.output.get(exp_k)}"
                            break
                elif run_res.output != expected:
                    case_passed = False
                    failure_reason = f"Expected {expected}, got {run_res.output}"
            elif run_res.success and expected_keys and isinstance(run_res.output, dict):
                for k in expected_keys:
                    if k not in run_res.output:
                        case_passed = False
                        failure_reason = f"Output missing expected key '{k}'"
                        break


            if case_passed:
                passed_count += 1
            else:
                failed_count += 1

            test_results.append({
                "test_name": tc_name,
                "passed": case_passed,
                "execution_time_ms": run_res.execution_time_ms,
                "failure_reason": failure_reason,
            })

        all_passed = failed_count == 0 and len(test_results) > 0
        return {
            "all_passed": all_passed,
            "total_tests": len(test_results),
            "passed_tests": passed_count,
            "failed_tests": failed_count,
            "details": test_results,
        }

    def full_verification(
        self,
        code: str,
        spec: CapabilitySpecification,
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        """
        Runs both static analysis and sandboxed test execution.
        Returns: (overall_success, test_summary, security_verdict)
        """
        # 1. Static security analysis
        static_res = self.static_analysis(code)
        security_verdict = {
            "ast_analysis": "passed" if static_res.get("valid") else "failed",
            "violations": static_res.get("violations", []),
            "secrets_scanned": True,
            "sandbox_isolated": True,
        }

        if not static_res.get("valid"):
            test_summary = {
                "all_passed": False,
                "total_tests": 0,
                "passed_tests": 0,
                "failed_tests": 1,
                "error": "Code failed static security analysis, test execution halted",
            }
            return False, test_summary, security_verdict

        # 2. Dynamic sandboxed tests
        test_summary = self.run_acceptance_tests(code, spec)
        overall_success = test_summary.get("all_passed", False)

        return overall_success, test_summary, security_verdict
