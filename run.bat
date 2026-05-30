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

:: Wait for port 11451 with loading animation
echo Loading character index (3.6万+ characters)...
echo.
set WAIT=0
:LOOP
set /a WAIT+=1
if %WAIT% gtr 1 echo|set /p=.
timeout /t 1 /nobreak >nul
if %WAIT% geq 45 (
    echo.
    echo Server started or timeout. Opening browser...
    goto OPEN
)
netstat -an | findstr "11451" >nul 2>&1
if errorlevel 1 goto LOOP

:OPEN
echo.
echo.
echo Server is ready!
start "" http://127.0.0.1:11451
exit
