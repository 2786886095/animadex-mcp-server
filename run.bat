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

echo [信息] 正在启动服务，请稍候...
echo.

call .venv\Scripts\activate.bat

:: 后台启动服务器
start /B python app.py > server.log 2>&1

:: 等待服务器就绪（最多等30秒）
set WAIT_COUNT=0
:WAIT_LOOP
timeout /t 2 /nobreak >nul
set /a WAIT_COUNT+=1
if %WAIT_COUNT% geq 15 (
    echo [警告] 服务启动较慢，请稍后手动打开浏览器
    goto OPEN_BROWSER
)
:: 检查端口是否已监听
netstat -an | findstr "11452" >nul 2>&1
if errorlevel 1 goto WAIT_LOOP

:OPEN_BROWSER
echo [信息] 服务已启动！
echo.
echo        http://127.0.0.1:11452
echo.
start "" http://127.0.0.1:11452

:: 保持窗口打开，显示实时日志
echo [信息] 按 Ctrl+C 停止服务，或直接关闭窗口
echo.
type server.log 2>nul
