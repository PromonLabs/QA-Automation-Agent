$ROOT     = Split-Path -Parent $MyInvocation.MyCommand.Path
$BACKEND  = "$ROOT\backend"
$FRONTEND = "$ROOT\frontend"
$PYTHON   = "$BACKEND\venv\Scripts\python.exe"
$PIP      = "$BACKEND\venv\Scripts\pip.exe"

Write-Host "=== QA Automation Agent ===" -ForegroundColor Cyan
Write-Host "Backend  : http://localhost:8000"
Write-Host "Frontend : http://localhost:3001"
Write-Host ""

# ── Install backend deps if needed ───────────────────────────────────────────
Write-Host "[setup] Checking backend dependencies..." -ForegroundColor Yellow
& $PIP install -r "$BACKEND\requirements.txt" -q --disable-pip-version-check
Write-Host "[setup] Done." -ForegroundColor Green
Write-Host ""

# ── Start backend as a background job ────────────────────────────────────────
Write-Host "[backend] Starting FastAPI..." -ForegroundColor Yellow
$backendJob = Start-Job -Name "Backend" -ScriptBlock {
    param($backendPath, $python)
    Set-Location $backendPath
    & $python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload 2>&1
} -ArgumentList $BACKEND, $PYTHON

Start-Sleep 3

# ── Start frontend in foreground (Ctrl+C stops both) ─────────────────────────
Write-Host "[frontend] Starting Next.js..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Open: http://localhost:3001" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop everything." -ForegroundColor Gray
Write-Host ""

# Stream backend logs alongside frontend
$null = Register-EngineEvent -SourceIdentifier "Stopping" -Action {
    Write-Host "`n[stop] Stopping backend..." -ForegroundColor Red
    Stop-Job -Name "Backend" -ErrorAction SilentlyContinue
    Remove-Job -Name "Backend" -ErrorAction SilentlyContinue
}

try {
    # Show backend output in real time alongside frontend
    $backendTimer = [System.Diagnostics.Stopwatch]::StartNew()

    Set-Location $FRONTEND
    $frontendProcess = Start-Process -FilePath "npm" -ArgumentList "run", "dev", "--", "--port", "3001" -PassThru -NoNewWindow

    while (-not $frontendProcess.HasExited) {
        # Flush backend job output
        $output = Receive-Job -Name "Backend" -ErrorAction SilentlyContinue
        foreach ($line in $output) {
            Write-Host "[backend] $line" -ForegroundColor DarkCyan
        }
        Start-Sleep -Milliseconds 500
    }
}
finally {
    Write-Host "`n[stop] Stopping backend..." -ForegroundColor Red
    Stop-Job -Name "Backend" -ErrorAction SilentlyContinue
    Remove-Job -Name "Backend" -ErrorAction SilentlyContinue
}
