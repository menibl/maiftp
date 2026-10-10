$ErrorActionPreference = "Stop"

$cleanupScript = Join-Path $PSScriptRoot "07-Cleanup-Old-Image-Files.ps1"

if (-not (Test-Path $cleanupScript)) {
    throw "Missing cleanup script: $cleanupScript"
}

$argument = "-NoProfile -ExecutionPolicy Bypass -File `"$cleanupScript`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argument
$trigger = New-ScheduledTaskTrigger -Daily -At "03:15"
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName "MaiFocus Daily Image Cleanup" `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "[OK] Daily image cleanup task installed: MaiFocus Daily Image Cleanup"
Write-Host "Runs daily at 03:15 and deletes only image/video files older than 7 days."
Write-Host "Log: C:\ProgramData\MaiFocusEdgeAgent\logs\image-cleanup.log"
Write-Host "Cleanup was not run now. To run it manually, execute:"
Write-Host "  $cleanupScript"
