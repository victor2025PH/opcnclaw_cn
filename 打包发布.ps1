# ╔══════════════════════════════════════════════════════════════╗
# ║        OpenClaw Voice — 打包发布脚本                        ║
# ║  在你的主机上运行，生成可分发的安装包                         ║
# ╚══════════════════════════════════════════════════════════════╝
#
# 使用方式：在项目根目录执行
#   .\打包发布.ps1
#   .\打包发布.ps1 -NoPause          # CI/自动化：不等待 Enter
# 输出：OpenClaw-Voice-v{version}-win64.zip（放到桌面）
# 版本：优先读取项目根目录 version.txt，与 Inno Setup / 后端一致

param(
    [switch]$NoPause
)

$ProjectDir = $PSScriptRoot
$VerFile    = Join-Path $ProjectDir "version.txt"
$Version    = if (Test-Path $VerFile) { (Get-Content $VerFile -Raw).Trim() } else { "1.0.0" }
if ([string]::IsNullOrWhiteSpace($Version)) { $Version = "1.0.0" }
$OutName    = "OpenClaw-Voice-v$Version-win64"
$OutDir     = "$env:USERPROFILE\Desktop\$OutName"
$OutZip     = "$env:USERPROFILE\Desktop\$OutName.zip"

# ── 排除不打包的内容 ──────────────────────────────────────────
$ExcludeDirs = @(
    "venv", ".venv", ".venv310", "__pycache__", ".git", ".pytest_cache",
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
        # Rust/Tauri 构建目录（仅按名称 `target` 会误伤，故用完整路径判断）
        if (-not $skip -and $item.PSIsContainer -and $item.Name -eq 'target' -and $item.FullName -like '*\src-tauri\target') {
            $skip = $true
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

# ── 生成版本信息文件（UTF-8；详细中文步骤见仓库内 安装说明.md / 部署指南.md）──
$buildTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$installNote = "OpenClaw Voice`r`nVersion: $Version`r`nBuild: $buildTime`r`n`r`nAfter unzip, run the install script in repo root - see README.`r`nKeep API keys private.`r`n"
$installNote | Out-File -FilePath "$OutDir\安装说明.txt" -Encoding utf8

# ── 创建 ZIP（.NET ZipFile：大项目比 Compress-Archive 稳定）────
Write-Host "🗜️  压缩中..." -ForegroundColor Yellow
if (Test-Path $OutZip) { Remove-Item $OutZip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$ErrorActionPreference = 'Stop'
try {
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $OutDir,
        $OutZip,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )
} catch {
    Write-Error "ZIP failed: $_"
    exit 1
}

# ── 统计 ──────────────────────────────────────────────────────
if (-not (Test-Path $OutZip)) {
    Write-Error "ZIP missing: $OutZip"
    exit 1
}
$zipSize = [math]::Round((Get-Item -LiteralPath $OutZip).Length / 1MB, 2)
$fileCount = (Get-ChildItem $OutDir -Recurse -File).Count
Remove-Item $OutDir -Recurse -Force

Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║           ✅ 打包完成！                       ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  Output: $OutZip" -ForegroundColor White
Write-Host "  Size MB: $zipSize" -ForegroundColor White
Write-Host "  Files: $fileCount" -ForegroundColor White
Write-Host ""
Write-Host "  Remind: do not pack dotenv with secrets into ZIP." -ForegroundColor Yellow

# 打开桌面（自动化模式下跳过，避免阻塞 headless）
if (-not $NoPause) {
  explorer.exe $env:USERPROFILE\Desktop
  Read-Host 'Press Enter to exit'
}
