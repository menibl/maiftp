$ErrorActionPreference = "Stop"

$agentHome = "C:\ProgramData\MaiFocusEdgeAgent"
$agentBin = Join-Path $agentHome "bin"
$sourceViewer = Join-Path $PSScriptRoot "Open-EdgeAgent-Live-Log.ps1"
$installedViewer = Join-Path $agentBin "Open-EdgeAgent-Live-Log.ps1"

if (-not (Test-Path -LiteralPath $sourceViewer)) {
    throw "Missing log viewer script: $sourceViewer"
}

New-Item -ItemType Directory -Force -Path $agentBin | Out-Null
Copy-Item -LiteralPath $sourceViewer -Destination $installedViewer -Force

$argument = "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$installedViewer`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT10S"
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName "MaiFocus Edge Agent Live Log Viewer" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "[OK] Log viewer task installed: MaiFocus Edge Agent Live Log Viewer"
Write-Host "After Windows login, a live Edge Agent log window will open automatically."
Write-Host "Viewer script: $installedViewer"

$existingViewer = Get-CimInstance Win32_Process -Filter "name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*Open-EdgeAgent-Live-Log.ps1*" }

if ($existingViewer) {
    Write-Host "[i] Live log viewer is already open."
} else {
    Write-Host "[i] Opening live log viewer now..."
    Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$installedViewer`"" `
        -WindowStyle Normal
}
