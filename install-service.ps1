# OpenClaw Voice — Windows 服务安装脚本
# 以管理员身份运行 PowerShell 执行此脚本
# 使用方式: .\install-service.ps1

$ServiceName  = "OpenClawVoice"
$DisplayName  = "OpenClaw Voice AI Server"
$Description  = "OpenClaw Voice AI 语音助手服务器（HTTP 8766 + HTTPS 8765）"
$PythonExe    = "C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe"
$WorkDir      = "D:\xlx2026\openclaw-voice"
$NssmUrl      = "https://nssm.cc/release/nssm-2.24.zip"
$NssmDir      = "$env:TEMP\nssm-2.24"
$NssmExe      = "$NssmDir\win64\nssm.exe"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  OpenClaw Voice 服务安装" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# 1. 检查管理员权限
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "❌ 请以管理员身份运行此脚本！" -ForegroundColor Red
    Write-Host "右键 PowerShell → 以管理员身份运行" -ForegroundColor Yellow
    Read-Host "按 Enter 退出"
    exit 1
}

# 2. 下载 NSSM（如未安装）
if (-NOT (Test-Path $NssmExe)) {
    Write-Host "📥 下载 NSSM 服务管理工具..." -ForegroundColor Yellow
    $ZipPath = "$env:TEMP\nssm.zip"
    try {
        Invoke-WebRequest -Uri $NssmUrl -OutFile $ZipPath -UseBasicParsing -TimeoutSec 30
        Expand-Archive -Path $ZipPath -DestinationPath $env:TEMP -Force
        Write-Host "✅ NSSM 下载完成" -ForegroundColor Green
    } catch {
        Write-Host "⚠️  自动下载失败，请手动下载 nssm.exe 到: $NssmDir\win64\" -ForegroundColor Red
        Write-Host "下载地址: https://nssm.cc/download" -ForegroundColor Yellow
        Read-Host "下载后按 Enter 继续"
        if (-NOT (Test-Path $NssmExe)) { exit 1 }
    }
}

# 3. 停止并删除旧服务（如存在）
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "🗑️  删除旧服务..." -ForegroundColor Yellow
    & $NssmExe stop $ServiceName 2>$null
    & $NssmExe remove $ServiceName confirm 2>$null
    Start-Sleep 2
}

# 4. 创建启动脚本
$StartScript = "$WorkDir\start-server.ps1"
@"
Set-Location "$WorkDir"
& "$PythonExe" -m src.server.main
"@ | Out-File -FilePath $StartScript -Encoding UTF8 -Force

# 5. 安装服务
Write-Host "🔧 安装 Windows 服务..." -ForegroundColor Yellow
& $NssmExe install $ServiceName powershell.exe
& $NssmExe set $ServiceName AppParameters "-ExecutionPolicy Bypass -NonInteractive -File `"$StartScript`""
& $NssmExe set $ServiceName AppDirectory $WorkDir
& $NssmExe set $ServiceName DisplayName $DisplayName
& $NssmExe set $ServiceName Description $Description
& $NssmExe set $ServiceName Start SERVICE_AUTO_START
& $NssmExe set $ServiceName AppRestartDelay 5000
& $NssmExe set $ServiceName AppStdout "$WorkDir\logs\service-stdout.log"
& $NssmExe set $ServiceName AppStderr "$WorkDir\logs\service-stderr.log"
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateOnline 1
& $NssmExe set $ServiceName AppRotateSeconds 86400
& $NssmExe set $ServiceName AppRotateBytes 10485760

# 创建日志目录
New-Item -ItemType Directory -Force -Path "$WorkDir\logs" | Out-Null

# 6. 添加防火墙规则
Write-Host "🔥 配置防火墙..." -ForegroundColor Yellow
netsh advfirewall firewall delete rule name="OpenClaw-HTTP-8766" 2>$null
netsh advfirewall firewall delete rule name="OpenClaw-HTTPS-8765" 2>$null
netsh advfirewall firewall add rule name="OpenClaw-HTTP-8766"  protocol=TCP dir=in localport=8766 action=allow enable=yes | Out-Null
netsh advfirewall firewall add rule name="OpenClaw-HTTPS-8765" protocol=TCP dir=in localport=8765 action=allow enable=yes | Out-Null
Write-Host "✅ 防火墙规则已添加" -ForegroundColor Green

# 7. 启动服务
Write-Host "🚀 启动服务..." -ForegroundColor Yellow
& $NssmExe start $ServiceName
Start-Sleep 3

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host "`n✅ 服务安装成功！" -ForegroundColor Green
    Write-Host ""
    Write-Host "  服务名称: $ServiceName" -ForegroundColor White
    Write-Host "  状态:     运行中" -ForegroundColor Green
    Write-Host "  开机自启: 已启用" -ForegroundColor Green
    Write-Host ""
    Write-Host "  访问地址:" -ForegroundColor Cyan
    Write-Host "  📱 手机扫码:  http://$(hostname):8766/qr" -ForegroundColor White
    Write-Host "  💻 完整版:    https://$(hostname):8765/app" -ForegroundColor White
    Write-Host ""
    Write-Host "  日志文件: $WorkDir\logs\" -ForegroundColor Gray
} else {
    Write-Host "`n⚠️  服务启动失败，请检查日志: $WorkDir\logs\service-stderr.log" -ForegroundColor Red
}

Write-Host ""
Write-Host "管理命令:" -ForegroundColor DarkGray
Write-Host "  启动: Start-Service $ServiceName" -ForegroundColor DarkGray
Write-Host "  停止: Stop-Service $ServiceName" -ForegroundColor DarkGray
Write-Host "  卸载: .\uninstall-service.ps1" -ForegroundColor DarkGray
Read-Host "`n按 Enter 退出"
