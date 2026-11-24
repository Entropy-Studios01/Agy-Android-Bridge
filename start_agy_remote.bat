@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PORT=8765"
set "WORK_DIR=%CD%"
if not "%~1"=="" if not "%~1"=="--tunnel" set "WORK_DIR=%~1"

if not exist ".venv\Scripts\python.exe" (
    echo [AGY Remote] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Python 3.10+ is required and must be on PATH.
        pause
        exit /b 1
    )
    echo [AGY Remote] Installing dependencies...
    .venv\Scripts\python.exe -m pip install --upgrade pip >nul
    .venv\Scripts\pip.exe install -r requirements.txt
)

if /I "%~1"=="--tunnel" (
    where cloudflared >nul 2>&1
    if errorlevel 1 (
        echo [WARN] cloudflared not found. Install it via: winget install Cloudflare.cloudflared
    ) else (
        echo [AGY Remote] Launching Cloudflare Quick Tunnel in a separate window...
        start "AGY Remote Tunnel" cmd /k "cloudflared tunnel --url http://127.0.0.1:%PORT%"
    )
)

echo [AGY Remote] Starting bridge on port %PORT% (cwd: %WORK_DIR%)...
.venv\Scripts\python.exe server.py --port %PORT% --cwd "%WORK_DIR%"
pause
