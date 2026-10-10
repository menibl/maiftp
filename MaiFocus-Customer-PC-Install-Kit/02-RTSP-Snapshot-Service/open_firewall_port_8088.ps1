$ErrorActionPreference = "Stop"

$RuleName = "MaiFocus RTSP Snapshot Service 8088"

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Firewall rule already exists: $RuleName"
    exit 0
}

New-NetFirewallRule `
    -DisplayName $RuleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 8088 `
    -Profile Any

Write-Host "Opened inbound TCP port 8088 for MaiFocus RTSP Snapshot Service."
