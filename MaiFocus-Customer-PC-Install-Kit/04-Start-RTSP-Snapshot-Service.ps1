$ErrorActionPreference = "Stop"
. "$PSScriptRoot\00-MASTER-CONFIG.ps1"

$sourceRtspDir = Join-Path $PSScriptRoot "02-RTSP-Snapshot-Service"
$sourceExe = Join-Path $sourceRtspDir "MaiFocusRtspSnapshotService.exe"
$sourceConfig = Join-Path $sourceRtspDir "cameras.json"
$rtspDir = "C:\ProgramData\MaiFocusRtspSnapshotService"
$exe = Join-Path $rtspDir "MaiFocusRtspSnapshotService.exe"
$configPath = Join-Path $rtspDir "cameras.json"
$stdoutLog = Join-Path $rtspDir "service.log"
$stderrLog = Join-Path $rtspDir "service.err.log"

if (-not (Test-Path $sourceExe)) {
    throw "Missing RTSP Snapshot Service EXE: $sourceExe"
}

New-Item -ItemType Directory -Force -Path $rtspDir | Out-Null
Copy-Item -LiteralPath $sourceExe -Destination $exe -Force
if (Test-Path $sourceConfig) {
    Copy-Item -LiteralPath $sourceConfig -Destination $configPath -Force
}

function Test-RtspReady {
    return [bool](Get-NetTCPConnection -LocalPort ([int]$MaiFocusConfig.RtspServicePort) -State Listen -ErrorAction SilentlyContinue)
}

function Wait-RtspReady {
    param([int]$Seconds = 45)
    for ($i = 1; $i -le $Seconds; $i++) {
        if (Test-RtspReady) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

$processes = @(Get-Process -Name "MaiFocusRtspSnapshotService" -ErrorAction SilentlyContinue)
if ($processes.Count -gt 0 -and -not (Test-RtspReady)) {
    $processes | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

if (-not (Get-Process -Name "MaiFocusRtspSnapshotService" -ErrorAction SilentlyContinue)) {
    Start-Process `
        -FilePath $exe `
        -WorkingDirectory $rtspDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog
}

$process = Get-Process -Name "MaiFocusRtspSnapshotService" -ErrorAction SilentlyContinue
$listener = Wait-RtspReady -Seconds 45

if (-not $process) {
    Write-Host "[FAIL] RTSP Snapshot Service process is not running."
    Write-Host "Check logs:"
    Write-Host "  $stdoutLog"
    Write-Host "  $stderrLog"
    exit 1
}

if (-not $listener) {
    Write-Host "[WARN] RTSP process is running, but port $($MaiFocusConfig.RtspServicePort) is not listening yet."
    Write-Host "Check logs:"
    Write-Host "  $stdoutLog"
    Write-Host "  $stderrLog"
} else {
    Write-Host "[OK] RTSP Snapshot Service is running and listening on port $($MaiFocusConfig.RtspServicePort)."
}

Write-Host "Local UI: http://127.0.0.1:$($MaiFocusConfig.RtspServicePort)/"
Write-Host "Local API: http://127.0.0.1:$($MaiFocusConfig.RtspServicePort)/api/snapshot"
Write-Host "Edit cameras here if needed: $configPath"
if ($env:USERNAME -and $env:SESSIONNAME -ne "Services") {
    Start-Process "http://127.0.0.1:$($MaiFocusConfig.RtspServicePort)/"
}
