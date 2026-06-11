# ── Local Development Startup ─────────────────────────────────────────────────
# Run this on your Windows machine: .\start-local.ps1

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKEND  = "$ROOT\backend"
$FRONTEND = "$ROOT\frontend"

Write-Host "=== QA Automation Agent - Local Dev ===" -ForegroundColor Cyan
Write-Host "Backend  : http://localhost:8000"
Write-Host "Frontend : http://localhost:3001"
Write-Host ""

# Start backend
Write-Host "[backend]  Starting FastAPI..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$BACKEND'; python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

Start-Sleep 2

# Start frontend
Write-Host "[frontend] Starting Next.js..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$FRONTEND'; npm run dev -- --port 3001"

Write-Host ""
Write-Host "Open: http://localhost:3001" -ForegroundColor Green
