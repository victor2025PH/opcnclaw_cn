# ╔══════════════════════════════════════════════════════════════╗
# ║        OpenClaw Voice AI — 一键安装脚本                     ║
# ║  支持 Windows 10/11，以管理员身份运行                        ║
# ╚══════════════════════════════════════════════════════════════╝
#
# 使用方式：
#   右键 -> 以管理员身份运行 PowerShell
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   .\一键安装.ps1

param(
    [switch]$Silent,       # 静默安装（跳过交互确认）
    [switch]$NoService,    # 不安装为 Windows 服务
    [switch]$NoModel,      # 跳过 Whisper 模型预下载
    [string]$InstallDir = "C:\OpenClaw"
)

# ── 颜色输出 ─────────────────────────────────────────────────────
function Write-Step  { param($n,$t) Write-Host "`n[$n/8] $t" -ForegroundColor Cyan }
function Write-OK    { param($t) Write-Host "  ✓ $t" -ForegroundColor Green }
function Write-Warn  { param($t) Write-Host "  ⚠ $t" -ForegroundColor Yellow }
function Write-Fail  { param($t) Write-Host "  ✗ $t" -ForegroundColor Red }
function Write-Info  { param($t) Write-Host "    $t" -ForegroundColor Gray }
function Ask-YesNo   {
    param($prompt, $default = $true)
    if ($Silent) { return $default }
    $yn = if ($default) { "Y/n" } else { "y/N" }
    $r = Read-Host "$prompt [$yn]"
    if ($r -eq '') { return $default }
    return ($r -match '^[yY]')
}

# ─────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║     OpenClaw Voice AI  安装程序              ║" -ForegroundColor Magenta
Write-Host "║     AI 语音助手 · 手势控制 · 远程桌面         ║" -ForegroundColor Magenta
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Magenta
Write-Host ""

# ── 0. 管理员权限检查 ─────────────────────────────────────────
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Fail "请以【管理员身份】运行此脚本！"
    Write-Info "右键 PowerShell 图标 → 以管理员身份运行"
    Write-Info "然后执行: Set-ExecutionPolicy Bypass -Scope Process -Force"
    Read-Host "`n按 Enter 退出"
    exit 1
}
Write-OK "管理员权限确认"

# 脚本所在目录 = 项目源码目录
$SourceDir = $PSScriptRoot
if (-NOT (Test-Path "$SourceDir\src\server\main.py")) {
    Write-Fail "找不到项目文件，请确认此脚本在 OpenClaw 项目根目录下运行"
    exit 1
}

Write-Info "安装源码目录: $SourceDir"
Write-Info "安装目标目录: $InstallDir"
if (-NOT $Silent) {
    if (-NOT (Ask-YesNo "确认安装到 $InstallDir ？")) {
        $InstallDir = Read-Host "请输入安装目录（如 D:\OpenClaw）"
    }
}

# ── 1. 检查 / 安装 Python ────────────────────────────────────────
Write-Step 1 "检查 Python 环境"

$pythonExe = $null
foreach ($candidate in @("python", "python3", "py")) {
    try {
        $ver = & $candidate --version 2>&1
        if ($ver -match "Python (3\.\d+)") {
            $major = [int]($Matches[1].Split(".")[0])
            $minor = [int]($Matches[1].Split(".")[1])
            if ($major -eq 3 -and $minor -ge 10) {
                $pythonExe = (Get-Command $candidate -ErrorAction SilentlyContinue)?.Source
                Write-OK "找到 Python $($Matches[1]) → $pythonExe"
                break
            }
        }
    } catch {}
}

if (-NOT $pythonExe) {
    Write-Warn "未找到 Python 3.10+，正在自动安装..."
    $PyUrl  = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $PyInst = "$env:TEMP\python-installer.exe"
    Write-Info "下载 Python 3.11 (~25MB)..."
    try {
        Invoke-WebRequest -Uri $PyUrl -OutFile $PyInst -UseBasicParsing -TimeoutSec 120
        Write-Info "安装 Python（静默安装）..."
        Start-Process $PyInst -ArgumentList "/quiet InstallAllUsers=1 PrependPath=1 Include_pip=1" -Wait
        # 刷新 PATH
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
        $pythonExe = (Get-Command python -ErrorAction SilentlyContinue)?.Source
        if ($pythonExe) { Write-OK "Python 安装成功: $pythonExe" }
        else { Write-Fail "Python 安装失败，请手动安装: https://python.org/downloads"; exit 1 }
    } catch {
        Write-Fail "下载失败: $_"
        Write-Info "请手动安装 Python 3.11: https://python.org/downloads"
        exit 1
    }
}

# ── 2. 复制项目文件 ──────────────────────────────────────────────
Write-Step 2 "复制项目文件到 $InstallDir"

