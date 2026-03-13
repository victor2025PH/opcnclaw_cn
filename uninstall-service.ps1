# OpenClaw Voice — Windows 服务卸载脚本
$ServiceName = "OpenClawVoice"
$NssmExe     = "$env:TEMP\nssm-2.24\win64\nssm.exe"

Write-Host "🗑️  卸载 OpenClaw Voice 服务..." -ForegroundColor Yellow

if (Test-Path $NssmExe) {
    & $NssmExe stop    $ServiceName 2>$null
    & $NssmExe remove  $ServiceName confirm 2>$null
} else {
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    sc.exe delete $ServiceName 2>$null
}

Write-Host "✅ 服务已卸载" -ForegroundColor Green
Read-Host "按 Enter 退出"
