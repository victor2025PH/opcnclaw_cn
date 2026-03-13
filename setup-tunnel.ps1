# OpenClaw Voice — Cloudflare Tunnel 内网穿透配置脚本
# 让外网手机也能访问（不限于同一 WiFi）
# 需要免费 Cloudflare 账号: https://dash.cloudflare.com/

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  OpenClaw 内网穿透配置（Cloudflare）" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

$CloudflaredUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
$CloudflaredExe = "$env:LOCALAPPDATA\cloudflared\cloudflared.exe"

# 1. 下载 cloudflared
if (-NOT (Test-Path $CloudflaredExe)) {
    Write-Host "📥 下载 cloudflared..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path (Split-Path $CloudflaredExe) | Out-Null
    try {
        Invoke-WebRequest -Uri $CloudflaredUrl -OutFile $CloudflaredExe -UseBasicParsing -TimeoutSec 60
        Write-Host "✅ 下载完成" -ForegroundColor Green
    } catch {
        Write-Host "❌ 下载失败，请手动下载: $CloudflaredUrl" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "选择穿透模式:" -ForegroundColor Cyan
Write-Host "  1. 临时隧道（无需注册，URL 每次变化）" -ForegroundColor White
Write-Host "  2. 固定隧道（需登录 Cloudflare，URL 固定）" -ForegroundColor White
Write-Host ""
$choice = Read-Host "输入 1 或 2"

if ($choice -eq "1") {
    Write-Host "`n🚀 启动临时隧道（HTTP 端口 8766）..." -ForegroundColor Yellow
    Write-Host "启动后会显示一个 trycloudflare.com 的临时 URL" -ForegroundColor Gray
    Write-Host "手机访问该 URL 即可（注意：此 URL 临时，重启后变化）`n" -ForegroundColor Gray
    & $CloudflaredExe tunnel --url http://localhost:8766

} elseif ($choice -eq "2") {
    Write-Host "`n🔐 登录 Cloudflare（将打开浏览器）..." -ForegroundColor Yellow
    & $CloudflaredExe login

    $TunnelName = Read-Host "输入隧道名称（如 openclaw）"
    $Domain     = Read-Host "输入你的域名（如 ai.yourdomain.com）"

    Write-Host "`n创建隧道..." -ForegroundColor Yellow
    & $CloudflaredExe tunnel create $TunnelName

    # 获取 tunnel ID
    $TunnelId = (& $CloudflaredExe tunnel list --output json | ConvertFrom-Json | Where-Object { $_.name -eq $TunnelName }).id

    # 创建配置文件
    $ConfigDir  = "$env:USERPROFILE\.cloudflared"
    $ConfigFile = "$ConfigDir\config.yml"
    New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null

    @"
tunnel: $TunnelId
credentials-file: $ConfigDir\$TunnelId.json

ingress:
  - hostname: $Domain
    service: http://localhost:8766
  - service: http_status:404
"@ | Out-File -FilePath $ConfigFile -Encoding UTF8

    Write-Host "`n配置 DNS..." -ForegroundColor Yellow
    & $CloudflaredExe tunnel route dns $TunnelName $Domain

    Write-Host "`n✅ 配置完成！" -ForegroundColor Green
    Write-Host "  固定访问地址: http://$Domain/chat" -ForegroundColor White
    Write-Host ""
    Write-Host "  启动隧道命令: cloudflared tunnel run $TunnelName" -ForegroundColor Gray
    Write-Host "  作为服务运行: cloudflared service install" -ForegroundColor Gray
}

Read-Host "`n按 Enter 退出"
