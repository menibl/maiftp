param(
    [string]$WebhookUrl = "",
    [string]$WebhookToken = "",
    [string]$HeartbeatUrl = "",
    [string]$RemoteCommandUrl = "",
    [string]$SourceName = "customer-site-1"
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "Start-MaiFocusEdgeAgent-Auto.ps1"

if (-not (Test-Path $scriptPath)) {
    Write-Host "Missing Start-MaiFocusEdgeAgent-Auto.ps1"
    exit 1
}

if ([string]::IsNullOrWhiteSpace($WebhookUrl)) {
    $WebhookUrl = Read-Host "Enter Webhook URL for first setup"
}

if ([string]::IsNullOrWhiteSpace($WebhookToken)) {
    $WebhookToken = Read-Host "Enter Webhook Token"
}

if ([string]::IsNullOrWhiteSpace($WebhookUrl)) {
    Write-Host "Webhook URL is required."
    exit 1
}

& $scriptPath `
    -WebhookUrl $WebhookUrl `
    -WebhookToken $WebhookToken `
    -HeartbeatUrl $HeartbeatUrl `
    -RemoteCommandUrl $RemoteCommandUrl `
    -SourceName $SourceName `
    -Mode "ftp-yolo-webhook" `
    -YoloModel "yolo26n.pt" `
    -InstallStartupTask

Write-Host ""
Write-Host "Installed. From now on, Windows startup will run unattended."
Write-Host "It will NOT ask for Webhook URL again."
