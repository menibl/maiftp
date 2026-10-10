$ErrorActionPreference = "Stop"
. "$PSScriptRoot\00-MASTER-CONFIG.ps1"

$agentDir = Join-Path $PSScriptRoot "01-EdgeAgent-FTP"
$exePath = Join-Path $agentDir "MaiFocusEdgeAgent.exe"
$agentHome = "C:\ProgramData\MaiFocusEdgeAgent"
$agentBin = Join-Path $agentHome "bin"
$legacyAgentHome = Join-Path $env:USERPROFILE "MaiFocusEdgeAgent"
$imageDir = Join-Path $agentHome "hikvision_images"
$configPath = Join-Path $agentHome "config.json"
$installedExePath = Join-Path $agentBin "MaiFocusEdgeAgent.exe"
$installedStartScript = Join-Path $agentBin "Start-EdgeAgent-From-Saved-Config.ps1"
$logDir = Join-Path $agentHome "logs"
$installLogPath = Join-Path $logDir "edge-agent-install-start.log"
$serviceLogPath = Join-Path $logDir "edge-agent-service.log"
$healthPath = Join-Path $agentHome "agent_health.json"

if (-not (Test-Path $exePath)) {
    throw "Missing Edge Agent EXE: $exePath"
}

New-Item -ItemType Directory -Force -Path $agentHome | Out-Null
New-Item -ItemType Directory -Force -Path $agentBin | Out-Null
New-Item -ItemType Directory -Force -Path $imageDir | Out-Null
New-Item -ItemType Directory -Force -Path $legacyAgentHome | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-InstallLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Encoding UTF8 -Path $installLogPath -Value $line
    Write-Host $line
}

