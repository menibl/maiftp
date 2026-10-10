$ErrorActionPreference = "Continue"

$logPath = "C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-service.log"
$ftpPort = 2121

try {
    $host.UI.RawUI.WindowTitle = "MaiFocus Edge Agent Live Log"
} catch {
}

Clear-Host
Write-Host "MaiFocus Edge Agent Live Log"
Write-Host "================================"
Write-Host ""
Write-Host "This window is only a live log viewer."
Write-Host "It does not start another FTP server and does not change settings."
Write-Host ""
Write-Host "Log file: $logPath"
Write-Host ""

while (-not (Test-Path -LiteralPath $logPath)) {
    Write-Host "Waiting for Edge Agent log file..."
    Start-Sleep -Seconds 3
}

$ftp = Get-NetTCPConnection -LocalPort $ftpPort -State Listen -ErrorAction SilentlyContinue
if ($ftp) {
    Write-Host "[OK] FTP is listening on TCP $ftpPort."
} else {
    Write-Host "[WARN] FTP is not listening on TCP $ftpPort right now."
}

Write-Host ""
Write-Host "Showing last 100 log lines and following new lines."
Write-Host "Press Ctrl+C to close this viewer."
Write-Host ""

Get-Content -LiteralPath $logPath -Tail 100 -Wait
