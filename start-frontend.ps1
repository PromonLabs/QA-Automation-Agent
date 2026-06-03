Set-Location $PSScriptRoot\frontend
if (-not (Test-Path "node_modules")) { npm install }
Write-Host "Starting frontend on http://localhost:3000 ..." -ForegroundColor White
npm run dev
