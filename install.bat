@echo off
chcp 65001 >nul
title AnimaDex - 安装依赖

cd /d "%~dp0"

echo.
echo  ╔══════════════════════════════════════╗
echo  ║    ✦ AnimaDex 环境安装 ✦            ║
echo  ╚══════════════════════════════════════╝
echo.

echo [1/3] 创建虚拟环境...
python -m venv .venv
if %errorlevel% neq 0 (
    echo [错误] Python 未安装或版本过低，请安装 Python 3.10+
    pause
    exit /b 1
)

echo [2/3] 安装依赖包...
call .venv\Scripts\pip.exe install -r requirements.txt
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

echo [3/3] 安装完成!
echo.
echo 运行 run.bat 启动服务
echo.

pause
