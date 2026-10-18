from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.memory.sanitizer import MemorySanitizer

logger = logging.getLogger(__name__)


@dataclass
class SandboxExecutionResult:
    success: bool
    exit_code: int
    output: Any
    stdout: str
    stderr: str
    execution_time_ms: int
    timed_out: bool = False
    is_containerized: bool = False
    error: str | None = None


class ExecutionSandbox:
    """
    Isolated execution sandbox for developing and testing dynamic capabilities.
    Enforces time limits, output limits, workspace containment, host secret stripping,
    and temporary workspace cleanup.
    Supports both real Docker container execution (--network none) and sanitized subprocesses.
    """

    SAFE_ENV_VARS = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "PYTHONIOENCODING",
    }

    HOST_SECRET_DENYLIST = {
        "DATABASE_URL",
        "POSTGRES_PASSWORD",
        "POSTGRES_USER",
        "JWT_SECRET_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "SLACK_BOT_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "ENCRYPTION_MASTER_KEY",
    }

    _docker_cached_status: bool | None = None

    def __init__(
        self,
        timeout_seconds: int = 10,
        max_output_chars: int = 25000,
        backend: str = "auto",
        container_image: str = "ai-employee-platform-agent:latest",
    ):
        self.timeout_seconds = max(1, min(30, timeout_seconds))
        self.max_output_chars = max(1000, min(50000, max_output_chars))
        self.backend = backend.lower().strip()
        self.container_image = container_image

    @classmethod
    def check_docker_available(cls, force_refresh: bool = False) -> bool:
        """Check if Docker daemon is accessible for containerized sandboxing."""
        if not force_refresh and cls._docker_cached_status is not None:
            return cls._docker_cached_status
        try:
            res = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
            )
            cls._docker_cached_status = (res.returncode == 0)
        except Exception:
            cls._docker_cached_status = False
        return cls._docker_cached_status

    @property
    def is_containerized(self) -> bool:
        """
        Returns True ONLY if the sandbox actually executes within a verified,
        accessible container runtime (e.g. Docker daemon is responsive).
        Never returns True as a nominal flag if Docker is unreachable.
        """
        if self.backend == "subprocess":
            return False
        return self.check_docker_available()

    def _build_sanitized_environment(self) -> dict[str, str]:
        """Strip host secrets and sensitive configuration from the child process environment."""
        env: dict[str, str] = {}
        for k, v in os.environ.items():
            k_upper = k.upper().strip()
            if k_upper in self.HOST_SECRET_DENYLIST:
                continue
            if any(s in k_upper for s in ("SECRET", "KEY", "TOKEN", "PASS", "CREDENTIAL")):
                continue
            if k in self.SAFE_ENV_VARS:
                env[k] = v

        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = ""  # Strictly isolate from host application python packages
        return env

    def execute(
        self,
        code: str,
        inputs: dict[str, Any] | None = None,
    ) -> SandboxExecutionResult:
        """Alias for run_code."""
        return self.run_code(code, input_data=inputs)

    def run_code(
        self,
        code: str,
        input_data: dict[str, Any] | None = None,
    ) -> SandboxExecutionResult:
        """
        Executes Python code in a contained temporary workspace, passes JSON inputs,
        captures structured outputs, and purges workspace upon completion.
        """
        temp_dir = tempfile.mkdtemp(prefix="sandboxed_cap_")
        workspace = Path(temp_dir)
        start_time = time.perf_counter()

        try:
            # 1. Prepare isolated workspace files
            script_path = workspace / "capability_runner.py"
            input_file = workspace / "input.json"
            output_file = workspace / "output.json"

            input_payload = input_data or {}
            input_file.write_text(json.dumps(input_payload, default=str), encoding="utf-8")

            # 2. Wrapper script that executes user code and writes json result
            wrapper_code = f"""
import json
import sys

def _run():
    with open("input.json", "r", encoding="utf-8") as f:
        inputs = json.load(f)

    # Injected capability code
{self._indent_code(code, spaces=4)}

    # Expecting the code to define 'run(inputs)', 'execute_capability(inputs)', 'execute(inputs)', or assign 'result'
    if "run" in locals() and callable(locals()["run"]):
        res = locals()["run"](inputs)
    elif "execute_capability" in locals() and callable(locals()["execute_capability"]):
        res = locals()["execute_capability"](inputs)
    elif "execute" in locals() and callable(locals()["execute"]):
        res = locals()["execute"](inputs)
    elif "result" in locals():
        res = locals()["result"]
    else:
        res = {{"status": "ok", "message": "Code executed without explicit result"}}

    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(res, f, default=str)

if __name__ == "__main__":
    try:
        _run()
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
"""
            script_path.write_text(wrapper_code, encoding="utf-8")

            # Determine execution backend
            docker_ready = self.check_docker_available()
            if self.backend == "docker" and not docker_ready:
                raise RuntimeError(
                    "Explicit Docker container execution requested, but Docker daemon is not accessible."
                )
            use_docker = (self.backend in ("docker", "auto")) and docker_ready

            if use_docker:
                # 3a. Execute in Docker with strict security constraints and no network
                clean_host_path = str(workspace).replace("\\", "/")
                docker_cmd = [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--memory",
                    "256m",
                    "--cpus",
                    "0.5",
                    "--pids-limit",
                    "64",
                    "--security-opt",
                    "no-new-privileges",
                    "-v",
                    f"{clean_host_path}:/sandbox",
                    "-w",
                    "/sandbox",
                    self.container_image,
                    "python",
                    "capability_runner.py",
                ]
                process = subprocess.Popen(
                    docker_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )
            else:
                # 3b. Fallback to host subprocess with sanitized environment and empty PYTHONPATH
                env = self._build_sanitized_environment()
                process = subprocess.Popen(
                    [sys.executable, str(script_path)],
                    cwd=str(workspace),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )

            try:
                stdout, stderr = process.communicate(timeout=self.timeout_seconds)
                timed_out = False
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                timed_out = True
                exit_code = -1

            elapsed_ms = int((time.perf_counter() - start_time) * 1000)

            clean_stdout = self._sanitize_and_truncate(stdout)
            clean_stderr = self._sanitize_and_truncate(stderr)

            if timed_out:
                return SandboxExecutionResult(
                    success=False,
                    exit_code=exit_code,
                    output=None,
                    stdout=clean_stdout,
                    stderr=clean_stderr,
                    execution_time_ms=elapsed_ms,
                    timed_out=True,
                    is_containerized=use_docker,
                    error=f"Execution timed out after {self.timeout_seconds} seconds",
                )

            if exit_code != 0:
                return SandboxExecutionResult(
                    success=False,
                    exit_code=exit_code,
                    output=None,
                    stdout=clean_stdout,
                    stderr=clean_stderr,
                    execution_time_ms=elapsed_ms,
                    is_containerized=use_docker,
                    error=f"Process exited with non-zero code {exit_code}: {clean_stderr[:500]}",
                )

            # Parse structured result from output.json
            if output_file.exists():
                try:
                    result_data = json.loads(output_file.read_text(encoding="utf-8"))
                except Exception as exc:
                    return SandboxExecutionResult(
                        success=False,
                        exit_code=exit_code,
                        output=None,
                        stdout=clean_stdout,
                        stderr=clean_stderr,
                        execution_time_ms=elapsed_ms,
                        is_containerized=use_docker,
                        error=f"Failed to parse capability output JSON: {str(exc)}",
                    )
            else:
                result_data = {"raw_output": clean_stdout}

            return SandboxExecutionResult(
                success=True,
                exit_code=0,
                output=result_data,
                stdout=clean_stdout,
                stderr=clean_stderr,
                execution_time_ms=elapsed_ms,
                is_containerized=use_docker,
            )

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            return SandboxExecutionResult(
                success=False,
                exit_code=1,
                output=None,
                stdout="",
                stderr=str(exc),
                execution_time_ms=elapsed_ms,
                is_containerized=False,
                error=f"Sandbox execution error: {str(exc)}",
            )
        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as exc:
                logger.warning("Failed to clean sandbox workspace %s: %s", temp_dir, exc)

    def _sanitize_and_truncate(self, text: str | None) -> str:
        if not text:
            return ""
        truncated = text[:self.max_output_chars]
        if len(text) > self.max_output_chars:
            truncated += "\n[OUTPUT_TRUNCATED_MAX_LIMIT_EXCEEDED]"
        return MemorySanitizer.mask_secrets(truncated)

    @staticmethod
    def _indent_code(code: str, spaces: int = 4) -> str:
        prefix = " " * spaces
        return "\n".join(prefix + line if line.strip() else "" for line in code.splitlines())
