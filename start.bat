@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion
title OpenClaw AI 语音助手
cd /d "%~dp0"

:: ── Tauri 桌面端检测（仅当真正的 exe 文件存在且大于 1MB 时才启动）──
set "OC_TAURI=%~dp0十三香小龙虾.exe"
if exist "%OC_TAURI%" (
    for %%F in ("%OC_TAURI%") do (
        if %%~zF GTR 1000000 (
            echo 正在启动桌面客户端 十三香小龙虾.exe ...
            start "" "%OC_TAURI%"
            exit /b 0
        )
    )
)

:: ── Detect Python ──
set PYTHON_EXE=
for %%p in (
    "%~dp0python\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
) do (
    if exist %%~p (
        set "PYTHON_EXE=%%~p"
        goto :py_found
    )
)
python --version >nul 2>&1
if %errorLevel% == 0 (
    set PYTHON_EXE=python
    goto :py_found
)
echo.
echo  Python 未找到！请先运行 install_full.bat 安装。
echo.
pause
exit /b 1

:py_found

:: ── Generate SSL certs if missing ──
if not exist "certs\server.crt" (
    if not exist "ssl\server.crt" (
        if not exist "ssl\cert.pem" (
            echo 正在生成 SSL 证书...
            "%PYTHON_EXE%" -c "import sys; sys.path.insert(0,'.'); from src.server.certs import ensure_certs; ensure_certs('certs')" 2>nul
            if !errorLevel! neq 0 (
                echo  SSL 证书生成失败，将以 HTTP-only 模式启动。
            )
        )
    )
)

:: ── Check port availability ──
set HTTP_PORT=8766
set HTTPS_PORT=8765
netstat -ano | findstr ":%HTTP_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorLevel% == 0 (
    echo  注意: HTTP 端口 %HTTP_PORT% 已被占用，可能有其他 OpenClaw 实例运行。
)

:: ── Launch ──
echo 正在启动 OpenClaw AI 语音助手...
echo.
"%PYTHON_EXE%" launcher.py %*
if errorlevel 1 (
    echo.
    echo 启动失败，可能原因：
    echo   1. 依赖未安装 - 请运行 install_full.bat
    echo   2. 端口被占用 - 请关闭其他 OpenClaw 实例
    echo   3. 配置错误   - 请检查 .env 文件
    echo.
    pause
)
