@echo off
chcp 65001 >nul
title 构建十三香小龙虾安装包

echo.
echo  ╔══════════════════════════════════════╗
echo  ║  构建十三香小龙虾安装包               ║
echo  ╚══════════════════════════════════════╝
echo.

:: Step 1: 构建 Tauri 桌面客户端
echo [1/3] 构建 Tauri 桌面客户端...
call npx tauri build
if errorlevel 1 (
    echo [错误] Tauri 构建失败
    pause
    exit /b 1
)

:: Step 2: 复制 exe 到统一目录并改名
echo [2/3] 复制到 dist\...
if not exist "dist" mkdir "dist"
copy /Y "src-tauri\target\release\shisanxiang.exe" "dist\十三香小龙虾.exe" >nul
echo   十三香小龙虾.exe → dist\

:: Step 3: 编译 Inno Setup 安装包
echo [3/3] 编译 Inno Setup 安装包...
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
) else (
    echo [警告] 未找到 Inno Setup 6，跳过安装包编译
    echo   请手动运行: ISCC.exe installer.iss
)

echo.
echo ══════════════════════════════════════════
echo  构建完成！
echo.
echo  桌面客户端: dist\十三香小龙虾.exe
echo  安装包:     dist\installer\十三香小龙虾-v3.5.2-Setup.exe
echo ══════════════════════════════════════════
pause
