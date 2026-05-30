@echo off
title AnimaDex Install

cd /d "%~dp0"

echo [1/3] Creating virtual environment...
if exist ".venv\Scripts\python.exe" (
    echo     Already exists, skipping.
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create venv. Install Python 3.10+ first.
        pause
        exit /b 1
    )
)

echo [2/3] Installing dependencies...
call .venv\Scripts\pip.exe install -r requirements.txt -q
if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
)

echo [3/3] Done!
echo Run run.bat to start.
pause
