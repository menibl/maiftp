$ErrorActionPreference = "Continue"

param(
    [switch]$StopTailscale
)

$taskNames = @(
    "MaiFocus Edge Agent Auto Start",
    "MaiFocus Edge Agent User Logon Fallback",
    "MaiFocus RTSP Snapshot Service Auto Start",
    "MaiFocus RTSP Snapshot Service User Logon Fallback",
    "MaiFocus Services Watchdog",
    "MaiFocus Daily Image Cleanup"
)

$processNames = @(
    "MaiFocusEdgeAgent",
    "MaiFocusRtspSnapshotService"
)

Write-Host "Stopping MaiFocus scheduled tasks and processes..."
Write-Host ""

foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "[i] Task not found: $taskName"
        continue
    }

    try {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null
        Write-Host "[OK] Disabled task: $taskName"
    } catch {
        Write-Host "[WARN] Could not disable task $taskName`: $($_.Exception.Message)"
    }
}

foreach ($processName in $processNames) {
    $processes = Get-Process -Name $processName -ErrorAction SilentlyContinue
    if (-not $processes) {
        Write-Host "[i] Process not running: $processName"
        continue
    }

    foreach ($process in $processes) {
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
            Write-Host "[OK] Stopped process: $processName PID=$($process.Id)"
        } catch {
            Write-Host "[WARN] Could not stop process $processName PID=$($process.Id): $($_.Exception.Message)"
        }
    }
}

if ($StopTailscale) {
    try {
        Stop-Service -Name "Tailscale" -Force -ErrorAction Stop
        Write-Host "[OK] Stopped Tailscale service."
    } catch {
        Write-Host "[WARN] Could not stop Tailscale service: $($_.Exception.Message)"
    }
} else {
    Write-Host "[i] Tailscale was not stopped. Use -StopTailscale only if you are not connected through Tailscale."
}

Write-Host ""
Write-Host "Done. You can now delete old MaiFocus folders."
Write-Host "To enable everything again later, run RUN-ALL-AS-ADMIN.bat as Administrator."
