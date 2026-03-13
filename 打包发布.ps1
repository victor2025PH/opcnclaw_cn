# ╔══════════════════════════════════════════════════════════════╗
# ║        OpenClaw Voice — 打包发布脚本                        ║
# ║  在你的主机上运行，生成可分发的安装包                         ║
# ╚══════════════════════════════════════════════════════════════╝
#
# 使用方式：在项目根目录执行
#   .\打包发布.ps1
# 输出：OpenClaw-Voice-v1.x.x-win64.zip（放到桌面）

$ProjectDir = $PSScriptRoot
$Version    = "1.0.0"
$OutName    = "OpenClaw-Voice-v$Version-win64"
$OutDir     = "$env:USERPROFILE\Desktop\$OutName"
$OutZip     = "$env:USERPROFILE\Desktop\$OutName.zip"

# ── 排除不打包的内容 ──────────────────────────────────────────
$ExcludeDirs = @(
    "venv", ".venv", "__pycache__", ".git", ".pytest_cache",
    ".mypy_cache", "*.egg-info", "dist", "build", "logs",
    "certs",       # 每台机器重新生成
    "node_modules"
)
$ExcludeFiles = @(
    ".env",        # 含 API Key，绝对不能打包！
    "*.pyc", "*.pyo", "*.pyd",
    "uv.lock",
    "glm_error.txt",
    "*.log"
)

Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     OpenClaw Voice  打包发布工具              ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  源码目录: $ProjectDir" -ForegroundColor Gray
Write-Host "  输出文件: $OutZip" -ForegroundColor Gray
Write-Host ""

# 清理旧目录
if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

# ── 复制文件 ──────────────────────────────────────────────────
Write-Host "📦 打包中..." -ForegroundColor Yellow

function Copy-Filtered {
    param($src, $dst)
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    foreach ($item in Get-ChildItem -Path $src -Force) {
        $skip = $false
        foreach ($pat in ($ExcludeDirs + $ExcludeFiles)) {
            if ($item.Name -like $pat) { $skip = $true; break }
        }
        if ($skip) { continue }
        if ($item.PSIsContainer) {
            Copy-Filtered -src $item.FullName -dst (Join-Path $dst $item.Name)
        } else {
            Copy-Item $item.FullName -Destination $dst -Force
        }
    }
}

Copy-Filtered -src $ProjectDir -dst $OutDir

# ── 生成版本信息文件 ──────────────────────────────────────────
$buildTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
@"
OpenClaw Voice AI — 安装包信息
================================
版本:     $Version
打包时间: $buildTime
支持系统: Windows 10/11 (64位) / macOS 12+ (Intel & Apple Silicon)
Python:   3.10+ (安装脚本自动处理)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Windows 安装步骤
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. 解压此 ZIP 包到任意目录（如 D:\OpenClaw）
  2. 右键 PowerShell → 以管理员身份运行
  3. cd 到解压目录
  4. 执行: Set-ExecutionPolicy Bypass -Scope Process -Force
  5. 执行: .\一键安装.ps1
  6. 按提示填入 API Key
  7. 完成！浏览器自动打开

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  macOS 安装步骤
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  1. 解压此 ZIP 包到任意目录（如 ~/OpenClaw）
  2. 打开「终端」应用
  3. cd 到解压目录
  4. 执行: chmod +x 一键安装-Mac.sh
  5. 执行: ./一键安装-Mac.sh
  6. 按提示填入 API Key
  7. 完成！浏览器自动打开

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  文件说明
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  一键安装.ps1        — Windows 安装脚本
  一键安装-Mac.sh     — macOS 安装脚本
  .env.template      — 配置模板（安装时自动复制）
  requirements.txt   — Python 依赖列表
  src/               — 服务器和前端源码
  部署指南.md         — 详细部署说明

注意: .env 文件含 API Key，请勿分享！
"@ | Out-File "$OutDir\安装说明.txt" -Encoding UTF8

# ── 创建 ZIP ──────────────────────────────────────────────────
Write-Host "🗜️  压缩中..." -ForegroundColor Yellow
if (Test-Path $OutZip) { Remove-Item $OutZip -Force }
Compress-Archive -Path "$OutDir\*" -DestinationPath $OutZip -CompressionLevel Optimal

# ── 统计 ──────────────────────────────────────────────────────
$zipSize = [math]::Round((Get-Item $OutZip).Length / 1MB, 2)
$fileCount = (Get-ChildItem $OutDir -Recurse -File).Count
Remove-Item $OutDir -Recurse -Force

Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║           ✅ 打包完成！                       ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  输出文件: $OutZip" -ForegroundColor White
Write-Host "  文件大小: ${zipSize} MB（不含 Python 依赖）" -ForegroundColor White
Write-Host "  文件数量: $fileCount 个" -ForegroundColor White
Write-Host ""
Write-Host "  发送给其他人后，对方安装步骤：" -ForegroundColor Cyan
Write-Host "  1. 解压 ZIP 到任意目录" -ForegroundColor Gray
Write-Host "  2. 右键 PowerShell → 以管理员运行" -ForegroundColor Gray
Write-Host "  3. 进入解压目录，运行 .\一键安装.ps1" -ForegroundColor Gray
Write-Host "  4. 填入 API Key，等待依赖下载完成（约 10 分钟）" -ForegroundColor Gray
Write-Host "  5. 完成，开机自动启动" -ForegroundColor Gray
Write-Host ""
Write-Host "  ⚠️  提醒：分发前确认 .env 文件未包含在 ZIP 中！" -ForegroundColor Yellow

# 打开桌面
explorer.exe $env:USERPROFILE\Desktop

Read-Host "`n按 Enter 退出"
