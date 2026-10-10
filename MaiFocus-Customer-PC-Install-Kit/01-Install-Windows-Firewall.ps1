$ErrorActionPreference = "Stop"
. "$PSScriptRoot\00-MASTER-CONFIG.ps1"

function Add-MaiFocusRule {
    param(
        [string]$Name,
        [string]$Ports
    )

    $existing = Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "[=] Firewall rule already exists: $Name"
        return
    }

    New-NetFirewallRule `
        -DisplayName $Name `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $Ports `
        -Profile Any | Out-Null

    Write-Host "[+] Firewall rule added: $Name -> TCP $Ports"
}

Add-MaiFocusRule -Name "MaiFocus Edge FTP $($MaiFocusConfig.FtpPort)" -Ports $MaiFocusConfig.FtpPort
Add-MaiFocusRule -Name "MaiFocus Edge FTP Passive $($MaiFocusConfig.PassiveStart)-$($MaiFocusConfig.PassiveEnd)" -Ports "$($MaiFocusConfig.PassiveStart)-$($MaiFocusConfig.PassiveEnd)"
Add-MaiFocusRule -Name "MaiFocus RTSP Snapshot Service $($MaiFocusConfig.RtspServicePort)" -Ports $MaiFocusConfig.RtspServicePort

Write-Host ""
Write-Host "[OK] Windows Firewall rules are ready."
Write-Host "Camera FTP settings:"
Write-Host "  Port: $($MaiFocusConfig.FtpPort)"
Write-Host "  Passive ports: $($MaiFocusConfig.PassiveStart)-$($MaiFocusConfig.PassiveEnd)"
Write-Host "  User: $($MaiFocusConfig.FtpUser)"
Write-Host "  Password: $($MaiFocusConfig.FtpPassword)"
