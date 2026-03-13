@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set SILENT=0
set MODE=minimal
if "%~1"=="/silent" set SILENT=1
if "%~1"=="/full" set MODE=full
if "%~2"=="/silent" set SILENT=1
if "%~2"=="/full" set MODE=full

set SCRIPT_DIR=%~dp0
set LOG_FILE=%SCRIPT_DIR%logs\install.log
set INSTALL_ERRORS=
if not exist "%SCRIPT_DIR%logs" mkdir "%SCRIPT_DIR%logs"

echo ================================================ > "%LOG_FILE%"
echo  OpenClaw AI v3.0 Installation Log >> "%LOG_FILE%"
echo  Mode: %MODE% >> "%LOG_FILE%"
echo  %date% %time% >> "%LOG_FILE%"
echo ================================================ >> "%LOG_FILE%"

if "%MODE%"=="full" (
    set TOTAL_STEPS=9
    set TITLE_MODE=完整安装（含本地 AI）
) else (
    set TOTAL_STEPS=7
    set TITLE_MODE=最小安装（云端 AI）
)

title [0/%TOTAL_STEPS%] OpenClaw AI 助手 — %TITLE_MODE%

if %SILENT%==0 color 0A
echo.
echo  ╔═══════════════════════════════════════════════════════════╗
echo  ║     OpenClaw AI 语音助手 v3.0 — %TITLE_MODE%            ║
echo  ╠═══════════════════════════════════════════════════════════╣
if "%MODE%"=="full" (
echo  ║  将自动安装以下组件:                                     ║
echo  ║    [1] 管理员权限检测                                    ║
echo  ║    [2] Python 3.11 运行环境                              ║
echo  ║    [3] Visual C++ 运行库                                 ║
echo  ║    [4] pip 加速镜像配置                                  ║
echo  ║    [5] 核心 Python 依赖包                                ║
echo  ║    [6] 本地 AI 引擎 [PyTorch + Whisper]                  ║
echo  ║    [7] 视觉控制套件 [OCR + 自动化]                       ║
echo  ║    [8] SSL 证书                                          ║
echo  ║    [9] 桌面快捷方式                                      ║
) else (
echo  ║  将自动安装以下组件:                                     ║
echo  ║    [1] 管理员权限检测                                    ║
echo  ║    [2] Python 3.11 运行环境                              ║
echo  ║    [3] Visual C++ 运行库                                 ║
echo  ║    [4] pip 加速镜像配置                                  ║
echo  ║    [5] 核心 Python 依赖包（云端版，无需 PyTorch）         ║
echo  ║    [6] SSL 证书                                          ║
echo  ║    [7] 桌面快捷方式                                      ║
)
echo  ╠═══════════════════════════════════════════════════════════╣
echo  ║  注意:                                                   ║
echo  ║    - 请勿关闭此窗口                                      ║
if "%MODE%"=="full" (
echo  ║    - 完整安装约需 15-25 分钟                              ║
) else (
echo  ║    - 最小安装约需 3-8 分钟                                ║
)
echo  ║    - 如果某步骤卡住超过 30 分钟:                          ║
echo  ║      按 Ctrl+C 中断，然后重新运行此脚本重试               ║
echo  ║    - 日志: logs\install.log                              ║
echo  ╚═══════════════════════════════════════════════════════════╝
echo.
if %SILENT%==0 (
    echo  按任意键开始安装...
    pause >nul
)

:: ──────────────────────────────────────────────────
:: 步骤 1：检查管理员权限
:: ──────────────────────────────────────────────────
title [1/%TOTAL_STEPS%] 检查管理员权限...
echo.
echo ────────────────────────────────────────────────
echo  [1/%TOTAL_STEPS%] 检查管理员权限              %time%
echo ────────────────────────────────────────────────
call :log "[1] 检查管理员权限"
net session >nul 2>&1
if %errorLevel% == 0 (
    echo   √ 管理员权限已确认
    call :log "  OK: 管理员权限"
    set ADMIN=1
) else (
    echo   ! 非管理员模式（VC++ 安装可能受限）
    echo   ! 如需管理员权限，请右键"以管理员身份运行"
    call :log "  WARN: 非管理员模式"
    set ADMIN=0
)

