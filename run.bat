@echo off
title AnimaDex Server
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run install.bat first.
    pause
    exit /b 1
)

:: Start server in a CMD window
start /MIN "AnimaDex Server" cmd /c ".venv\Scripts\python.exe app.py & pause"

:: Wait for port 11451 (max 30s)
set WAIT=0
:LOOP
timeout /t 2 /nobreak >nul
set /a WAIT+=1
if %WAIT% geq 15 goto OPEN
netstat -an | findstr "11451" >nul 2>&1
if errorlevel 1 goto LOOP

:OPEN
start "" http://127.0.0.1:11451
exit
