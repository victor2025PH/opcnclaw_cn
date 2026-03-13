@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo.
echo ╔═══════════════════════════════════════════════╗
echo ║   OpenClaw v3.0 — 安装包构建脚本             ║
echo ╚═══════════════════════════════════════════════╝
echo.

:: ── 查找 ISCC.exe ──
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
)

if "%ISCC%"=="" (
    echo   X 未检测到 Inno Setup 6
    echo.
    echo   请先安装 Inno Setup 6:
    echo   https://jrsoftware.org/isdl.php
    echo.
    echo   安装后重新运行此脚本。
    pause
    exit /b 1
)

echo   √ 找到: %ISCC%
echo.

:: ── 预检 ──
echo  [1/4] 检查文件完整性...
set MISSING=0
for %%f in (
    launcher.py
    requirements.txt
    requirements-full.txt
    .env.template
    installer.iss
    install_full.bat
    OpenClaw.vbs
    start.bat
    assets\icon.ico
    assets\icon.png
    src\server\main.py
    src\server\health.py
    src\gui\settings.py
    src\bridge\wechat_mp.py
) do (
    if not exist "%%f" (
        echo     X 缺失: %%f
        set /a MISSING+=1
    )
)

if %MISSING% gtr 0 (
    echo   X 有 %MISSING% 个文件缺失，请先修复！
    pause
    exit /b 1
)
echo   √ 核心文件齐全

:: ── 语法检查 ──
echo.
echo  [2/4] Python 语法检查...
set PY=python
where python >nul 2>&1 || set PY="C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"

%PY% -m py_compile src\server\main.py 2>nul
if %errorLevel% neq 0 (
    echo   X main.py 编译失败
    pause
    exit /b 1
)
%PY% -m py_compile src\gui\settings.py 2>nul
%PY% -m py_compile launcher.py 2>nul
echo   √ 语法检查通过

:: ── 确保 version.txt ──
echo.
echo  [3/4] 检查 version.txt...
if exist version.txt (
    set /p BUILD_VER=<version.txt
    echo   √ version.txt = !BUILD_VER!
) else (
    echo 3.2.0> version.txt
    echo   √ version.txt = 3.2.0 (新建)
)

:: ── 编译安装包 ──
echo.
echo  [4/4] 编译安装包...
echo.

if not exist "dist\installer" mkdir "dist\installer"

"%ISCC%" installer.iss

if %errorLevel% == 0 (
    echo.
    echo ═══════════════════════════════════════════════
    echo   √ 构建成功！
    echo   输出: dist\installer\OpenClaw-v3.2-Setup.exe
    echo ═══════════════════════════════════════════════
) else (
    echo.
    echo   X 构建失败！请检查 Inno Setup 输出的错误信息。
)

echo.
pause
