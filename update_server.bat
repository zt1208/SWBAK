@echo off
chcp 65001 >nul 2>&1
title SWBAK - Sync code to server

echo ================================================
echo   SWBAK server update
echo   Target: 192.168.1.7  (auto package + upload + restart)
echo ================================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] python not found in PATH.
    pause
    exit /b 1
)

python "%~dp0_deploy\deploy.py"
set RC=%errorlevel%

echo.
if %RC% equ 0 (
    echo [OK] Update finished. Visit: http://192.168.1.7:5000
) else (
    echo [FAIL] Update failed. Check messages above.
)
pause
