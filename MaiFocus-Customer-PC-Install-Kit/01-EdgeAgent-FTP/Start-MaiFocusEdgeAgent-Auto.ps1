param(
    [string]$WebhookUrl = "",
    [string]$WebhookToken = "",
    [string]$HeartbeatUrl = "",
    [string]$RemoteCommandUrl = "",
    [string]$SourceName = "customer-site-1",
    [string]$AgentId = $env:COMPUTERNAME,
    [ValidateSet("ftp-webhook", "ftp-yolo-webhook", "ftp-ai-image-webhook")]
    [string]$Mode = "ftp-yolo-webhook",
    [ValidateSet("yolo26n.pt", "yolov8n.pt")]
    [string]$YoloModel = "yolo26n.pt",
    [switch]$NoPrompt,
    [switch]$InstallStartupTask
)

$ErrorActionPreference = "Stop"

$agentHome = Join-Path $env:USERPROFILE "MaiFocusEdgeAgent"
$imageDir = Join-Path $agentHome "hikvision_images"
$configPath = Join-Path $agentHome "config.json"

New-Item -ItemType Directory -Force -Path $agentHome | Out-Null
New-Item -ItemType Directory -Force -Path $imageDir | Out-Null

if ([string]::IsNullOrWhiteSpace($WebhookUrl) -and (Test-Path $configPath)) {
    try {
        $existingConfig = Get-Content -Raw -Path $configPath | ConvertFrom-Json
        $WebhookUrl = [string]$existingConfig.webhook_url
        if ([string]::IsNullOrWhiteSpace($WebhookToken)) {
            $WebhookToken = [string]$existingConfig.webhook_token
        }
        if ([string]::IsNullOrWhiteSpace($HeartbeatUrl)) {
            $HeartbeatUrl = [string]$existingConfig.heartbeat_url
        }
        if ([string]::IsNullOrWhiteSpace($RemoteCommandUrl)) {
            $RemoteCommandUrl = [string]$existingConfig.remote_command_url
        }
        if ($existingConfig.source_name) {
            $SourceName = [string]$existingConfig.source_name
        }
        if ($existingConfig.mode) {
            $Mode = [string]$existingConfig.mode
        }
        if ($existingConfig.yolo_model) {
            $YoloModel = [string]$existingConfig.yolo_model
        }
    } catch {
        Write-Host "Could not read existing config. Continuing with provided values."
    }
}

if ([string]::IsNullOrWhiteSpace($WebhookUrl) -and -not $NoPrompt) {
    $WebhookUrl = Read-Host "Enter Webhook URL"
}

if ([string]::IsNullOrWhiteSpace($WebhookUrl) -and -not $NoPrompt) {
    Write-Host "Webhook URL is required for first setup."
    Write-Host "Run this once with -WebhookUrl, then startup can run unattended."
    exit 1
}

$config = [ordered]@{
    agent_id = $AgentId
    source_name = $SourceName
    mode = $Mode
    webhook_url = $WebhookUrl
    webhook_token = $WebhookToken
    ai_model_url = ""
    ai_model_name = ""
    heartbeat_url = $HeartbeatUrl
    remote_command_url = $RemoteCommandUrl
    ftp_user = "hikvision"
    ftp_password = "CHANGE_ME_FTP_PASSWORD"
    ftp_port = "2121"
    passive_start = "50000"
    passive_end = "50100"
    watch_dir = $imageDir
    poll_seconds = "2"
    stable_seconds = "2"
    webhook_timeout = "30"
    heartbeat_minutes = "1"
    command_poll_seconds = "60"
    yolo_model = $YoloModel
    alert_labels = "person,car"
    alert_min_confidence = "0.6"
    send_only_alerts = "1"
    skip_yolo_when_busy = "1"
    max_cpu_percent = "85"
    max_yolo_queue_size = "10"
    max_file_age_seconds = "120"
    ignore_existing_on_start = "1"
    newest_first_when_backlogged = "1"
    compress_before_upload = "1"
    upload_max_width = "1280"
    upload_jpeg_quality = "80"
    webhook_format = "json-base64"
}

$config | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 -Path $configPath

$registryPath = "HKCU:\Software\MaiFocus\EdgeAgent"
New-Item -Path $registryPath -Force | Out-Null
foreach ($key in $config.Keys) {
    New-ItemProperty -Path $registryPath -Name $key -Value ([string]$config[$key]) -PropertyType String -Force | Out-Null
}

try {
    New-NetFirewallRule -DisplayName "MaiFocus Edge FTP 2121" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 2121 -Profile Any -ErrorAction SilentlyContinue | Out-Null
    New-NetFirewallRule -DisplayName "MaiFocus Edge FTP Passive 50000-50100" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 50000-50100 -Profile Any -ErrorAction SilentlyContinue | Out-Null
} catch {
    Write-Host "Firewall rules were not installed. Run as Administrator if FTP is blocked."
}

$exePath = Join-Path $PSScriptRoot "MaiFocusEdgeAgent.exe"
if (-not (Test-Path $exePath)) {
    $exePath = Join-Path $PSScriptRoot "dist\MaiFocusEdgeAgent.exe"
}

if (-not (Test-Path $exePath)) {
    Write-Host "MaiFocusEdgeAgent.exe was not found next to this script."
    exit 1
}

Start-Process -FilePath $exePath -ArgumentList "--auto-start"

if ($InstallStartupTask) {
    $scriptPath = $MyInvocation.MyCommand.Path
    $exeForTask = Join-Path $PSScriptRoot "MaiFocusEdgeAgent.exe"
    $action = New-ScheduledTaskAction -Execute $exeForTask -Argument "--headless-service"
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName "MaiFocus Edge Agent Auto Start" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
    Write-Host "Startup task installed: MaiFocus Edge Agent Auto Start"
}

Write-Host "MaiFocus Edge Agent started with default settings."
Write-Host "Camera FTP settings:"
Write-Host "  Server Address: this PC local IP"
Write-Host "  Port: 2121"
Write-Host "  Username: hikvision"
Write-Host "  Password: CHANGE_ME_FTP_PASSWORD"
