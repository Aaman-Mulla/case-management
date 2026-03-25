@echo off
title Case Management System - Starting...
echo.
echo  ============================================
echo   Case Management System
echo   Office of the Registrar of Companies, Pune
echo  ============================================
echo.
echo  Starting the application... please wait.
echo.

cd /d "%~dp0"
start "" /min venv\Scripts\python.exe serve.py

:: Wait a few seconds for the server to start
timeout /t 5 /nobreak >nul

:: Read port from .env
set PORT=5000
for /f "tokens=1,2 delims==" %%a in (.env) do (
    if "%%a"=="PORT" set PORT=%%b
)

echo.
echo  ============================================
echo   App is now running!
echo   Open your browser and go to:
echo   http://localhost:%PORT%
echo  ============================================
echo.
echo  You can close this window.
echo  To stop the app, double-click "Stop App.bat"
echo.
pause