$exclude = @("venv", ".venv", "__pycache__", ".git", ".env", "certs", "logs",
             "*.pyc", "*.pyo", "uv.lock", "*.egg-info")

if (Test-Path $InstallDir) {
    if (-NOT $Silent) {
        if (Ask-YesNo "目录已存在，是否覆盖更新？" $true) {
            # 保留 .env 和 certs
            Write-Info "保留已有 .env 和 certs..."
        }
    }
} else {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}

# 复制（排除敏感目录）
$items = Get-ChildItem -Path $SourceDir -Force | Where-Object {
    $name = $_.Name
    -not ($exclude | Where-Object { $name -like $_ })
}
foreach ($item in $items) {
    $dest = Join-Path $InstallDir $item.Name
    if ($item.PSIsContainer) {
        # 递归复制目录，排除 __pycache__ 等
        Copy-Item -Path $item.FullName -Destination $dest -Recurse -Force -ErrorAction SilentlyContinue
        # 清理目标里的 __pycache__
        Get-ChildItem -Path $dest -Recurse -Filter "__pycache__" -Directory | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Copy-Item -Path $item.FullName -Destination $dest -Force -ErrorAction SilentlyContinue
    }
}
New-Item -ItemType Directory -Force -Path "$InstallDir\logs" | Out-Null
Write-OK "文件复制完成"

# ── 3. 创建 Python 虚拟环境 + 安装依赖 ──────────────────────────
Write-Step 3 "安装 Python 依赖包（可能需要 5-15 分钟）"

$VenvDir = "$InstallDir\venv"
if (-NOT (Test-Path "$VenvDir\Scripts\python.exe")) {
    Write-Info "创建虚拟环境..."
    & $pythonExe -m venv $VenvDir
}
$VenvPython = "$VenvDir\Scripts\python.exe"
$VenvPip    = "$VenvDir\Scripts\pip.exe"

Write-Info "升级 pip..."
& $VenvPython -m pip install --upgrade pip --quiet

Write-Info "安装依赖包（请耐心等待，torch 约 2GB）..."
Write-Info "你可以去泡杯茶 ☕"
& $VenvPip install -r "$InstallDir\requirements.txt" --quiet 2>&1 | ForEach-Object {
    if ($_ -match "Successfully installed|Collecting|Downloading") {
        Write-Info $_
    }
}
if ($LASTEXITCODE -ne 0) {
    Write-Warn "部分包安装失败，尝试单独安装核心包..."
    $core = @("fastapi","uvicorn[standard]","openai","httpx","python-dotenv","loguru","qrcode[pil]","mss","pyautogui","pillow","edge-tts","faster-whisper")
    foreach ($pkg in $core) {
        & $VenvPip install $pkg --quiet
    }
}
Write-OK "依赖安装完成"

# ── 4. 配置 .env ─────────────────────────────────────────────────
Write-Step 4 "配置 API Key 和服务器参数"

$EnvFile = "$InstallDir\.env"
if (-NOT (Test-Path $EnvFile)) {
    Copy-Item "$InstallDir\.env.template" $EnvFile
    Write-Info "已从模板创建 .env"
}

if (-NOT $Silent) {
    Write-Host ""
    Write-Host "  需要填入以下 API Key（直接回车跳过，之后可手动编辑 .env）:" -ForegroundColor White
    Write-Host ""

    # 读取现有值
    $envContent = Get-Content $EnvFile -Raw

    # 智谱视觉 API
    $zhipuKey = Read-Host "  智谱视觉 API Key（GLM-4V，可在 open.bigmodel.cn 免费注册）"
    if ($zhipuKey.Trim()) {
        $envContent = $envContent -replace "ZHIPU_VISION_API_KEY=.*", "ZHIPU_VISION_API_KEY=$($zhipuKey.Trim())"
    }

    # OpenClaw Gateway Token（对话 LLM）
    Write-Host ""
    Write-Host "  LLM 对话模型（二选一）:" -ForegroundColor Gray
    Write-Host "    A. OpenClaw Gateway（需要 Token）" -ForegroundColor Gray
    Write-Host "    B. DeepSeek/OpenAI 直连（需要 API Key）" -ForegroundColor Gray
    $llmChoice = Read-Host "  选择 A 或 B（默认 B）"

    if ($llmChoice -match '^[aA]') {
        $gwToken = Read-Host "  OpenClaw Gateway Token"
        if ($gwToken.Trim()) {
            $envContent = $envContent -replace "OPENCLAW_GATEWAY_TOKEN=.*", "OPENCLAW_GATEWAY_TOKEN=$($gwToken.Trim())"
        }
    } else {
        $apiKey  = Read-Host "  OpenAI/DeepSeek API Key"
        $baseUrl = Read-Host "  API Base URL（DeepSeek 填 https://api.deepseek.com/v1，OpenAI 留空）"
        if ($apiKey.Trim()) {
            $envContent = $envContent + "`nOPENAI_API_KEY=$($apiKey.Trim())"
            if ($baseUrl.Trim()) {
                $envContent = $envContent + "`nOPENAI_BASE_URL=$($baseUrl.Trim())"
                $envContent = $envContent + "`nOPENAI_MODEL=deepseek-chat"
            }
        }
    }

    $envContent | Out-File -FilePath $EnvFile -Encoding UTF8 -NoNewline
    Write-OK ".env 配置完成（可随时编辑 $EnvFile）"
} else {
    Write-Warn "静默模式：跳过 API Key 配置，请手动编辑 $EnvFile"
}

