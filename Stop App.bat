@echo off
title Case Management System - Stopping...
echo.
echo  ============================================
echo   Stopping the Case Management System...
echo  ============================================
echo.

cd /d "%~dp0"

:: Find python process listening on port 5000 and stop it
set FOUND=0
for /f "tokens=5" %%p in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":5000 "') do (
    taskkill /PID %%p /F >nul 2>&1
    if not errorlevel 1 set FOUND=1
)

if %FOUND%==1 (
    echo.
    echo  App has been stopped successfully.
) else (
    echo.
    echo  App was not running.
)

echo.
echo  ============================================
echo  You can close this window.
echo  To start the app again, double-click "Start App.bat"
echo.
pause
