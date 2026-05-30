@echo off
title AnimaDex Server
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Run install.bat first.
    pause
    exit /b 1
)

:: Start server silently (no window)
start "" ".venv\Scripts\pythonw.exe" app.py

:: Wait for port 11451
set WAIT=0
:LOOP
timeout /t 2 /nobreak >nul
set /a WAIT+=1
if %WAIT% geq 20 goto OPEN
netstat -an | findstr "11451" >nul 2>&1
if errorlevel 1 goto LOOP

:OPEN
start "" http://127.0.0.1:11451
exit
