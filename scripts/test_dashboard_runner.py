#!/usr/bin/env python3
"""
Autonomous Dashboard Test Runner for AI Employee Platform.
Executes automated unattended verification of frontend dashboard pages, routes,
authentication flows, and interaction states, producing structured artifacts and reports.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = WORKSPACE_ROOT / "artifacts" / "dashboard-reports"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# Discovered Route Inventory
TENANT_ROUTES = [
    {"path": "/login", "name": "Login Page", "auth_required": False, "role": "public"},
    {"path": "/", "name": "Overview Dashboard", "auth_required": True, "role": "tenant_user"},
    {"path": "/agents", "name": "Digital Employees", "auth_required": True, "role": "tenant_user"},
    {"path": "/tasks", "name": "Tasks Registry", "auth_required": True, "role": "tenant_user"},
    {"path": "/channels", "name": "Omni-Channels", "auth_required": True, "role": "tenant_user"},
    {"path": "/campaigns", "name": "Campaigns & Proactive Notifications", "auth_required": True, "role": "tenant_user"},
    {"path": "/usage", "name": "AI Usage & Budget", "auth_required": True, "role": "tenant_user"},
    {"path": "/settings", "name": "Company Business Brain Settings", "auth_required": True, "role": "tenant_owner"},
]

ADMIN_ROUTES = [
    {"path": "/login", "name": "Platform Admin Login", "auth_required": False, "role": "public"},
    {"path": "/", "name": "Platform Overview", "auth_required": True, "role": "superadmin"},
    {"path": "/tenants", "name": "Tenants Directory", "auth_required": True, "role": "superadmin"},
    {"path": "/agents-tasks", "name": "Global Agents & Tasks", "auth_required": True, "role": "superadmin"},
    {"path": "/monitoring", "name": "System Monitoring & Metrics", "auth_required": True, "role": "superadmin"},
    {"path": "/integrations", "name": "Platform Integrations", "auth_required": True, "role": "superadmin"},
    {"path": "/settings", "name": "Platform Settings", "auth_required": True, "role": "superadmin"},
]


def run_command(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str, str]:
    """Execute shell command with bounded timeout and capture stdout/stderr."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd or WORKSPACE_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=True if os.name == "nt" else False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"Command timed out after {timeout} seconds: {' '.join(cmd)}"
    except Exception as exc:
        return 1, "", str(exc)


def test_build(app_dir: str) -> dict[str, Any]:
    """Test TypeScript compilation and Vite build bundle integrity."""
    full_path = WORKSPACE_ROOT / "apps" / app_dir
    start_time = time.time()
    code, out, err = run_command(["npm", "run", "build"], cwd=full_path, timeout=120)
    duration = time.time() - start_time

    return {
        "name": f"Build & Typecheck: {app_dir}",
        "passed": code == 0,
        "exit_code": code,
        "duration_seconds": round(duration, 2),
        "stdout": out[-1000:] if out else "",
        "error": err[-1000:] if err and code != 0 else None,
    }


def test_vitest_suite(app_dir: str, pattern: str | None = None) -> dict[str, Any]:
    """Run Vitest unattended component/E2E test suite."""
    full_path = WORKSPACE_ROOT / "apps" / app_dir
    cmd = ["npm", "run", "test"]
    if pattern:
        cmd.extend(["--", pattern])

    start_time = time.time()
    code, out, err = run_command(cmd, cwd=full_path, timeout=180)
    duration = time.time() - start_time

    return {
        "name": f"Component & Interaction Tests: {app_dir}" + (f" ({pattern})" if pattern else ""),
        "passed": code == 0,
        "exit_code": code,
        "duration_seconds": round(duration, 2),
        "stdout": out[-1500:] if out else "",
        "error": err[-1500:] if err and code != 0 else None,
    }


def verify_route_definitions(app_name: str, app_file: Path, expected_routes: list[dict[str, Any]]) -> dict[str, Any]:
    """Inspects frontend router code to verify all routes and protection guards are wired."""
    start_time = time.time()
    if not app_file.exists():
        return {
            "name": f"Route Inventory Verification: {app_name}",
            "passed": False,
            "error": f"File not found: {app_file}",
        }

    content = app_file.read_text(encoding="utf-8")
    missing_routes = []
    for r in expected_routes:
        path = r["path"]
        if path == "/":
            if "index" not in content and 'path="/"' not in content:
                missing_routes.append(path)
        else:
            clean_path = path.lstrip("/")
            if f'path="{clean_path}"' not in content and f'path="{path}"' not in content:
                missing_routes.append(path)

    has_auth_guard = "ProtectedRoute" in content or "useAuth" in content
    passed = len(missing_routes) == 0 and has_auth_guard
    duration = time.time() - start_time

    return {
        "name": f"Route Inventory & Auth Guards: {app_name}",
        "passed": passed,
        "total_routes_checked": len(expected_routes),
        "missing_routes": missing_routes,
        "auth_guard_detected": has_auth_guard,
        "duration_seconds": round(duration, 3),
        "error": f"Missing routes: {missing_routes}" if missing_routes else None,
    }


