$ErrorActionPreference = "Stop"

New-NetFirewallRule `
  -DisplayName "MaiFocus Edge FTP 2121" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 2121 `
  -Profile Any `
  -ErrorAction SilentlyContinue | Out-Null

New-NetFirewallRule `
  -DisplayName "MaiFocus Edge FTP Passive 50000-50100" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 50000-50100 `
  -Profile Any `
  -ErrorAction SilentlyContinue | Out-Null

Write-Host "Firewall rules installed."
