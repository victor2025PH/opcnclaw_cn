@echo off
chcp 65001 > nul
title OpenClaw AI 语音助手
cd /d "%~dp0"
echo 正在启动 OpenClaw AI 语音助手...
python launcher.py %*
if errorlevel 1 (
    echo.
    echo 启动失败，请运行 install.bat 安装依赖
    pause
)
