# scripts/test-dashboard-report.ps1
$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $python scripts/test_dashboard_runner.py --suite report
exit $LASTEXITCODE
