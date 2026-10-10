$ErrorActionPreference = "Continue"
. "$PSScriptRoot\00-MASTER-CONFIG.ps1"

$agentHome = "C:\ProgramData\MaiFocusEdgeAgent"
$configPath = Join-Path $agentHome "config.json"

Write-Host "=== MaiFocus validation ==="
Write-Host ""

$versionPath = Join-Path $PSScriptRoot "VERSION.txt"
if (Test-Path $versionPath) {
    Write-Host "[0] Package version"
    Get-Content -Path $versionPath | Select-Object -First 3
    Write-Host ""
}

Write-Host "[1] Config file"
if (Test-Path $configPath) {
    Write-Host "[OK] $configPath"
    $config = Get-Content -Raw -Path $configPath | ConvertFrom-Json
    $config | Select-Object agent_id,source_name,mode,webhook_url,heartbeat_url,ftp_port,heartbeat_minutes,webhook_format | Format-List
    if ([string]::IsNullOrWhiteSpace([string]$config.webhook_token)) {
        Write-Host "[WARN] webhook_token is empty"
    } else {
        Write-Host "[OK] webhook_token is set"
    }
} else {
    Write-Host "[FAIL] Missing config: $configPath"
}

Write-Host ""
Write-Host "[2] Listening ports"
Get-NetTCPConnection -LocalPort ([int]$MaiFocusConfig.FtpPort) -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,State,OwningProcess | Format-Table
Get-NetTCPConnection -LocalPort ([int]$MaiFocusConfig.RtspServicePort) -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,State,OwningProcess | Format-Table
if (-not (Get-NetTCPConnection -LocalPort ([int]$MaiFocusConfig.FtpPort) -State Listen -ErrorAction SilentlyContinue)) {
    Write-Host "[FAIL] Edge Agent FTP port $($MaiFocusConfig.FtpPort) is not listening."
    Write-Host "Edge logs:"
    Write-Host "  C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-service.log"
    Write-Host "  C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-start-script.log"
    Write-Host "  C:\ProgramData\MaiFocusEdgeAgent\logs\service-watchdog.log"
}
if (-not (Get-NetTCPConnection -LocalPort ([int]$MaiFocusConfig.RtspServicePort) -State Listen -ErrorAction SilentlyContinue)) {
    Write-Host "[WARN] RTSP port $($MaiFocusConfig.RtspServicePort) is not listening."
    Write-Host "RTSP logs:"
    Write-Host "  $PSScriptRoot\02-RTSP-Snapshot-Service\service.log"
    Write-Host "  $PSScriptRoot\02-RTSP-Snapshot-Service\service.err.log"
}

Write-Host ""
Write-Host "[3] Firewall rules"
Get-NetFirewallRule -DisplayName "MaiFocus*" -ErrorAction SilentlyContinue | Select-Object DisplayName,Enabled,Direction,Action | Format-Table

Write-Host ""
Write-Host "[4] Startup tasks"
$taskNames = @(
    "MaiFocus Edge Agent Auto Start",
    "MaiFocus Edge Agent User Logon Fallback",
    "MaiFocus RTSP Snapshot Service Auto Start",
    "MaiFocus RTSP Snapshot Service User Logon Fallback",
    "MaiFocus Services Watchdog",
    "MaiFocus Daily Image Cleanup",
    "MaiFocus Edge Agent Live Log Viewer",
    "MaiFocus Edge Agent GUI At Logon"
)
foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
    if ($task) {
        [pscustomobject]@{
            TaskName = $task.TaskName
            State = $task.State
            LastRunTime = $info.LastRunTime
            LastTaskResult = $info.LastTaskResult
            NextRunTime = $info.NextRunTime
        } | Format-List
    } else {
        Write-Host "[WARN] Missing task: $taskName"
    }
}

Write-Host ""
Write-Host "[4b] Windows services/processes"
Get-Service -Name "Tailscale" -ErrorAction SilentlyContinue | Select-Object Name,Status,StartType | Format-Table
Get-Service -Name "TailscaleService" -ErrorAction SilentlyContinue | Select-Object Name,Status,StartType | Format-Table
Get-Process -Name "MaiFocusEdgeAgent" -ErrorAction SilentlyContinue | Select-Object ProcessName,Id,StartTime | Format-Table
Get-Process -Name "MaiFocusRtspSnapshotService" -ErrorAction SilentlyContinue | Select-Object ProcessName,Id,StartTime | Format-Table

Write-Host ""
Write-Host "[4c] Cleanup logs"
Write-Host "Edge headless service log: C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-service.log"
Write-Host "Edge install start log: C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-install-start.log"
Write-Host "Watchdog log: C:\ProgramData\MaiFocusEdgeAgent\logs\service-watchdog.log"
Write-Host "Daily cleanup task log: C:\ProgramData\MaiFocusEdgeAgent\logs\image-cleanup.log"
Write-Host "Edge health file: C:\ProgramData\MaiFocusEdgeAgent\agent_health.json"

Write-Host ""
Write-Host "[5] Test GCP heartbeat endpoint"
$heartbeatUrl = ""
$webhookToken = ""
$webhookUrl = ""
$sourceName = $MaiFocusConfig.SourceName
$mode = $MaiFocusConfig.Mode
$ftpPort = [int]$MaiFocusConfig.FtpPort
if (Test-Path $configPath) {
    try {
        $edgeConfig = Get-Content -Raw -Path $configPath | ConvertFrom-Json
        $heartbeatUrl = [string]$edgeConfig.heartbeat_url
        $webhookToken = [string]$edgeConfig.webhook_token
        $webhookUrl = [string]$edgeConfig.webhook_url
        $sourceName = [string]$edgeConfig.source_name
        $mode = [string]$edgeConfig.mode
        $ftpPort = [int]$edgeConfig.ftp_port
    } catch {
        Write-Host "[WARN] Could not read Edge config for heartbeat test: $($_.Exception.Message)"
    }
}

if ([string]::IsNullOrWhiteSpace($heartbeatUrl)) {
    Write-Host "[SKIP] heartbeat_url is empty in $configPath"
    Write-Host ""
    Write-Host "Validation complete."
    return
}

$body = @{
    agent_id = "manual-validation-$env:COMPUTERNAME"
    source = $sourceName
    mission_id = ([regex]::Match($webhookUrl, "/mission-webhooks/([^/]+)/").Groups[1].Value)
    mode = $mode
    status = "validation"
    hostname = $env:COMPUTERNAME
    local_ips = @("127.0.0.1")
    ftp_port = $ftpPort
    image_folder = @{ files = 0; bytes = 0; newest_file_utc = $null }
    disk = @{ total = 0; used = 0; free = 0 }
} | ConvertTo-Json -Depth 6

try {
    $response = Invoke-WebRequest `
        -Uri $heartbeatUrl `
        -Method POST `
        -Headers @{
            "X-Webhook-Token" = $webhookToken
            "Authorization" = "Bearer $webhookToken"
        } `
        -ContentType "application/json" `
        -Body $body `
        -TimeoutSec 30 `
        -UseBasicParsing
    Write-Host "[OK] Heartbeat HTTP $($response.StatusCode)"
    Write-Host $response.Content
} catch {
    Write-Host "[FAIL] Heartbeat test failed: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Validation complete."
