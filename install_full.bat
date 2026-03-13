@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title OpenClaw AI 助手 — 完整安装向导

:: ══════════════════════════════════════════════════
::  OpenClaw 完整安装向导 v2.0
::  解决"电脑没有相应程序或插件"的终极方案
:: ══════════════════════════════════════════════════

color 0A
echo.
echo   ██████╗ ██████╗ ███████╗███╗   ██╗ ██████╗██╗      █████╗ ██╗    ██╗
echo  ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔════╝██║     ██╔══██╗██║    ██║
echo  ██║   ██║██████╔╝█████╗  ██╔██╗ ██║██║     ██║     ███████║██║ █╗ ██║
echo  ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██║     ██║     ██╔══██║██║███╗██║
echo  ╚██████╔╝██║     ███████╗██║ ╚████║╚██████╗███████╗██║  ██║╚███╔███╔╝
echo   ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝ ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝
echo.
echo                  AI 语音助手 v2.0 — 完整安装向导
echo.
echo  ════════════════════════════════════════════════════════════════
echo  本安装向导将自动检测并安装所有必需组件：
echo    ✓ Python 3.11 运行环境
echo    ✓ Visual C++ 运行库（torch 必需）
echo    ✓ 所有 Python 依赖包
echo    ✓ SSL 证书（麦克风权限必需）
echo    ✓ 桌面快捷方式
echo  ════════════════════════════════════════════════════════════════
echo.
pause

:: ──────────────────────────────────────────────────
:: 步骤 1：检查管理员权限（VC++ 安装需要）
:: ──────────────────────────────────────────────────
echo [1/8] 检查权限...
net session >nul 2>&1
if %errorLevel% == 0 (
    echo   ✓ 管理员权限确认
    set ADMIN=1
) else (
    echo   ⚠ 当前非管理员模式（部分功能可能受限）
    echo   ⚠ 如 VC++ 安装失败，请右键本文件"以管理员身份运行"
    set ADMIN=0
)

:: ──────────────────────────────────────────────────
:: 步骤 2：检测/安装 Python
:: ──────────────────────────────────────────────────
echo.
echo [2/8] 检测 Python 安装...

:: 检查多种 Python 路径
set PYTHON_EXE=
for %%p in (
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
) do (
    if exist %%p (
        set PYTHON_EXE=%%~p
        goto :python_found
    )
)

:: 尝试 PATH 中的 python
python --version >nul 2>&1
if %errorLevel% == 0 (
    set PYTHON_EXE=python
    goto :python_found
)

:: 没有 Python，自动下载安装
echo   ! 未检测到 Python，正在下载 Python 3.11...
echo.
set PY_INSTALLER=%TEMP%\python-311-setup.exe
set PY_URL=https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-amd64.exe
set PY_URL2=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe

echo   下载地址: %PY_URL%
echo   （如果慢，请手动下载 Python 3.11: %PY_URL2%）
echo.

:: 用 PowerShell 下载（Win10 内置）
powershell -Command "& {$p = New-Object System.Net.WebClient; $p.DownloadFile('%PY_URL%', '%PY_INSTALLER%')}" 2>nul
if not exist "%PY_INSTALLER%" (
    powershell -Command "& {$p = New-Object System.Net.WebClient; $p.DownloadFile('%PY_URL2%', '%PY_INSTALLER%')}" 2>nul
)

if exist "%PY_INSTALLER%" (
    echo   安装 Python 3.11（静默安装）...
    :: PrependPath=1 自动加入PATH, /quiet 静默
    "%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=0
    del "%PY_INSTALLER%" 2>nul

    :: 重新检测
    set PYTHON_EXE="C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
    if exist !PYTHON_EXE! goto :python_found
    set PYTHON_EXE=python
) else (
    echo   ✗ Python 下载失败！请手动下载安装：
    echo     https://www.python.org/downloads/release/python-3119/
    echo.
    start https://www.python.org/downloads/release/python-3119/
    pause
    exit /b 1
)

:python_found
echo   ✓ Python: %PYTHON_EXE%
%PYTHON_EXE% --version

:: ──────────────────────────────────────────────────
:: 步骤 3：检测/安装 VC++ 运行库
:: ──────────────────────────────────────────────────
echo.
echo [3/8] 检测 Visual C++ 运行库...

reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" >nul 2>&1
if %errorLevel% == 0 (
    echo   ✓ Visual C++ 运行库已安装
    goto :vcredist_done
)

reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" >nul 2>&1
if %errorLevel% == 0 (
    echo   ✓ Visual C++ 运行库已安装
    goto :vcredist_done
)

echo   ! 未检测到 VC++ 运行库，正在下载（5MB）...
set VC_URL=https://aka.ms/vs/17/release/vc_redist.x64.exe
set VC_INSTALLER=%TEMP%\vcredist_x64.exe

powershell -Command "& {$p=New-Object System.Net.WebClient; $p.DownloadFile('%VC_URL%', '%VC_INSTALLER%')}" 2>nul

if exist "%VC_INSTALLER%" (
    echo   安装 Visual C++ 运行库...
    "%VC_INSTALLER%" /quiet /norestart
    del "%VC_INSTALLER%" 2>nul
    echo   ✓ VC++ 运行库安装完成
) else (
    echo   ⚠ VC++ 下载失败，如遇到 torch 报错请手动安装：
    echo     https://aka.ms/vs/17/release/vc_redist.x64.exe
)

:vcredist_done

