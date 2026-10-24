# scripts/test-dashboard-pages.ps1
param([string]$Suite = "pages")
$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $python scripts/test_dashboard_runner.py --suite $Suite
exit $LASTEXITCODE