:: ──────────────────────────────────────────────────
:: 步骤 2：检测/安装 Python
:: ──────────────────────────────────────────────────
title [2/%TOTAL_STEPS%] 检测 Python...
echo.
echo ────────────────────────────────────────────────
echo  [2/%TOTAL_STEPS%] 检测 Python 安装            %time%
echo ────────────────────────────────────────────────
call :log "[2] 检测 Python"

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

python --version >nul 2>&1
if %errorLevel% == 0 (
    set PYTHON_EXE=python
    goto :python_found
)

echo   ! 未检测到 Python，正在下载 Python 3.11...
call :log "  Python not found, downloading..."
set PY_INSTALLER=%TEMP%\python-311-setup.exe
set PY_URL=https://mirrors.huaweicloud.com/python/3.11.9/python-3.11.9-amd64.exe
set PY_URL2=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe

echo   下载源: 华为云镜像
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('%PY_URL%', '%PY_INSTALLER%')}" 2>nul
if not exist "%PY_INSTALLER%" (
    echo   华为云镜像失败，尝试官方源...
    powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('%PY_URL2%', '%PY_INSTALLER%')}" 2>nul
)

if exist "%PY_INSTALLER%" (
    echo   安装 Python 3.11（静默安装）...
    "%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=0
    del "%PY_INSTALLER%" 2>nul
    set PYTHON_EXE="C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
    if exist !PYTHON_EXE! goto :python_found
    set PYTHON_EXE=python
) else (
    echo   X Python 下载失败！
    echo.
    echo   ══════════════════════════════════════════════
    echo   请手动下载安装 Python 3.11:
    echo   https://www.python.org/downloads/release/python-3119/
    echo   安装后重新运行此脚本
    echo   ══════════════════════════════════════════════
    call :log "  FATAL: Python download failed"
    if %SILENT%==0 pause
    exit /b 1
)

:python_found
echo   √ Python: %PYTHON_EXE%
%PYTHON_EXE% --version
call :log "  OK: %PYTHON_EXE%"

:: ──────────────────────────────────────────────────
:: 步骤 3：检测/安装 VC++ 运行库
:: ──────────────────────────────────────────────────
title [3/%TOTAL_STEPS%] 检测 VC++ 运行库...
echo.
echo ────────────────────────────────────────────────
echo  [3/%TOTAL_STEPS%] 检测 Visual C++ 运行库      %time%
echo ────────────────────────────────────────────────
call :log "[3] 检测 VC++ 运行库"

reg query "HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" >nul 2>&1
if %errorLevel% == 0 (
    echo   √ Visual C++ 运行库已安装
    call :log "  OK: VC++ already installed"
    goto :vcredist_done
)
reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" >nul 2>&1
if %errorLevel% == 0 (
    echo   √ Visual C++ 运行库已安装
    call :log "  OK: VC++ already installed (WOW64)"
    goto :vcredist_done
)

echo   ! 未检测到 VC++ 运行库，正在下载（5MB）...
set VC_URL=https://aka.ms/vs/17/release/vc_redist.x64.exe
set VC_INSTALLER=%TEMP%\vcredist_x64.exe
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('%VC_URL%', '%VC_INSTALLER%')}" 2>nul

if exist "%VC_INSTALLER%" (
    echo   安装 Visual C++ 运行库...
    "%VC_INSTALLER%" /quiet /norestart
    del "%VC_INSTALLER%" 2>nul
    echo   √ VC++ 运行库安装完成
    call :log "  OK: VC++ installed"
) else (
    echo   ! VC++ 下载失败，部分组件可能无法运行
    echo   手动下载: https://aka.ms/vs/17/release/vc_redist.x64.exe
    call :log "  WARN: VC++ download failed"
    set INSTALL_ERRORS=!INSTALL_ERRORS! [VC++]
)

:vcredist_done

:: ──────────────────────────────────────────────────
:: 步骤 4：配置 pip 镜像
:: ──────────────────────────────────────────────────
title [4/%TOTAL_STEPS%] 配置 pip 镜像...
echo.
echo ────────────────────────────────────────────────
echo  [4/%TOTAL_STEPS%] 配置 pip 加速镜像（阿里云） %time%
echo ────────────────────────────────────────────────
call :log "[4] 配置 pip 镜像"

