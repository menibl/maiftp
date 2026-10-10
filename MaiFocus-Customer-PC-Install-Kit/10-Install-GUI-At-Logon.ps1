$ErrorActionPreference = "Stop"

$agentHome = "C:\ProgramData\MaiFocusEdgeAgent"
$agentBin = Join-Path $agentHome "bin"
$sourceGuiLauncher = Join-Path $PSScriptRoot "Open-EdgeAgent-GUI.ps1"
$installedGuiLauncher = Join-Path $agentBin "Open-EdgeAgent-GUI.ps1"

if (-not (Test-Path -LiteralPath $sourceGuiLauncher)) {
    throw "Missing GUI launcher script: $sourceGuiLauncher"
}

New-Item -ItemType Directory -Force -Path $agentBin | Out-Null
Copy-Item -LiteralPath $sourceGuiLauncher -Destination $installedGuiLauncher -Force

$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$installedGuiLauncher`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT20S"
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName "MaiFocus Edge Agent GUI At Logon" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "[OK] GUI logon task installed: MaiFocus Edge Agent GUI At Logon"
Write-Host "After Windows login, the Edge Agent GUI will open for settings/status."
Write-Host "The GUI opens without --auto-start, so it does not start a second FTP server."

$visibleGui = Get-Process -Name "MaiFocusEdgeAgent" -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -like "*MaiFocus Edge Agent*" }

if ($visibleGui) {
    Write-Host "[i] Edge Agent GUI is already open."
} else {
    Write-Host "[i] Opening Edge Agent GUI now..."
    & $installedGuiLauncher
}
