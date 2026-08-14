@echo off
title Switch Backup Tool - Launcher
cd /d "%~dp0"

echo ============================================
echo    Switch Backup Tool - One Click Start
echo ============================================
echo.

REM 1. Check Python
echo [1/3] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.8+
    echo Download: https://www.python.org/downloads/
    echo Remember to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo Found Python %PYVER%
echo.

REM 2. Install dependencies
echo [2/3] Installing dependencies...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency install failed. Please run manually:
    echo        pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo.
echo Dependencies ready.
echo.

REM 3. Run main app
echo [3/3] Starting application...
echo ============================================
echo.
python main.py
if errorlevel 1 (
    echo.
    echo [App exited with error] code: %errorlevel%
    echo.
    pause
)

exit /b 0