%PYTHON_EXE% -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ >nul 2>&1
%PYTHON_EXE% -m pip config set global.trusted-host mirrors.aliyun.com >nul 2>&1
%PYTHON_EXE% -m pip install --upgrade pip --quiet 2>&1
echo   √ pip 镜像配置完成（阿里云）
call :log "  OK: pip mirror configured"

:: ──────────────────────────────────────────────────
:: 步骤 5：安装核心依赖
:: ──────────────────────────────────────────────────
title [5/%TOTAL_STEPS%] 安装核心依赖...
echo.
echo ────────────────────────────────────────────────
echo  [5/%TOTAL_STEPS%] 安装核心 Python 依赖        %time%
if "%MODE%"=="full" (
echo  模式: 完整安装 — 使用 requirements-full.txt
echo  预计时间: 3-5 分钟
) else (
echo  模式: 最小安装 — 仅云端依赖（无 PyTorch）
echo  预计时间: 1-3 分钟
)
echo ────────────────────────────────────────────────
call :log "[5] 安装核心依赖 (mode=%MODE%)"

if "%MODE%"=="full" (
    if exist "%SCRIPT_DIR%requirements-full.txt" (
        %PYTHON_EXE% -m pip install --no-cache-dir -r "%SCRIPT_DIR%requirements-full.txt" 2>&1
    ) else (
        echo   ! requirements-full.txt 不存在，降级为最小安装
        %PYTHON_EXE% -m pip install --no-cache-dir -r "%SCRIPT_DIR%requirements.txt" 2>&1
    )
) else (
    %PYTHON_EXE% -m pip install --no-cache-dir -r "%SCRIPT_DIR%requirements.txt" 2>&1
)

if %errorLevel% neq 0 (
    echo.
    echo   X 核心依赖安装失败！
    echo   可能原因: 网络不稳定 / 镜像源不可用 / 磁盘空间不足
    echo   建议: 检查网络后重新运行此脚本
    call :log "  FAIL: 核心依赖安装失败"
    set INSTALL_ERRORS=!INSTALL_ERRORS! [核心依赖]
) else (
    echo.
    echo   √ 核心依赖安装完成                        %time%
    call :log "  OK: 核心依赖安装完成"
)

:: ──────────────────────────────────────────────────
:: 步骤 6-7 (完整模式): AI 引擎 + 视觉控制
:: ──────────────────────────────────────────────────
if "%MODE%"=="full" (
    title [6/%TOTAL_STEPS%] 安装 PyTorch...
    echo.
    echo ────────────────────────────────────────────────
    echo  [6/%TOTAL_STEPS%] 安装 AI 引擎 PyTorch       %time%
    echo  预计时间: 5-10 分钟（PyTorch 约 200MB）
    echo ────────────────────────────────────────────────
    call :log "[6] 安装 AI 引擎"

    %PYTHON_EXE% -m pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu 2>&1
    if !errorLevel! neq 0 (
        echo   ! PyTorch 官方源失败，尝试阿里云镜像...
        call :log "  WARN: PyTorch official source failed"
        %PYTHON_EXE% -m pip install --no-cache-dir torch 2>&1
        if !errorLevel! neq 0 (
            echo   X PyTorch 安装失败！
            call :log "  FAIL: PyTorch install failed"
            set INSTALL_ERRORS=!INSTALL_ERRORS! [PyTorch]
        )
    )

    echo.
    echo   安装 faster-whisper 和 silero-vad...
    %PYTHON_EXE% -m pip install --no-cache-dir faster-whisper silero-vad funasr 2>&1
    if !errorLevel! neq 0 (
        echo   X 语音识别组件安装失败！
        call :log "  FAIL: STT components failed"
        set INSTALL_ERRORS=!INSTALL_ERRORS! [Whisper]
    ) else (
        echo   √ AI 引擎安装完成                      %time%
        call :log "  OK: AI 引擎安装完成"
    )

    title [7/%TOTAL_STEPS%] 安装视觉控制套件...
    echo.
    echo ────────────────────────────────────────────────
    echo  [7/%TOTAL_STEPS%] 安装视觉控制套件           %time%
    echo  包含: OCR 识别 + 屏幕捕获 + 自动化操作
    echo ────────────────────────────────────────────────
    call :log "[7] 安装视觉控制套件"

    %PYTHON_EXE% -m pip install --no-cache-dir rapidocr-onnxruntime mss pyautogui uiautomation 2>&1
    if !errorLevel! neq 0 (
        echo   ! 视觉控制套件安装失败（非关键）
        call :log "  WARN: vision components failed"
        set INSTALL_ERRORS=!INSTALL_ERRORS! [Vision]
    ) else (
        echo   √ 视觉控制套件安装完成                  %time%
        call :log "  OK: 视觉控制套件安装完成"
    )

    set NEXT_STEP=8
) else (
    set NEXT_STEP=6
)

