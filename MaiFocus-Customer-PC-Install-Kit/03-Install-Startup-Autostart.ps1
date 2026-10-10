$ErrorActionPreference = "Stop"
. "$PSScriptRoot\00-MASTER-CONFIG.ps1"

$agentHome = "C:\ProgramData\MaiFocusEdgeAgent"
$agentBin = Join-Path $agentHome "bin"
$sourceStartScript = Join-Path $PSScriptRoot "Start-EdgeAgent-From-Saved-Config.ps1"
$sourceExe = Join-Path $PSScriptRoot "01-EdgeAgent-FTP\MaiFocusEdgeAgent.exe"
$startScript = Join-Path $agentBin "Start-EdgeAgent-From-Saved-Config.ps1"
$installedExe = Join-Path $agentBin "MaiFocusEdgeAgent.exe"

if (-not (Test-Path $sourceStartScript)) {
    throw "Missing Edge Agent start script: $sourceStartScript"
}

New-Item -ItemType Directory -Force -Path $agentBin | Out-Null
Copy-Item -LiteralPath $sourceStartScript -Destination $startScript -Force
if ((Test-Path $sourceExe) -and -not (Test-Path $installedExe)) {
    Copy-Item -LiteralPath $sourceExe -Destination $installedExe -Force
} elseif (Test-Path $installedExe) {
    Write-Host "[i] Edge Agent EXE already installed: $installedExe"
}

$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`" -NoPrompt"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT15S"
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
    -TaskName "MaiFocus Edge Agent Auto Start" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logonPrincipal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask `
    -TaskName "MaiFocus Edge Agent User Logon Fallback" `
    -Action $action `
    -Trigger $logonTrigger `
    -Principal $logonPrincipal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "[OK] Startup task installed: MaiFocus Edge Agent Auto Start"
Write-Host "The Edge Agent will start headless when Windows boots, before user logon."
Write-Host "[OK] Logon fallback task installed: MaiFocus Edge Agent User Logon Fallback"
