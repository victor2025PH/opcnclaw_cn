@echo off
chcp 65001 >nul
title OpenClaw AI - Debug Mode
cd /d "%~dp0"
echo Starting OpenClaw AI...
echo.
python launcher.py %*
if errorlevel 1 (
    echo.
    echo ========================================
    echo  Launch failed! Check:
    echo   1. Run install_full.bat first
    echo   2. Configure API Key in settings
    echo   3. See logs\openclaw.log
    echo ========================================
    pause
)
