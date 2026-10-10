$ErrorActionPreference = "Continue"

$kitRoot = $PSScriptRoot
$agentHome = "C:\ProgramData\MaiFocusEdgeAgent"
$agentStartScript = Join-Path $agentHome "bin\Start-EdgeAgent-From-Saved-Config.ps1"
if (-not (Test-Path $agentStartScript)) {
    $agentStartScript = Join-Path $kitRoot "Start-EdgeAgent-From-Saved-Config.ps1"
}
$rtspStartScript = "C:\ProgramData\MaiFocusRtspSnapshotService\Start-RTSP-From-Saved-Config.ps1"
if (-not (Test-Path $rtspStartScript)) {
    $rtspStartScript = Join-Path $kitRoot "Start-RTSP-From-Saved-Config.ps1"
}
$logDir = "C:\ProgramData\MaiFocusEdgeAgent\logs"
$logPath = Join-Path $logDir "service-watchdog.log"
$configPath = "C:\ProgramData\MaiFocusEdgeAgent\config.json"
$healthPath = "C:\ProgramData\MaiFocusEdgeAgent\agent_health.json"
$ftpPort = 2121
$rtspPort = 8088
$maxHealthAgeSeconds = 180
$maxPendingAgeSeconds = 180
$maxMissingHealthSeconds = 180

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (Test-Path $configPath) {
    try {
        $edgeConfig = Get-Content -Raw -Path $configPath | ConvertFrom-Json
        if ($edgeConfig.ftp_port) { $ftpPort = [int]$edgeConfig.ftp_port }
    } catch {
        # Keep defaults.
    }
}

function Write-WatchdogLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Encoding UTF8 -Path $logPath -Value $line
    Write-Host $line
}

function Ensure-Tailscale {
    $service = Get-Service -Name "Tailscale" -ErrorAction SilentlyContinue
    if (-not $service) {
        $service = Get-Service -Name "TailscaleService" -ErrorAction SilentlyContinue
    }
    if (-not $service) {
        Write-WatchdogLog "Tailscale service not found. Install Tailscale first if remote access is required."
        return
    }

    try {
        sc.exe config $service.Name start= auto | Out-Null
        Set-Service -Name $service.Name -StartupType Automatic -ErrorAction SilentlyContinue
    } catch {
        Write-WatchdogLog "Could not set Tailscale startup mode: $($_.Exception.Message)"
    }

    $service = Get-Service -Name $service.Name -ErrorAction SilentlyContinue
    if ($service.Status -ne "Running") {
        try {
            Start-Service -Name $service.Name
            Write-WatchdogLog "Started Tailscale service ($($service.Name))."
        } catch {
            Write-WatchdogLog "Failed to start Tailscale service: $($_.Exception.Message)"
        }
    } else {
        Write-WatchdogLog "Tailscale service already running ($($service.Name))."
    }
}

