Write-Host "`n🤖 AutoAgent — AI Browser Automation Platform" -ForegroundColor White
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray

# Check Ollama
Write-Host "`n[1/4] Checking Ollama..." -ForegroundColor Gray
try {
    $r = Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 5
    Write-Host "      ✓ Ollama is running" -ForegroundColor White
    $models = $r.models | ForEach-Object { $_.name }
    if ("qwen2.5:14b" -in $models) {
        Write-Host "      ✓ qwen2.5:14b found" -ForegroundColor White
    } else {
        Write-Host "      ⚠ qwen2.5:14b not found - run: ollama pull qwen2.5:14b" -ForegroundColor Gray
    }
} catch {
    Write-Host "      ✗ Ollama not running - start it with: ollama serve" -ForegroundColor Gray
}

# Setup backend
Write-Host "`n[2/4] Setting up backend..." -ForegroundColor Gray
Set-Location backend
if (-not (Test-Path "venv")) {
    python -m venv venv
    Write-Host "      ✓ Virtual environment created" -ForegroundColor White
}
& venv\Scripts\pip.exe install -r requirements.txt -q
Write-Host "      ✓ Dependencies installed" -ForegroundColor White
try {
    & venv\Scripts\playwright.exe install chromium 2>&1 | Out-Null
    Write-Host "      ✓ Chromium installed" -ForegroundColor White
} catch {}
if (-not (Test-Path ".env")) { Copy-Item .env.example .env }

# Start backend in background
Write-Host "`n[3/4] Starting backend (http://localhost:8000)..." -ForegroundColor Gray
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; venv\Scripts\uvicorn app.main:app --reload --port 8000" -PassThru | Out-Null
Start-Sleep 2
Write-Host "      ✓ Backend starting..." -ForegroundColor White
Set-Location ..

# Setup & start frontend
Write-Host "`n[4/4] Setting up frontend (http://localhost:3000)..." -ForegroundColor Gray
Set-Location frontend
if (-not (Test-Path "node_modules")) {
    Write-Host "      Installing npm packages (this may take a minute)..." -ForegroundColor Gray
    npm install --silent
}
Write-Host "      ✓ Starting Next.js dev server..." -ForegroundColor White
Set-Location ..

Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
Write-Host "  Frontend  → http://localhost:3000" -ForegroundColor White
Write-Host "  Backend   → http://localhost:8000" -ForegroundColor White
Write-Host "  API Docs  → http://localhost:8000/docs" -ForegroundColor White
Write-Host "  Login     → admin / admin123" -ForegroundColor White
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`n" -ForegroundColor Gray

Set-Location frontend
npm run dev
