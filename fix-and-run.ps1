Write-Host "`n🔧 AutoAgent — Fix & Run Script" -ForegroundColor White
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray

Set-Location $PSScriptRoot\backend

# Create venv if needed
if (-not (Test-Path "venv")) {
    Write-Host "`n[1] Creating Python venv..." -ForegroundColor White
    python -m venv venv
} else {
    Write-Host "`n[1] Venv exists ✓" -ForegroundColor Gray
}

# Install requirements
Write-Host "[2] Installing Python packages..." -ForegroundColor White
& venv\Scripts\pip.exe install -r requirements.txt -q
Write-Host "    Done ✓" -ForegroundColor Gray

# Install Playwright + Chromium
Write-Host "[3] Installing Playwright Chromium browser..." -ForegroundColor White
& venv\Scripts\python.exe -m playwright install chromium
Write-Host "    Done ✓" -ForegroundColor Gray

# Copy .env
if (-not (Test-Path ".env")) { Copy-Item .env.example .env }

# Verify Chromium
Write-Host "[4] Verifying Chromium install..." -ForegroundColor White
$check = & venv\Scripts\python.exe -c @'
import sys, asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from playwright.sync_api import sync_playwright
import os
with sync_playwright() as p:
    exe = p.chromium.executable_path
    exists = os.path.exists(exe)
    print(f"  Chromium: {exe}")
    print(f"  Exists: {exists}")
'@
Write-Host $check -ForegroundColor White

# Verify ProactorEventLoop will be used
Write-Host "[5] Checking event loop policy..." -ForegroundColor White
$loop = & venv\Scripts\python.exe -c @'
import sys, asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
loop = asyncio.new_event_loop()
print(f"  Loop type: {type(loop).__name__}")
loop.close()
'@
Write-Host $loop -ForegroundColor White

Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
Write-Host "  All checks done. Starting backend..." -ForegroundColor White
Write-Host "  Backend → http://localhost:8000" -ForegroundColor White
Write-Host "  API docs → http://localhost:8000/docs" -ForegroundColor White
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`n" -ForegroundColor Gray

# Launch using run.py (sets ProactorEventLoop before uvicorn)
& venv\Scripts\python.exe run.py
