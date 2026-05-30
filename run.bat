@echo off
chcp 65001 >nul
title AnimaDex MCP Server

cd /d "%~dp0"

echo.
echo  ╔══════════════════════════════════════╗
echo  ║      ✦ AnimaDex MCP Server ✦        ║
echo  ║      角色提示词搜索与复制工具         ║
echo  ╚══════════════════════════════════════╝
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到虚拟环境，请先运行 install.bat
    pause
    exit /b 1
)

echo [信息] 正在启动服务...
echo.
start "" http://127.0.0.1:11451

call .venv\Scripts\activate.bat
python app.py

pause