# ── 5. 预下载 Whisper 模型 ──────────────────────────────────────
Write-Step 5 "预下载语音识别模型"
if (-NOT $NoModel) {
    Write-Info "下载 Whisper base 模型（约 145MB）..."
    & $VenvPython -c "
from faster_whisper import WhisperModel
import sys
try:
    m = WhisperModel('base', device='cpu', compute_type='int8')
    print('  ✓ 模型下载完成')
except Exception as e:
    print(f'  ⚠ 模型预下载失败（首次启动时会自动下载）: {e}')
" 2>&1 | Write-Host
} else {
    Write-Info "跳过模型预下载（首次启动时自动下载）"
}

# ── 6. 添加防火墙规则 ────────────────────────────────────────────
Write-Step 6 "配置 Windows 防火墙"
netsh advfirewall firewall delete rule name="OpenClaw-HTTP-8766"  2>$null | Out-Null
netsh advfirewall firewall delete rule name="OpenClaw-HTTPS-8765" 2>$null | Out-Null
netsh advfirewall firewall add rule name="OpenClaw-HTTP-8766"  protocol=TCP dir=in localport=8766 action=allow enable=yes | Out-Null
netsh advfirewall firewall add rule name="OpenClaw-HTTPS-8765" protocol=TCP dir=in localport=8765 action=allow enable=yes | Out-Null
Write-OK "防火墙规则已添加（端口 8765 HTTPS，8766 HTTP）"

# ── 7. 安装 Windows 服务（开机自启）────────────────────────────
Write-Step 7 "安装 Windows 服务（开机自启）"

# 创建启动脚本
$StartBat = "$InstallDir\启动服务器.bat"
@"
@echo off
cd /d "$InstallDir"
"$VenvPython" -m src.server.main
pause
"@ | Out-File -FilePath $StartBat -Encoding ASCII

$StartPs1 = "$InstallDir\start-server.ps1"
@"
Set-Location "$InstallDir"
& "$VenvPython" -m src.server.main
"@ | Out-File -FilePath $StartPs1 -Encoding UTF8

if ($NoService) {
    Write-Info "跳过服务安装（使用 启动服务器.bat 手动启动）"
} else {
    $NssmExe = "$InstallDir\tools\nssm.exe"
    New-Item -ItemType Directory -Force -Path "$InstallDir\tools" | Out-Null

    if (-NOT (Test-Path $NssmExe)) {
        Write-Info "下载 NSSM 服务管理工具..."
        $NssmZip = "$env:TEMP\nssm.zip"
        try {
            Invoke-WebRequest "https://nssm.cc/release/nssm-2.24.zip" -OutFile $NssmZip -UseBasicParsing -TimeoutSec 30
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            $zip = [System.IO.Compression.ZipFile]::OpenRead($NssmZip)
            $entry = $zip.Entries | Where-Object { $_.FullName -like "*/win64/nssm.exe" } | Select-Object -First 1
            if ($entry) {
                [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $NssmExe, $true)
            }
            $zip.Dispose()
        } catch {
            Write-Warn "NSSM 下载失败，将使用计划任务代替..."
            $NssmExe = $null
        }
    }

    $ServiceName = "OpenClawVoice"
    $existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($existing) {
        & $NssmExe stop $ServiceName 2>$null
        & $NssmExe remove $ServiceName confirm 2>$null
        Start-Sleep 2
    }

    if ($NssmExe -and (Test-Path $NssmExe)) {
        & $NssmExe install $ServiceName powershell.exe
        & $NssmExe set $ServiceName AppParameters "-ExecutionPolicy Bypass -NonInteractive -File `"$StartPs1`""
        & $NssmExe set $ServiceName AppDirectory $InstallDir
        & $NssmExe set $ServiceName DisplayName "OpenClaw Voice AI"
        & $NssmExe set $ServiceName Description "AI 语音助手 — 语音/视觉/手势控制"
        & $NssmExe set $ServiceName Start SERVICE_AUTO_START
        & $NssmExe set $ServiceName AppRestartDelay 5000
        & $NssmExe set $ServiceName AppStdout "$InstallDir\logs\stdout.log"
        & $NssmExe set $ServiceName AppStderr "$InstallDir\logs\stderr.log"
        & $NssmExe set $ServiceName AppRotateFiles 1
        & $NssmExe set $ServiceName AppRotateBytes 10485760
        & $NssmExe start $ServiceName
        Start-Sleep 3
        $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($svc -and $svc.Status -eq "Running") {
            Write-OK "Windows 服务安装成功（开机自启）"
        } else {
            Write-Warn "服务安装完成但未启动，稍后手动启动: Start-Service OpenClawVoice"
        }
    } else {
        # 备选：Task Scheduler
        Write-Info "使用 Windows 计划任务代替服务..."
        $action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$StartPs1`"" -WorkingDirectory $InstallDir
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $settings = New-ScheduledTaskSettingsSet -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3
        Register-ScheduledTask -TaskName "OpenClawVoice" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
        Write-OK "计划任务安装成功（登录时自动启动）"
    }
}

