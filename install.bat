@echo off
chcp 65001 > nul
title OpenClaw AI 语音助手 — 安装程序

echo.
echo  ╔═══════════════════════════════════════════════╗
echo  ║   🦞  OpenClaw AI 语音助手  v2.0              ║
echo  ║   全双工 · 多平台 · 3000+技能                 ║
echo  ║   安装程序                                    ║
echo  ╚═══════════════════════════════════════════════╝
echo.

:: ── 检测Python ────────────────────────────────────────
echo [1/5] 检测 Python 环境...
python --version > nul 2>&1
if errorlevel 1 (
    echo.
    echo  ❌ 未检测到 Python！
    echo.
    echo  请先安装 Python 3.10 或更高版本：
    echo  1. 打开浏览器访问：https://www.python.org/downloads/
    echo  2. 点击 "Download Python 3.x.x"
    echo  3. 安装时勾选 "Add Python to PATH"（重要！）
    echo  4. 安装完成后重新运行此脚本
    echo.
    echo  或者使用华为镜像（国内下载更快）：
    echo  https://mirrors.huaweicloud.com/python/
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo  ✅ Python %PYVER% 检测成功

:: ── 升级pip ───────────────────────────────────────────
echo.
echo [2/5] 配置 pip 国内镜像源（加速下载）...
python -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ > nul 2>&1
python -m pip config set global.trusted-host mirrors.aliyun.com > nul 2>&1
python -m pip install --upgrade pip --quiet
echo  ✅ pip 已配置阿里云镜像

:: ── 安装依赖 ──────────────────────────────────────────
echo.
echo [3/5] 安装依赖包（首次安装可能需要10-20分钟）...
echo  正在安装核心包...

python -m pip install fastapi uvicorn[standard] websockets pydantic pydantic-settings python-multipart --quiet
if errorlevel 1 goto install_error
echo  ✅ Web 框架安装完成

python -m pip install numpy soundfile httpx openai python-dotenv loguru --quiet
if errorlevel 1 goto install_error
echo  ✅ 基础工具安装完成

echo  正在安装 AI 语音处理包（较大，请耐心等待）...
python -m pip install faster-whisper torch silero-vad edge-tts --quiet
if errorlevel 1 (
    echo  ⚠️ AI 语音包安装失败，尝试仅安装核心功能...
    python -m pip install faster-whisper edge-tts --quiet
)
echo  ✅ 语音处理安装完成

python -m pip install pystray customtkinter pillow jieba qrcode[pil] --quiet
if errorlevel 1 goto install_error
echo  ✅ 界面组件安装完成

echo  ✅ 所有依赖安装完成！
goto install_success

:install_error
echo.
echo  ❌ 安装遇到问题！
echo  请查看错误信息，或手动运行：
echo  python -m pip install -r requirements.txt
echo.
pause
exit /b 1

:install_success

:: ── 创建配置文件 ──────────────────────────────────────
echo.
echo [4/5] 初始化配置...
if not exist "data" mkdir data
if not exist "logs" mkdir logs
if not exist "ssl" (
    mkdir ssl
    echo  正在生成 SSL 证书（用于 HTTPS）...
    python -c "
import subprocess, sys
try:
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048',
                   '-keyout', 'ssl/server.key', '-out', 'ssl/server.crt',
                   '-days', '3650', '-nodes', '-subj',
                   '/CN=localhost/O=OpenClaw/C=CN'], check=True, capture_output=True)
    print('SSL 证书生成成功')
except:
    print('OpenSSL 不可用，跳过 HTTPS（HTTP 模式仍可用）')
" 2>&1
)

:: 运行 Python 初始化
python -c "
import sys
sys.path.insert(0, '.')
from src.router.config import ensure_config
cfg = ensure_config()
print('配置文件初始化完成')
" 2>&1

echo  ✅ 配置初始化完成

:: ── 创建桌面快捷方式 ──────────────────────────────────
echo.
echo [5/5] 创建桌面快捷方式...
set INSTALL_DIR=%~dp0
set SHORTCUT_NAME=OpenClaw AI助手

:: 使用 VBScript 创建快捷方式
set VBS_FILE=%TEMP%\create_shortcut.vbs
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%VBS_FILE%"
echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\OpenClaw AI助手.lnk" >> "%VBS_FILE%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%VBS_FILE%"
echo oLink.TargetPath = "pythonw.exe" >> "%VBS_FILE%"
echo oLink.Arguments = """%INSTALL_DIR%launcher.py""" >> "%VBS_FILE%"
echo oLink.WorkingDirectory = "%INSTALL_DIR%" >> "%VBS_FILE%"
echo oLink.Description = "OpenClaw AI 语音助手 - 全双工对话" >> "%VBS_FILE%"
echo oLink.WindowStyle = 7 >> "%VBS_FILE%"
echo oLink.Save >> "%VBS_FILE%"
cscript /nologo "%VBS_FILE%"
del "%VBS_FILE%" 2>nul

if exist "%USERPROFILE%\Desktop\OpenClaw AI助手.lnk" (
    echo  ✅ 桌面快捷方式已创建
) else (
    echo  ⚠️ 快捷方式创建失败，请手动创建
)

:: 也创建一个命令行版本（方便调试）
set VBS2=%TEMP%\create_shortcut2.vbs
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%VBS2%"
echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\OpenClaw (命令行).lnk" >> "%VBS2%"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%VBS2%"
echo oLink.TargetPath = "cmd.exe" >> "%VBS2%"
echo oLink.Arguments = "/K cd /d ""%INSTALL_DIR%"" ^&^& python launcher.py" >> "%VBS2%"
echo oLink.WorkingDirectory = "%INSTALL_DIR%" >> "%VBS2%"
echo oLink.Description = "OpenClaw AI 语音助手 - 命令行模式" >> "%VBS2%"
echo oLink.Save >> "%VBS2%"
cscript /nologo "%VBS2%"
del "%VBS2%" 2>nul

:: ── 完成 ──────────────────────────────────────────────
echo.
echo  ╔═══════════════════════════════════════════════╗
echo  ║   🎉  安装完成！                              ║
echo  ╠═══════════════════════════════════════════════╣
echo  ║   启动方式：                                  ║
echo  ║   1. 双击桌面「OpenClaw AI助手」图标          ║
echo  ║   2. 或运行：python launcher.py              ║
echo  ║                                               ║
echo  ║   首次启动后：                                ║
echo  ║   1. 点击托盘图标 → 打开设置                  ║
echo  ║   2. 配置 AI 平台 Key（智谱免费推荐）          ║
echo  ║   3. 访问 http://localhost:8766/app           ║
echo  ╚═══════════════════════════════════════════════╝
echo.

set /p LAUNCH="  立即启动 OpenClaw？(y/n): "
if /i "%LAUNCH%"=="y" (
    echo.
    echo  正在启动...
    start "" pythonw.exe "%INSTALL_DIR%launcher.py"
    timeout /t 2 > nul
    start "" "http://localhost:8766/app"
)

pause
