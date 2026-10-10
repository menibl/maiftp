$ErrorActionPreference = "Stop"
. "$PSScriptRoot\00-MASTER-CONFIG.ps1"

$sourceStartScript = Join-Path $PSScriptRoot "Start-RTSP-From-Saved-Config.ps1"
$rtspRuntimeDir = "C:\ProgramData\MaiFocusRtspSnapshotService"
$startScript = Join-Path $rtspRuntimeDir "Start-RTSP-From-Saved-Config.ps1"

if (-not (Test-Path $sourceStartScript)) {
    throw "Missing RTSP start script: $sourceStartScript"
}

New-Item -ItemType Directory -Force -Path $rtspRuntimeDir | Out-Null
Copy-Item -LiteralPath $sourceStartScript -Destination $startScript -Force

$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT20S"
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
    -TaskName "MaiFocus RTSP Snapshot Service Auto Start" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logonPrincipal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask `
    -TaskName "MaiFocus RTSP Snapshot Service User Logon Fallback" `
    -Action $action `
    -Trigger $logonTrigger `
    -Principal $logonPrincipal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "[OK] Startup task installed: MaiFocus RTSP Snapshot Service Auto Start"
Write-Host "The RTSP Snapshot Service will start automatically when Windows boots, before user logon."
Write-Host "[OK] Logon fallback task installed: MaiFocus RTSP Snapshot Service User Logon Fallback"
