@echo off
title AnimaDex Server
cd /d "%~dp0"

:: ============================================
:: 端口设置 - 修改下面数字即可更换端口
:: ============================================
set PORT=11451

if not exist ".venv\Scripts\pythonw.exe" (
    echo Run install.bat first.
    pause
    exit /b 1
)

:: Start server silently (PORT env var passed to Python)
start "" ".venv\Scripts\pythonw.exe" app.py

:: Wait for port to be ready
set WAIT=0
:LOOP
timeout /t 2 /nobreak >nul
set /a WAIT+=1
if %WAIT% geq 20 goto OPEN
netstat -an | findstr ":%PORT%" >nul 2>&1
if errorlevel 1 goto LOOP

:OPEN
start "" http://127.0.0.1:%PORT%
exit
