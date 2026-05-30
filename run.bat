@echo off
title AnimaDex Server

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Run install.bat first.
    pause
    exit /b 1
)

echo Starting server...

start /B python app.py > server.log 2>&1

:: Wait for port 11452
set WAIT=0
:LOOP
timeout /t 2 /nobreak >nul
set /a WAIT+=1
if %WAIT% geq 15 goto OPEN
netstat -an | findstr "11452" >nul 2>&1
if errorlevel 1 goto LOOP

:OPEN
start "" http://127.0.0.1:11452
echo Server running at http://127.0.0.1:11452
echo Close this window to stop.
type server.log
