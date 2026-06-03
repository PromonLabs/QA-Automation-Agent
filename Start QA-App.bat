@echo off
title AutoAgent - QA App Launcher
color 0F

echo.
echo  =============================================
echo   AutoAgent -- AI Browser Automation Platform
echo  =============================================
echo.

set "APP_DIR=C:\Users\Sandhosh\Desktop\QA-App"

:: Check if backend folder exists
if not exist "%APP_DIR%\backend\venv\Scripts\uvicorn.exe" (
    echo  [ERROR] Backend venv not found. Run start.ps1 once first to set up.
    pause
    exit /b 1
)

:: Check if frontend node_modules exists
if not exist "%APP_DIR%\frontend\node_modules" (
    echo  [INFO] Installing frontend packages for the first time...
    cd /d "%APP_DIR%\frontend"
    call npm install
)

echo  [1/3] Starting Backend  --  http://localhost:8000
start "QA-App Backend" cmd /k "cd /d "%APP_DIR%\backend" && venv\Scripts\uvicorn.exe app.main:app --reload --port 8000"

echo  [2/3] Starting Frontend --  http://localhost:3000
start "QA-App Frontend" cmd /k "cd /d "%APP_DIR%\frontend" && npm run dev"

echo  [3/3] Opening browser in 8 seconds (waiting for servers to start)...
timeout /t 8 /nobreak >nul

start "" "http://localhost:3000"

echo.
echo  =============================================
echo   Both servers are running!
echo   Frontend  ->  http://localhost:3000
echo   Backend   ->  http://localhost:8000
echo   API Docs  ->  http://localhost:8000/docs
echo   Login     ->  admin / admin123
echo  =============================================
echo.
echo  Close the two server windows to stop the app.
echo.
pause