# ── 8. 创建桌面快捷方式 ─────────────────────────────────────────
Write-Step 8 "创建快捷方式"

$WshShell = New-Object -ComObject WScript.Shell
$Desktop  = [System.Environment]::GetFolderPath('Desktop')

# 启动快捷方式
$ShortcutStart = $WshShell.CreateShortcut("$Desktop\OpenClaw AI.lnk")
$ShortcutStart.TargetPath   = "powershell.exe"
$ShortcutStart.Arguments    = "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$StartPs1`""
$ShortcutStart.WorkingDirectory = $InstallDir
$ShortcutStart.Description  = "启动 OpenClaw AI 语音助手"
$ShortcutStart.Save()

# 打开界面快捷方式
$ShortcutWeb = $WshShell.CreateShortcut("$Desktop\OpenClaw AI 界面.lnk")
$ShortcutWeb.TargetPath  = "http://localhost:8766/qr"
$ShortcutWeb.Description = "打开 OpenClaw AI 界面"
$ShortcutWeb.Save()

# 配置文件快捷方式
$ShortcutCfg = $WshShell.CreateShortcut("$Desktop\OpenClaw 配置.lnk")
$ShortcutCfg.TargetPath  = "notepad.exe"
$ShortcutCfg.Arguments   = "`"$InstallDir\.env`""
$ShortcutCfg.Description = "编辑 OpenClaw AI 配置"
$ShortcutCfg.Save()

Write-OK "桌面快捷方式已创建（3 个）"

# ── 完成 ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║           ✅ 安装完成！                       ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  安装目录: $InstallDir" -ForegroundColor White
Write-Host "  配置文件: $InstallDir\.env" -ForegroundColor White
Write-Host "  日志目录: $InstallDir\logs\" -ForegroundColor White
Write-Host ""
Write-Host "  📱 手机扫码:   http://本机IP:8766/qr" -ForegroundColor Cyan
Write-Host "  💻 完整版:     https://本机IP:8765/app" -ForegroundColor Cyan
Write-Host "  🖥️  二维码展示: http://localhost:8766/qr" -ForegroundColor Cyan
Write-Host ""
Write-Host "  桌面快捷方式：" -ForegroundColor White
Write-Host "   • OpenClaw AI          → 启动服务器" -ForegroundColor Gray
Write-Host "   • OpenClaw AI 界面     → 打开浏览器界面" -ForegroundColor Gray
Write-Host "   • OpenClaw 配置        → 编辑 API Key 等配置" -ForegroundColor Gray
Write-Host ""

if (-NOT $NoService) {
    Write-Host "  服务管理命令（管理员 PowerShell）:" -ForegroundColor DarkGray
    Write-Host "    Start-Service OpenClawVoice    # 启动" -ForegroundColor DarkGray
    Write-Host "    Stop-Service  OpenClawVoice    # 停止" -ForegroundColor DarkGray
    Write-Host "    Restart-Service OpenClawVoice  # 重启" -ForegroundColor DarkGray
    Write-Host ""
}

if (Ask-YesNo "现在启动服务器并打开界面？" $true) {
    Write-Info "启动服务器..."
    if (-NOT $NoService) {
        try { Start-Service OpenClawVoice -ErrorAction SilentlyContinue } catch {}
    } else {
        Start-Process powershell -ArgumentList "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$StartPs1`""
    }
    Start-Sleep 4
    Start-Process "http://localhost:8766/qr"
}

Write-Host ""
Read-Host "按 Enter 退出安装程序"
