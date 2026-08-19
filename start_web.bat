@echo off
title SWBAK Web Server - Launcher
cd /d "%~dp0"

echo ============================================
echo    SWBAK Web Server - One Click Start
echo ============================================
echo.

REM 1. Find Python (try python / python3 / py)
echo [1/3] Checking Python...
set "PYCMD="
python --version >nul 2>&1 && set "PYCMD=python"
if not defined PYCMD (
    python3 --version >nul 2>&1 && set "PYCMD=python3"
)
if not defined PYCMD (
    py --version >nul 2>&1 && set "PYCMD=py"
)
if not defined PYCMD (
    echo [ERROR] Python not found. Please install Python 3.8+
    echo Download: https://www.python.org/downloads/
    echo Remember to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('%PYCMD% --version 2^>^&1') do set PYVER=%%v
echo Found Python %PYVER%  ^(command: %PYCMD%^)
echo.

REM 2. Install dependencies
echo [2/3] Installing dependencies...
%PYCMD% -m pip install --upgrade pip >nul 2>&1
%PYCMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency install failed. Please run manually:
    echo        %PYCMD% -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo.
echo Dependencies ready.
echo.

REM 3. Run web server
echo [3/3] Starting web server...
echo ============================================
echo.
echo   URL: http://localhost:5000
echo   Press Ctrl+C to stop.
echo.
echo ============================================
echo.

REM Open browser after short delay (in background)
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:5000"

%PYCMD% web_app.py
if errorlevel 1 (
    echo.
    echo [Server exited with error] code: %errorlevel%
    echo.
    pause
)

exit /b 0