:: ──────────────────────────────────────────────────
:: SSL 证书 (CA + Server cert with LAN IPs)
:: ──────────────────────────────────────────────────
title [!NEXT_STEP!/%TOTAL_STEPS%] 生成 SSL 证书...
echo.
echo ────────────────────────────────────────────────
echo  [!NEXT_STEP!/%TOTAL_STEPS%] 生成 SSL 证书     %time%
echo  使用 CA 签发模式，支持局域网和 iOS 设备
echo ────────────────────────────────────────────────
call :log "[!NEXT_STEP!] 生成 SSL 证书 (CA mode)"

%PYTHON_EXE% -m pip install cryptography --quiet 2>&1
%PYTHON_EXE% -c "import sys; sys.path.insert(0,'.'); from src.server.certs import ensure_certs; ca,crt,key=ensure_certs('certs'); print(f'CA: {ca}'); print(f'Cert: {crt}'); print(f'Key: {key}')" 2>&1
if !errorLevel! == 0 (
    echo   √ SSL 证书生成完成（CA + Server，含局域网 IP）
    call :log "  OK: SSL via certs.py (CA mode with LAN IPs)"
) else (
    echo   ! certs.py 生成失败，尝试简单证书...
    call :log "  WARN: certs.py failed, trying fallback"
    if not exist ssl mkdir ssl
    where openssl >nul 2>&1
    if !errorLevel! == 0 (
        openssl req -x509 -newkey rsa:2048 -keyout ssl\key.pem -out ssl\cert.pem ^
            -days 3650 -nodes -subj "/CN=localhost" -addext "subjectAltName=IP:127.0.0.1,IP:0.0.0.0" 2>nul
        echo   √ SSL 证书生成完成（openssl 回退）
        call :log "  OK: SSL via openssl fallback"
    ) else (
        echo   ! SSL 证书生成失败，启动后可能需要手动处理
        call :log "  WARN: SSL generation failed completely"
        set INSTALL_ERRORS=!INSTALL_ERRORS! [SSL]
    )
)

:: ──────────────────────────────────────────────────
:: 创建桌面快捷方式
:: ──────────────────────────────────────────────────
set /a LAST_STEP=NEXT_STEP+1
title [!LAST_STEP!/%TOTAL_STEPS%] 创建快捷方式...
echo.
echo ────────────────────────────────────────────────
echo  [!LAST_STEP!/%TOTAL_STEPS%] 创建桌面快捷方式  %time%
echo ────────────────────────────────────────────────
call :log "[!LAST_STEP!] 创建快捷方式"

set APP_DIR=%CD%

:: Copy .env template if not exists
if not exist "!APP_DIR!\.env" (
    if exist "!APP_DIR!\.env.template" (
        copy "!APP_DIR!\.env.template" "!APP_DIR!\.env" >nul 2>&1
        echo   √ 已创建 .env 配置文件
        call :log "  OK: .env created from template"
    )
)

:: Create required directories
if not exist "!APP_DIR!\data" mkdir "!APP_DIR!\data"
if not exist "!APP_DIR!\data\voice_clones" mkdir "!APP_DIR!\data\voice_clones"
if not exist "!APP_DIR!\data\screenshots" mkdir "!APP_DIR!\data\screenshots"
if not exist "!APP_DIR!\logs" mkdir "!APP_DIR!\logs"
if not exist "!APP_DIR!\models" mkdir "!APP_DIR!\models"

