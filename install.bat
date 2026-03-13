@echo off
chcp 65001 > nul
title OpenClaw AI 语音助手 — 安装程序
cd /d "%~dp0"

echo.
echo  ╔═══════════════════════════════════════════════╗
echo  ║   OpenClaw AI 语音助手  v3.2                  ║
echo  ║   全双工 · 多平台 · 智能桌面控制              ║
echo  ║   安装程序                                    ║
echo  ╚═══════════════════════════════════════════════╝
echo.

:: Check if install_full.bat exists for comprehensive install
if exist "%~dp0install_full.bat" (
    echo  检测到完整安装脚本，即将启动...
    echo.
    echo  安装模式:
    echo    [1] 最小安装（云端 AI，3-8 分钟，推荐低配电脑）
    echo    [2] 完整安装（含本地 AI 模型，15-25 分钟，推荐高配电脑）
    echo.
    set /p MODE_CHOICE="  请选择 (1/2, 默认1): "
    if "!MODE_CHOICE!"=="2" (
        call "%~dp0install_full.bat" /full
    ) else (
        call "%~dp0install_full.bat"
    )
    goto :eof
)

:: Fallback: simple install if install_full.bat is missing
echo  install_full.bat 未找到，使用简化安装...
echo.

:: Detect Python
echo [1/4] 检测 Python 环境...
python --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  Python 未找到！
    echo.
    echo  请安装 Python 3.10+:
    echo    https://www.python.org/downloads/
    echo    安装时务必勾选 "Add Python to PATH"
    echo.
    echo  或使用华为镜像（国内更快）:
    echo    https://mirrors.huaweicloud.com/python/
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  Python %PYVER%

:: Configure pip
echo.
echo [2/4] 配置 pip 镜像源...
python -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ > nul 2>&1
python -m pip config set global.trusted-host mirrors.aliyun.com > nul 2>&1
python -m pip install --upgrade pip --quiet 2>nul
echo  pip 已配置阿里云镜像

:: Install dependencies
echo.
echo [3/4] 安装依赖（首次约 5-10 分钟）...
python -m pip install --no-cache-dir -r requirements.txt
if errorlevel 1 (
    echo.
    echo  依赖安装失败！请检查网络后重试。
    pause
    exit /b 1
)
echo  所有依赖安装完成

:: Generate certs
echo.
echo [4/4] 生成 SSL 证书...
python -c "import sys; sys.path.insert(0,'.'); from src.server.certs import ensure_certs; ensure_certs('certs')" 2>nul
if errorlevel 1 (
    echo  SSL 证书生成失败（HTTP 模式仍可用）
) else (
    echo  SSL 证书已生成
)

:: Copy .env template
if not exist ".env" (
    if exist ".env.template" (
        copy ".env.template" ".env" >nul
        echo  已创建 .env 配置文件
    )
)

:: Create directories
if not exist "data" mkdir data
if not exist "logs" mkdir logs

echo.
echo  ╔═══════════════════════════════════════════════╗
echo  ║   安装完成！                                  ║
echo  ╠═══════════════════════════════════════════════╣
echo  ║   启动: 双击桌面「OpenClaw AI助手」           ║
echo  ║   或运行: python launcher.py                  ║
echo  ║                                               ║
echo  ║   首次启动请配置 AI Key:                      ║
echo  ║   推荐: 智谱 AI（永久免费）open.bigmodel.cn   ║
echo  ╚═══════════════════════════════════════════════╝
echo.
set /p LAUNCH="  立即启动? (y/n): "
if /i "%LAUNCH%"=="y" (
    start "" python launcher.py
    timeout /t 3 > nul
    start "" "http://localhost:8766/app"
)
pause