function Test-ListeningPort {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-ListeningPort {
    param(
        [int]$Port,
        [int]$Seconds = 90
    )
    for ($i = 1; $i -le $Seconds; $i++) {
        if (Test-ListeningPort -Port $Port) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Get-UtcDateAgeSeconds {
    param([string]$DateValue)
    if ([string]::IsNullOrWhiteSpace($DateValue)) {
        return [double]::PositiveInfinity
    }

    try {
        $date = [datetimeoffset]::Parse($DateValue).UtcDateTime
        return ([datetime]::UtcNow - $date).TotalSeconds
    } catch {
        return [double]::PositiveInfinity
    }
}

function Restart-EdgeAgent {
    param([string]$Reason)

    Write-WatchdogLog "Restarting MaiFocusEdgeAgent: $Reason"
    Get-Process -Name "MaiFocusEdgeAgent" -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3

    if (-not (Test-Path $agentStartScript)) {
        Write-WatchdogLog "Missing Edge Agent start script: $agentStartScript"
        return
    }

    try {
        $process = Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$agentStartScript`"" `
            -WindowStyle Hidden `
            -PassThru
        Write-WatchdogLog "Started MaiFocusEdgeAgent restart helper PID=$($process.Id). Waiting for FTP TCP $ftpPort."
        if (Wait-ListeningPort -Port $ftpPort -Seconds 120) {
            Write-WatchdogLog "MaiFocusEdgeAgent FTP is listening after watchdog restart."
        } else {
            $processes = @(Get-Process -Name "MaiFocusEdgeAgent" -ErrorAction SilentlyContinue)
            Write-WatchdogLog "MaiFocusEdgeAgent restart helper finished/started, but FTP TCP $ftpPort is still not listening. Process count=$($processes.Count)."
        }
    } catch {
        Write-WatchdogLog "Failed to restart MaiFocusEdgeAgent: $($_.Exception.Message)"
    }
}

function Test-EdgeAgentHealth {
    if (-not (Test-ListeningPort -Port $ftpPort)) {
        return
    }

    $processes = @(Get-Process -Name "MaiFocusEdgeAgent" -ErrorAction SilentlyContinue)
    $oldestProcess = $processes |
        Where-Object { $_.StartTime } |
        Sort-Object StartTime |
        Select-Object -First 1
    $processAge = [double]::PositiveInfinity
    if ($oldestProcess) {
        $processAge = ((Get-Date) - $oldestProcess.StartTime).TotalSeconds
    }

    if (-not (Test-Path $healthPath)) {
        if ($processes.Count -gt 0) {
            if ($oldestProcess) {
                if ($processAge -gt $maxMissingHealthSeconds) {
                    Restart-EdgeAgent ("health file missing for {0:n0}s > {1}s" -f $processAge, $maxMissingHealthSeconds)
                    return
                }
            }
            Write-WatchdogLog "Health file not found yet: $healthPath"
        }
        return
    }

    try {
        $health = Get-Content -Raw -Path $healthPath | ConvertFrom-Json
    } catch {
        Restart-EdgeAgent "health file is unreadable: $($_.Exception.Message)"
        return
    }

    $status = [string]$health.status
    if ($status -eq "paused_by_mission" -or $status -eq "stopped") {
        Write-WatchdogLog "Edge health OK: status=$status."
        return
    }

    $healthAge = Get-UtcDateAgeSeconds ([string]$health.updated_at_utc)
    if ($healthAge -gt $maxHealthAgeSeconds) {
        if ($processAge -le $maxMissingHealthSeconds) {
            Write-WatchdogLog ("Edge health is stale, but process is new ({0:n0}s). Waiting for fresh health." -f $processAge)
            return
        }
        Restart-EdgeAgent ("health stale for {0:n0}s > {1}s" -f $healthAge, $maxHealthAgeSeconds)
        return
    }

    $pendingCount = 0
    if ($null -ne $health.pending_count) {
        $pendingCount = [int]$health.pending_count
    }
    $oldestPendingAge = 0.0
    if ($null -ne $health.oldest_pending_age_seconds) {
        $oldestPendingAge = [double]$health.oldest_pending_age_seconds
    }
    $lastProcessedAge = Get-UtcDateAgeSeconds ([string]$health.last_image_processed_utc)

    if (
        $pendingCount -gt 0 `
        -and $oldestPendingAge -gt $maxPendingAgeSeconds `
        -and $lastProcessedAge -gt $maxPendingAgeSeconds
    ) {
        Restart-EdgeAgent (
            "image pipeline stuck: pending=$pendingCount, oldest_pending={0:n0}s, last_processed={1:n0}s" -f
            $oldestPendingAge,
            $lastProcessedAge
        )
        return
    }

    $yoloAge = Get-UtcDateAgeSeconds ([string]$health.last_yolo_started_utc)
    $yoloFinishedAge = Get-UtcDateAgeSeconds ([string]$health.last_yolo_finished_utc)
    if ($status -eq "running_yolo" -and $yoloAge -gt $maxPendingAgeSeconds -and $yoloFinishedAge -gt $maxPendingAgeSeconds) {
        Restart-EdgeAgent ("YOLO appears stuck for {0:n0}s" -f $yoloAge)
        return
    }

    Write-WatchdogLog (
        "Edge health OK: status=$status, pending=$pendingCount, oldest_pending={0:n0}s, health_age={1:n0}s." -f
        $oldestPendingAge,
        $healthAge
    )
}

function Ensure-Process {
    param(
        [string]$Name,
        [string]$StartScript,
        [int]$Port = 0
    )

    $processes = @(Get-Process -Name $Name -ErrorAction SilentlyContinue)
    if ($processes.Count -gt 0) {
        if ($Port -le 0 -or (Test-ListeningPort -Port $Port)) {
            Write-WatchdogLog "$Name already running; port $Port is listening."
            return
        }

        Write-WatchdogLog "$Name process exists, but port $Port is not listening. Restarting process."
        $processes | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }

    if (-not (Test-Path $StartScript)) {
        Write-WatchdogLog "Missing start script for $Name`: $StartScript"
        return
    }

    try {
        $process = Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$StartScript`"" `
            -WindowStyle Hidden `
            -PassThru
        if ($Port -gt 0) {
            Write-WatchdogLog "Started $Name helper PID=$($process.Id) via $StartScript. Waiting for port $Port."
            if (Wait-ListeningPort -Port $Port -Seconds 120) {
                Write-WatchdogLog "$Name port $Port is listening after start."
            } else {
                $processes = @(Get-Process -Name $Name -ErrorAction SilentlyContinue)
                Write-WatchdogLog "$Name start helper returned, but port $Port is still not listening. Process count=$($processes.Count)."
            }
        } else {
            Write-WatchdogLog "Started $Name via $StartScript."
        }
    } catch {
        Write-WatchdogLog "Failed to start $Name`: $($_.Exception.Message)"
    }
}

Ensure-Tailscale
Ensure-Process -Name "MaiFocusEdgeAgent" -StartScript $agentStartScript -Port $ftpPort
Test-EdgeAgentHealth
Ensure-Process -Name "MaiFocusRtspSnapshotService" -StartScript $rtspStartScript -Port $rtspPort
