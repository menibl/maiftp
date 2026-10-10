$ErrorActionPreference = "Stop"

Write-Host "MaiFocus boot autostart repair"
Write-Host "Run this PowerShell window as Administrator."
Write-Host ""

& "$PSScriptRoot\01-Install-Windows-Firewall.ps1"
& "$PSScriptRoot\03-Install-Startup-Autostart.ps1"
& "$PSScriptRoot\04-Install-RTSP-Startup-Autostart.ps1"
& "$PSScriptRoot\06-Install-Service-Watchdog-Autostart.ps1"
& "$PSScriptRoot\09-Install-Log-Viewer-At-Logon.ps1"
& "$PSScriptRoot\10-Install-GUI-At-Logon.ps1"

Write-Host ""
Write-Host "[i] Running watchdog now..."
& "$PSScriptRoot\06-Ensure-MaiFocus-Services.ps1"

Start-Sleep -Seconds 5

Write-Host ""
Write-Host "[i] Checking listening ports..."
$ftp = Get-NetTCPConnection -LocalPort 2121 -State Listen -ErrorAction SilentlyContinue
$rtsp = Get-NetTCPConnection -LocalPort 8088 -State Listen -ErrorAction SilentlyContinue

if ($ftp) {
    Write-Host "[OK] FTP is listening on TCP 2121."
} else {
    Write-Host "[FAIL] FTP is not listening on TCP 2121."
}

if ($rtsp) {
    Write-Host "[OK] RTSP Snapshot Service is listening on TCP 8088."
} else {
    Write-Host "[WARN] RTSP Snapshot Service is not listening on TCP 8088."
}

Write-Host ""
Write-Host "After repair, restart Windows and test without logging in:"
Write-Host "  Test-NetConnection EDGE_IP -Port 2121"
Write-Host "  Test-NetConnection EDGE_IP -Port 8088"
Write-Host ""
Write-Host "Logs:"
Write-Host "  C:\ProgramData\MaiFocusEdgeAgent\logs\service-watchdog.log"
Write-Host "  C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-service.log"