:: ──────────────────────────────────────────────────
:: 步骤 4：配置 pip 镜像
:: ──────────────────────────────────────────────────
echo.
echo [4/8] 配置 pip 加速镜像（阿里云）...
%PYTHON_EXE% -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ >nul
%PYTHON_EXE% -m pip config set global.trusted-host mirrors.aliyun.com >nul
%PYTHON_EXE% -m pip install --upgrade pip --quiet
echo   ✓ pip 镜像配置完成（阿里云）

:: ──────────────────────────────────────────────────
:: 步骤 5：安装核心依赖
:: ──────────────────────────────────────────────────
echo.
echo [5/8] 安装核心依赖...
echo   （约需 2-5 分钟，请耐心等待）
%PYTHON_EXE% -m pip install ^
    fastapi uvicorn[standard] websockets pydantic pydantic-settings ^
    python-multipart httpx openai python-dotenv loguru ^
    pystray customtkinter pillow jieba qrcode ^
    numpy soundfile edge-tts --quiet
echo   ✓ 核心依赖安装完成

:: ──────────────────────────────────────────────────
:: 步骤 6：安装 AI 依赖（torch 较大）
:: ──────────────────────────────────────────────────
echo.
echo [6/8] 安装 AI 依赖（torch + faster-whisper）...
echo   [!] torch 体积较大（约 500MB），下载需要时间
echo   [!] 正在使用国内镜像加速...
echo.

%PYTHON_EXE% -m pip install torch --index-url https://download.pytorch.org/whl/cpu --quiet
if %errorLevel% neq 0 (
    echo   ⚠ PyTorch CPU 版安装失败，尝试标准版...
    %PYTHON_EXE% -m pip install torch --quiet
)
%PYTHON_EXE% -m pip install faster-whisper silero-vad --quiet
echo   ✓ AI 依赖安装完成

:: ──────────────────────────────────────────────────
:: 步骤 7：生成 SSL 证书
:: ──────────────────────────────────────────────────
echo.
echo [7/8] 生成 SSL 证书（麦克风需要 HTTPS）...
if not exist ssl mkdir ssl

where openssl >nul 2>&1
if %errorLevel% == 0 (
    openssl req -x509 -newkey rsa:2048 -keyout ssl\key.pem -out ssl\cert.pem ^
        -days 3650 -nodes -subj "/CN=localhost" -addext "subjectAltName=IP:127.0.0.1,IP:0.0.0.0" 2>nul
    echo   ✓ SSL 证书生成完成
) else (
    echo   ⚠ 未找到 openssl，尝试用 Python 生成证书...
    %PYTHON_EXE% -c "
import subprocess, sys
try:
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'cryptography', '--quiet'])
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime, ipaddress
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    cert = (x509.CertificateBuilder()
        .subject_name(subject).issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName('localhost'),
            x509.IPAddress(ipaddress.IPv4Address('127.0.0.1')),
        ]), critical=False)
        .sign(key, hashes.SHA256()))
    open('ssl/cert.pem','wb').write(cert.public_bytes(serialization.Encoding.PEM))
    open('ssl/key.pem','wb').write(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    print('SSL 证书生成成功')
except Exception as e:
    print(f'SSL 证书生成失败: {e}')
"
)

:: ──────────────────────────────────────────────────
:: 步骤 8：创建桌面快捷方式
:: ──────────────────────────────────────────────────
echo.
echo [8/8] 创建桌面快捷方式...

set APP_DIR=%CD%
set SHORTCUT_VBS=%TEMP%\create_shortcut.vbs
(
echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
echo sDesktop = oWS.SpecialFolders^("Desktop"^)
echo.
echo ' 主桌面图标
echo Set oLink = oWS.CreateShortcut^(sDesktop ^& "\OpenClaw AI助手.lnk"^)
echo oLink.TargetPath = "wscript.exe"
echo oLink.Arguments = """!APP_DIR!\start.bat"""
echo oLink.WorkingDirectory = "!APP_DIR!"
echo oLink.Description = "OpenClaw AI 语音助手"
echo oLink.Save
echo.
echo ' 开始菜单
echo sMenu = oWS.SpecialFolders^("Programs"^)
echo Set oLink2 = oWS.CreateShortcut^(sMenu ^& "\OpenClaw AI助手.lnk"^)
echo oLink2.TargetPath = "wscript.exe"
echo oLink2.Arguments = """!APP_DIR!\start.bat"""
echo oLink2.WorkingDirectory = "!APP_DIR!"
echo oLink2.Save
echo.
echo MsgBox "OpenClaw AI助手 安装完成！" ^& Chr^(13^) ^& Chr^(10^) ^& Chr^(13^) ^& Chr^(10^) ^& "✓ 桌面快捷方式已创建" ^& Chr^(13^) ^& Chr^(10^) ^& "✓ 双击 'OpenClaw AI助手' 即可启动", 64, "安装完成"
) > "%SHORTCUT_VBS%"

cscript //nologo "%SHORTCUT_VBS%"
del "%SHORTCUT_VBS%" 2>nul

:: ──────────────────────────────────────────────────
:: 完成
:: ──────────────────────────────────────────────────
echo.
echo ════════════════════════════════════════════════════
echo   ✅ 安装完成！
echo.
echo   启动方式：
echo     桌面双击「OpenClaw AI助手」
echo     或命令行：python launcher.py
echo.
echo   首次启动请配置 AI 平台 Key（免费可用）：
echo     推荐：智谱 AI（永久免费）open.bigmodel.cn
echo ════════════════════════════════════════════════════
echo.
pause
