Set-Location $PSScriptRoot\backend

if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor White
    python -m venv venv
}

Write-Host "Installing dependencies..." -ForegroundColor Gray
& venv\Scripts\pip.exe install -r requirements.txt -q

if (-not (Test-Path ".env")) { Copy-Item .env.example .env }

# Install Chromium if missing
$chromiumOk = & venv\Scripts\python.exe -c @'
import os
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        exe = p.chromium.executable_path
        print("ok" if exe and os.path.exists(exe) else "missing")
except:
    print("missing")
'@ 2>&1

if ($chromiumOk -ne "ok") {
    Write-Host "`n  Chromium not found - installing now..." -ForegroundColor White
    & venv\Scripts\python.exe -m playwright install chromium
    Write-Host "  Chromium installed [OK]" -ForegroundColor White
} else {
    Write-Host "  Chromium ready [OK]" -ForegroundColor Gray
}

Write-Host "`n  Starting backend -> http://localhost:8000" -ForegroundColor White
Write-Host "  (BrowserAgent auto-uses ProactorEventLoop thread on Windows)" -ForegroundColor Gray
Write-Host ""
Write-Host "  TIP: To run a flow directly (faster, no UI):" -ForegroundColor Gray
Write-Host "       venv\Scripts\python.exe run.py" -ForegroundColor Gray
Write-Host ""

& venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