set SHORTCUT_VBS=%TEMP%\create_shortcut.vbs
(
echo Set oWS = WScript.CreateObject^("WScript.Shell"^)
echo Set fso = CreateObject^("Scripting.FileSystemObject"^)
echo sDesktop = oWS.SpecialFolders^("Desktop"^)
echo Set oLink = oWS.CreateShortcut^(sDesktop ^& "\OpenClaw AI助手.lnk"^)
echo oLink.TargetPath = "wscript.exe"
echo oLink.Arguments = """!APP_DIR!\OpenClaw.vbs"""
echo oLink.WorkingDirectory = "!APP_DIR!"
echo oLink.Description = "OpenClaw AI 语音助手 — 全双工对话"
echo If fso.FileExists^("!APP_DIR!\assets\icon.ico"^) Then oLink.IconLocation = "!APP_DIR!\assets\icon.ico"
echo oLink.Save
echo sMenu = oWS.SpecialFolders^("Programs"^)
echo Set oLink2 = oWS.CreateShortcut^(sMenu ^& "\OpenClaw AI助手.lnk"^)
echo oLink2.TargetPath = "wscript.exe"
echo oLink2.Arguments = """!APP_DIR!\OpenClaw.vbs"""
echo oLink2.WorkingDirectory = "!APP_DIR!"
echo oLink2.Description = "OpenClaw AI 语音助手 — 全双工对话"
echo If fso.FileExists^("!APP_DIR!\assets\icon.ico"^) Then oLink2.IconLocation = "!APP_DIR!\assets\icon.ico"
echo oLink2.Save
echo Set oLink3 = oWS.CreateShortcut^(sDesktop ^& "\OpenClaw (命令行).lnk"^)
echo oLink3.TargetPath = "!APP_DIR!\start.bat"
echo oLink3.WorkingDirectory = "!APP_DIR!"
echo oLink3.Description = "OpenClaw AI — 命令行调试模式"
echo oLink3.Save
) > "%SHORTCUT_VBS%"
cscript //nologo "%SHORTCUT_VBS%" 2>nul
del "%SHORTCUT_VBS%" 2>nul
echo   √ 快捷方式创建完成（桌面 + 开始菜单 + 命令行）
call :log "  OK: 快捷方式已创建"

:: ──────────────────────────────────────────────────
:: 写入安装模式标记
:: ──────────────────────────────────────────────────
echo %MODE%> "%SCRIPT_DIR%install_mode.txt"

:: ──────────────────────────────────────────────────
:: 安装结果汇总
:: ──────────────────────────────────────────────────
echo.
echo ════════════════════════════════════════════════════════════
call :log "================================================"
call :log "安装结束: %date% %time%"

if defined INSTALL_ERRORS (
    title OpenClaw — 安装完成（有异常）
    echo   ! 安装完成，但以下步骤有异常:
    echo     %INSTALL_ERRORS%
    echo.
    echo   建议操作:
    echo     1. 检查网络连接后重新运行此脚本
    echo     2. 查看详细日志: %LOG_FILE%
    echo     3. 将日志发送给开发者排查
    call :log "WARNINGS: %INSTALL_ERRORS%"
) else (
    title OpenClaw — 安装成功！
    echo   安装全部完成！ 模式: %MODE%
    echo.
    echo   启动方式:
    echo     桌面双击「OpenClaw AI助手」图标
    echo     或命令行: start.bat / python launcher.py
    echo.
    echo   首次启动请配置 AI 平台 Key（免费可用）:
    echo     推荐: 智谱 AI（永久免费）open.bigmodel.cn
    echo.
    echo   网页端: http://localhost:8766/app
    if "%MODE%"=="minimal" (
        echo.
        echo   提示: 当前为最小安装（云端 AI）
        echo   如需本地 AI 能力，重新运行: install_full.bat /full
    )
    call :log "ALL OK: 安装全部成功 (mode=%MODE%)"
)
echo ════════════════════════════════════════════════════════════
echo.
if %SILENT%==0 pause
goto :eof

:: ──────────────────────────────────────────────────
:: 日志写入子程序
:: ──────────────────────────────────────────────────
:log
echo [%date% %time%] %~1 >> "%LOG_FILE%"
goto :eof
