@echo off
chcp 65001 >nul
title OpenClaw 打包工具

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║         OpenClaw AI 助手 — 打包工具              ║
echo ╠══════════════════════════════════════════════════╣
echo ║  [1] 快速便携包（推荐，含Python，解压即用）       ║
echo ║  [2] 轻量便携包（不含AI包，首次运行在线安装）     ║
echo ║  [3] PyInstaller 打包（单文件夹EXE）             ║
echo ║  [4] 生成Inno Setup安装程序（需要先运行选项1）    ║
echo ╚══════════════════════════════════════════════════╝
echo.
set /p choice=请选择 [1-4]: 

if "%choice%"=="1" goto portable_full
if "%choice%"=="2" goto portable_light
if "%choice%"=="3" goto pyinstaller
if "%choice%"=="4" goto innosetup
goto end

:portable_full
echo.
echo [+] 构建完整便携包（含AI包，约1GB）...
echo [!] 需要网络，请确保网络畅通，预计需要10-30分钟
python build_portable.py --mode portable
goto done

:portable_light
echo.
echo [+] 构建轻量便携包（不含AI包，约200MB）...
python build_portable.py --mode portable --no-ai
goto done

:pyinstaller
echo.
echo [+] 运行 PyInstaller...
echo [!] 需要已安装所有依赖
python -m PyInstaller openclaw.spec --clean
goto done

:innosetup
echo.
echo [+] 检查 Inno Setup...
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    "C:\Program Files\Inno Setup 6\ISCC.exe" installer.iss
) else (
    echo [!] 未找到 Inno Setup 6，请先安装：
    echo     https://jrsoftware.org/isdl.php
    echo.
    echo     安装后重新运行此选项
    start https://jrsoftware.org/isdl.php
)
goto done

:done
echo.
echo ════════════════════════════════════════
echo 打包完成！输出目录: dist\
dir dist\ /b 2>nul
echo ════════════════════════════════════════
pause

:end