function Test-FtpReady {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-FtpReady {
    param(
        [int]$Port,
        [int]$Seconds
    )
    for ($i = 1; $i -le $Seconds; $i++) {
        if (Test-FtpReady -Port $Port) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

Get-Process -Name "MaiFocusEdgeAgent" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
cmd.exe /c "taskkill /F /IM MaiFocusEdgeAgent.exe >NUL 2>NUL"
Start-Sleep -Seconds 2

try {
    Copy-Item -LiteralPath $exePath -Destination $installedExePath -Force -ErrorAction Stop
} catch {
    if (Test-Path $installedExePath) {
        Write-Host "[WARN] Could not overwrite running Edge Agent EXE. Reusing installed EXE: $installedExePath"
        Write-Host "[WARN] Details: $($_.Exception.Message)"
    } else {
        throw
    }
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Start-EdgeAgent-From-Saved-Config.ps1") -Destination $installedStartScript -Force

$existingConfig = $null
$legacyConfigCandidates = @()
$legacyConfigCandidates += (Join-Path $legacyAgentHome "config.json")
$legacyConfigCandidates += Get-ChildItem -Path "C:\Users" -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName "MaiFocusEdgeAgent\config.json" }

$configReadPath = $null
if (Test-Path $configPath) {
    $configReadPath = $configPath
} else {
    foreach ($candidate in $legacyConfigCandidates) {
        if (Test-Path $candidate) {
            $configReadPath = $candidate
            break
        }
    }
}

if ($configReadPath) {
    try {
        $existingConfig = Get-Content -Raw -Path $configReadPath | ConvertFrom-Json
        Write-Host "[i] Existing Edge Agent config found. Preserving saved customer settings."
        Write-Host "[i] Config source: $configReadPath"
    } catch {
        Write-Host "[WARN] Existing config could not be read and will be recreated: $($_.Exception.Message)"
    }
}

function Get-ExistingOrDefault {
    param(
        [string]$Name,
        [object]$DefaultValue
    )

    if ($existingConfig -and $existingConfig.PSObject.Properties.Name -contains $Name) {
        $value = $existingConfig.$Name
        if (-not [string]::IsNullOrWhiteSpace([string]$value)) {
            return $value
        }
    }
    return $DefaultValue
}

$config = [ordered]@{
    agent_id = Get-ExistingOrDefault "agent_id" $env:COMPUTERNAME
    source_name = Get-ExistingOrDefault "source_name" $MaiFocusConfig.SourceName
    mode = Get-ExistingOrDefault "mode" $MaiFocusConfig.Mode
    webhook_url = Get-ExistingOrDefault "webhook_url" $MaiFocusConfig.WebhookUrl
    webhook_token = Get-ExistingOrDefault "webhook_token" $MaiFocusConfig.WebhookToken
    ai_model_url = Get-ExistingOrDefault "ai_model_url" ""
    ai_model_name = Get-ExistingOrDefault "ai_model_name" ""
    heartbeat_url = Get-ExistingOrDefault "heartbeat_url" $MaiFocusConfig.HeartbeatUrl
    remote_command_url = Get-ExistingOrDefault "remote_command_url" $MaiFocusConfig.RemoteCommandUrl
    ftp_user = Get-ExistingOrDefault "ftp_user" $MaiFocusConfig.FtpUser
    ftp_password = Get-ExistingOrDefault "ftp_password" $MaiFocusConfig.FtpPassword
    ftp_port = [string](Get-ExistingOrDefault "ftp_port" $MaiFocusConfig.FtpPort)
    passive_start = [string](Get-ExistingOrDefault "passive_start" $MaiFocusConfig.PassiveStart)
    passive_end = [string](Get-ExistingOrDefault "passive_end" $MaiFocusConfig.PassiveEnd)
    watch_dir = Get-ExistingOrDefault "watch_dir" $imageDir
    poll_seconds = [string](Get-ExistingOrDefault "poll_seconds" "2")
    stable_seconds = [string](Get-ExistingOrDefault "stable_seconds" "2")
    webhook_timeout = [string](Get-ExistingOrDefault "webhook_timeout" "30")
    heartbeat_minutes = [string](Get-ExistingOrDefault "heartbeat_minutes" $MaiFocusConfig.HeartbeatMinutes)
    command_poll_seconds = [string](Get-ExistingOrDefault "command_poll_seconds" "60")
    yolo_model = Get-ExistingOrDefault "yolo_model" $MaiFocusConfig.YoloModel
    alert_labels = Get-ExistingOrDefault "alert_labels" "person,car"
    alert_min_confidence = [string](Get-ExistingOrDefault "alert_min_confidence" "0.6")
    send_only_alerts = [string](Get-ExistingOrDefault "send_only_alerts" "1")
    skip_yolo_when_busy = [string](Get-ExistingOrDefault "skip_yolo_when_busy" "1")
    max_cpu_percent = [string](Get-ExistingOrDefault "max_cpu_percent" "85")
    yolo_worker_count = [string](Get-ExistingOrDefault "yolo_worker_count" $MaiFocusConfig.YoloWorkerCount)
    max_yolo_queue_size = [string](Get-ExistingOrDefault "max_yolo_queue_size" $MaiFocusConfig.MaxYoloQueueSize)
    max_file_age_seconds = [string](Get-ExistingOrDefault "max_file_age_seconds" $MaiFocusConfig.MaxFileAgeSeconds)
    ignore_existing_on_start = [string](Get-ExistingOrDefault "ignore_existing_on_start" $MaiFocusConfig.IgnoreExistingOnStart)
    newest_first_when_backlogged = [string](Get-ExistingOrDefault "newest_first_when_backlogged" $MaiFocusConfig.NewestFirstWhenBacklogged)
    compress_before_upload = [string](Get-ExistingOrDefault "compress_before_upload" "1")
    upload_max_width = [string](Get-ExistingOrDefault "upload_max_width" "1280")
    upload_jpeg_quality = [string](Get-ExistingOrDefault "upload_jpeg_quality" "80")
    webhook_format = Get-ExistingOrDefault "webhook_format" "json-base64"
}

$config | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -Path $configPath
$config | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -Path (Join-Path $legacyAgentHome "config.json")

$registryPath = "HKCU:\Software\MaiFocus\EdgeAgent"
New-Item -Path $registryPath -Force | Out-Null
foreach ($key in $config.Keys) {
    New-ItemProperty -Path $registryPath -Name $key -Value ([string]$config[$key]) -PropertyType String -Force | Out-Null
}

$env:MAIFOCUS_AGENT_HOME = $agentHome
Remove-Item -LiteralPath $healthPath -Force -ErrorAction SilentlyContinue
Write-InstallLog "Starting Edge Agent headless from: $installedExePath"
$startedProcess = Start-Process `
    -FilePath $installedExePath `
    -ArgumentList "--headless-service" `
    -WorkingDirectory $agentBin `
    -WindowStyle Hidden `
    -PassThru
Write-InstallLog "Start-Process returned PID=$($startedProcess.Id). Waiting for FTP TCP $($config.ftp_port)."

$ftpReady = Wait-FtpReady -Port ([int]$config.ftp_port) -Seconds 90

if (-not $ftpReady) {
    $processes = @(Get-Process -Name "MaiFocusEdgeAgent" -ErrorAction SilentlyContinue)
    Write-InstallLog "FTP did not listen after first start. Process count: $($processes.Count). Trying saved start script."
    if (Test-Path $installedStartScript) {
        Start-Process `
            -FilePath "powershell.exe" `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$installedStartScript`"" `
            -WindowStyle Hidden | Out-Null
        $ftpReady = Wait-FtpReady -Port ([int]$config.ftp_port) -Seconds 60
    } else {
        Write-InstallLog "Saved start script missing: $installedStartScript"
    }
}

Write-Host ""
if ($ftpReady) {
    Write-Host "[OK] Edge Agent configured and FTP is listening on TCP $($config.ftp_port)."
} else {
    Write-Host "[WARN] Edge Agent was started, but FTP is not listening yet on TCP $($config.ftp_port)."
    Write-Host "Check log: C:\ProgramData\MaiFocusEdgeAgent\logs\edge-agent-service.log"
    Write-Host "Install start log: $installLogPath"
    Write-Host ""
    Write-Host "Current MaiFocusEdgeAgent processes:"
    Get-Process -Name "MaiFocusEdgeAgent" -ErrorAction SilentlyContinue |
        Select-Object Id,SI,StartTime,CPU,Path |
        Format-Table
    Write-Host ""
    Write-Host "Last Edge Agent service log lines:"
    Get-Content -LiteralPath $serviceLogPath -Tail 80 -ErrorAction SilentlyContinue
}
Write-Host "Config: $configPath"
Write-Host "Installed EXE: $installedExePath"
Write-Host "Webhook URL: $($config.webhook_url)"
Write-Host "Heartbeat URL: $($config.heartbeat_url)"
if ([string]::IsNullOrWhiteSpace([string]$config.webhook_url)) {
    Write-Host "[WARN] webhook_url is empty. Set it in the GUI, config.json, or via dynamic heartbeat."
}
if ([string]::IsNullOrWhiteSpace([string]$config.webhook_token)) {
    Write-Host "[WARN] webhook_token is empty. Set it in the GUI, config.json, or via dynamic heartbeat."
}
Write-Host "Heartbeat every $($MaiFocusConfig.HeartbeatMinutes) minute(s)."
