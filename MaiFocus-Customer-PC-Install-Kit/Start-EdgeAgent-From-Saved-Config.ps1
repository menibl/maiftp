param(
    [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"

$agentHome = "C:\ProgramData\MaiFocusEdgeAgent"
$agentBin = Join-Path $agentHome "bin"
$installedExePath = Join-Path $agentBin "MaiFocusEdgeAgent.exe"
$kitExePath = Join-Path (Join-Path $PSScriptRoot "01-EdgeAgent-FTP") "MaiFocusEdgeAgent.exe"
$localExePath = Join-Path $PSScriptRoot "MaiFocusEdgeAgent.exe"

$exePath = $installedExePath
if (-not (Test-Path $exePath)) {
    if (Test-Path $localExePath) {
        $exePath = $localExePath
    } elseif (Test-Path $kitExePath) {
        $exePath = $kitExePath
    }
}

if (-not (Test-Path $exePath)) {
    throw "Missing Edge Agent EXE. Checked: $installedExePath, $localExePath, $kitExePath"
}

New-Item -ItemType Directory -Force -Path $agentHome | Out-Null
New-Item -ItemType Directory -Force -Path $agentBin | Out-Null
$env:MAIFOCUS_AGENT_HOME = $agentHome

$ftpPort = 2121
$configPath = Join-Path $agentHome "config.json"
$healthPath = Join-Path $agentHome "agent_health.json"
$logDir = Join-Path $agentHome "logs"
$startLogPath = Join-Path $logDir "edge-agent-start-script.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-StartLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Encoding UTF8 -Path $startLogPath -Value $line
    Write-Host $line
}

function Test-FtpReady {
    return [bool](Get-NetTCPConnection -LocalPort $ftpPort -State Listen -ErrorAction SilentlyContinue)
}

function Wait-FtpReady {
    param([int]$Seconds = 90)
    for ($i = 1; $i -le $Seconds; $i++) {
        if (Test-FtpReady) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

if (Test-Path $configPath) {
    try {
        $config = Get-Content -Raw -Path $configPath | ConvertFrom-Json
        if ($config.ftp_port) { $ftpPort = [int]$config.ftp_port }
    } catch {
        # Keep default.
    }
}

$processes = @(Get-Process -Name "MaiFocusEdgeAgent" -ErrorAction SilentlyContinue)
$ftpReady = Test-FtpReady

if ($ftpReady) {
    Write-StartLog "MaiFocusEdgeAgent FTP is already listening on TCP $ftpPort."
    exit 0
}

if ($processes.Count -gt 0 -and -not $ftpReady) {
    Write-StartLog "MaiFocusEdgeAgent process exists but FTP TCP $ftpPort is not listening. Stopping stale process(es): $($processes.Count)."
    $processes | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

if (-not (Get-Process -Name "MaiFocusEdgeAgent" -ErrorAction SilentlyContinue)) {
    Remove-Item -LiteralPath $healthPath -Force -ErrorAction SilentlyContinue
    Write-StartLog "Starting MaiFocusEdgeAgent headless from $exePath."
    $startedProcess = Start-Process -FilePath $exePath -ArgumentList "--headless-service" -WorkingDirectory (Split-Path -Parent $exePath) -WindowStyle Hidden -PassThru
    Write-StartLog "Start-Process returned PID=$($startedProcess.Id). Waiting for FTP TCP $ftpPort."
}

if (Wait-FtpReady -Seconds 120) {
    Write-StartLog "MaiFocusEdgeAgent FTP is listening on TCP $ftpPort."
    exit 0
}

$processes = @(Get-Process -Name "MaiFocusEdgeAgent" -ErrorAction SilentlyContinue)
Write-StartLog "MaiFocusEdgeAgent FTP did not listen on TCP $ftpPort after startup. Process count: $($processes.Count)."
exit 2
