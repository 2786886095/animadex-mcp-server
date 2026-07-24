@echo off
title AnimaDex Server
cd /d "%~dp0"

:: ============================================
:: �˿����� - �޸��������ּ��ɸ����˿�
:: ============================================
set PORT=8888

if not exist ".venv\Scripts\pythonw.exe" (
    echo Run install.bat first.
    pause
    exit /b 1
)

:: Start server in a visible console window (shows errors & logs)
start "AnimaDex Server" ".venv\Scripts\python.exe" app.py

:: Wait for port to be ready (up to 60 seconds)
echo Waiting for server to start on port %PORT%...
set WAIT=0
:LOOP
timeout /t 2 /nobreak >nul
set /a WAIT+=1
if %WAIT% geq 30 goto OPEN
netstat -an | findstr ":%PORT%" >nul 2>&1
if errorlevel 1 goto LOOP

:OPEN
echo Server should be ready. Opening browser...
start "" http://127.0.0.1:%PORT%
echo.
echo If the page doesn't load, check the server console window for errors.
echo Press any key to exit this launcher...
pause >nul
exit
