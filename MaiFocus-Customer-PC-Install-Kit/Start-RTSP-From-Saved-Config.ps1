$ErrorActionPreference = "Stop"

$rtspDir = "C:\ProgramData\MaiFocusRtspSnapshotService"
$exePath = Join-Path $rtspDir "MaiFocusRtspSnapshotService.exe"
$fallbackDir = Join-Path $PSScriptRoot "02-RTSP-Snapshot-Service"
if (-not (Test-Path $exePath)) {
    $rtspDir = $fallbackDir
    $exePath = Join-Path $rtspDir "MaiFocusRtspSnapshotService.exe"
}
$stdoutLog = Join-Path $rtspDir "service.log"
$stderrLog = Join-Path $rtspDir "service.err.log"

if (-not (Test-Path $exePath)) {
    throw "Missing RTSP Snapshot Service EXE: $exePath"
}

$rtspPort = 8088
$configPath = Join-Path $rtspDir "cameras.json"
if (Test-Path $configPath) {
    try {
        $config = Get-Content -Raw -Path $configPath | ConvertFrom-Json
        if ($config.server.port) { $rtspPort = [int]$config.server.port }
    } catch {
        # Keep default.
    }
}

function Test-RtspReady {
    return [bool](Get-NetTCPConnection -LocalPort $rtspPort -State Listen -ErrorAction SilentlyContinue)
}

$processes = @(Get-Process -Name "MaiFocusRtspSnapshotService" -ErrorAction SilentlyContinue)
if ($processes.Count -gt 0 -and -not (Test-RtspReady)) {
    $processes | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

if (-not (Get-Process -Name "MaiFocusRtspSnapshotService" -ErrorAction SilentlyContinue)) {
    Start-Process `
        -FilePath $exePath `
        -WorkingDirectory $rtspDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog
}