def execute_suite(suite_type: str) -> dict[str, Any]:
    """Executes the requested test suite and compiles the complete report."""
    report: dict[str, Any] = {
        "suite": suite_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workspace": str(WORKSPACE_ROOT),
        "tests": [],
        "summary": {"total": 0, "passed": 0, "failed": 0},
    }

    tests: list[dict[str, Any]] = []

    # 1. Routes Inventory Check
    if suite_type in ("all", "routes", "smoke"):
        tests.append(verify_route_definitions("Tenant Dashboard", WORKSPACE_ROOT / "apps" / "tenant-dashboard" / "src" / "App.tsx", TENANT_ROUTES))
        tests.append(verify_route_definitions("Admin Dashboard", WORKSPACE_ROOT / "apps" / "admin-dashboard" / "src" / "App.tsx", ADMIN_ROUTES))

    # 2. Build Verification
    if suite_type in ("all", "smoke"):
        tests.append(test_build("tenant-dashboard"))
        tests.append(test_build("admin-dashboard"))

    # 3. Auth Tests
    if suite_type in ("all", "auth"):
        tests.append(test_vitest_suite("tenant-dashboard", "AuthContext"))
        tests.append(test_vitest_suite("admin-dashboard", "AuthContext"))

    # 4. Pages & Interactions E2E
    if suite_type in ("all", "pages"):
        tests.append(test_vitest_suite("tenant-dashboard", "tenant_e2e_scenarios"))
        tests.append(test_vitest_suite("admin-dashboard", "e2e_scenarios"))

    report["tests"] = tests
    report["summary"]["total"] = len(tests)
    report["summary"]["passed"] = sum(1 for t in tests if t.get("passed"))
    report["summary"]["failed"] = sum(1 for t in tests if not t.get("passed"))
    report["status"] = "PASSED" if report["summary"]["failed"] == 0 else "FAILED"

    # Write JSON and Markdown Artifacts
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = ARTIFACTS_DIR / f"dashboard_report_{timestamp_str}.json"
    latest_md_path = ARTIFACTS_DIR / "latest_dashboard_report.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    md_content = generate_markdown_report(report)
    with open(latest_md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"\nReport written to: {json_path}")
    print(f"Summary markdown written to: {latest_md_path}")
    print(f"Overall Status: {report['status']} ({report['summary']['passed']}/{report['summary']['total']} passed)")

    return report


def generate_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# Autonomous Dashboard Test Report",
        f"- **Suite**: `{report['suite']}`",
        f"- **Timestamp**: `{report['timestamp']}`",
        f"- **Overall Status**: **{report['status']}** ({report['summary']['passed']}/{report['summary']['total']} Passed)",
        "",
        "## Test Execution Summary",
        "| Test Name | Status | Duration (s) | Details |",
        "| :--- | :---: | :---: | :--- |",
    ]

    for t in report["tests"]:
        status_icon = "✅ PASSED" if t.get("passed") else "❌ FAILED"
        dur = t.get("duration_seconds", "-")
        detail = t.get("error") or "Clean execution"
        lines.append(f"| {t['name']} | {status_icon} | {dur} | {detail} |")

    lines.extend([
        "",
        "## Discovered Route Inventory Coverage",
        "### Tenant Dashboard (`apps/tenant-dashboard`)",
        "| Route | Page / Name | Auth Required | Role Scope |",
        "| :--- | :--- | :---: | :--- |",
    ])
    for r in TENANT_ROUTES:
        lines.append(f"| `{r['path']}` | {r['name']} | {'Yes' if r['auth_required'] else 'No'} | `{r['role']}` |")

    lines.extend([
        "",
        "### Admin Dashboard (`apps/admin-dashboard`)",
        "| Route | Page / Name | Auth Required | Role Scope |",
        "| :--- | :--- | :---: | :--- |",
    ])
    for r in ADMIN_ROUTES:
        lines.append(f"| `{r['path']}` | {r['name']} | {'Yes' if r['auth_required'] else 'No'} | `{r['role']}` |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Autonomous Dashboard Test Runner")
    parser.add_argument(
        "--suite",
        choices=["all", "smoke", "routes", "auth", "pages", "report"],
        default="all",
        help="Test suite to execute (default: all)",
    )
    args = parser.parse_args()
    suite = "all" if args.suite == "report" else args.suite
    report = execute_suite(suite)
    sys.exit(0 if report["status"] == "PASSED" else 1)


if __name__ == "__main__":
    main()
