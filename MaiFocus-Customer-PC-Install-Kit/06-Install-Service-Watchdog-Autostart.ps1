$ErrorActionPreference = "Stop"

$watchdogScript = Join-Path $PSScriptRoot "06-Ensure-MaiFocus-Services.ps1"

if (-not (Test-Path $watchdogScript)) {
    throw "Missing watchdog script: $watchdogScript"
}

$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$watchdogScript`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument

$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$startupTrigger.Delay = "PT30S"

$repeatTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask `
    -TaskName "MaiFocus Services Watchdog" `
    -Action $action `
    -Trigger @($startupTrigger, $repeatTrigger) `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "[OK] Startup/watchdog task installed: MaiFocus Services Watchdog"
Write-Host "It checks Tailscale, Edge Agent, and RTSP every 1 minute and after Windows boot."

& $watchdogScript
