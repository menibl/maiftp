$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir = Split-Path -Parent $ScriptDir
$OutDir = Join-Path $RepoDir "MaiFocusRtspSnapshotService-Windows"

Set-Location $ScriptDir

if (Test-Path $OutDir) {
    Remove-Item -LiteralPath $OutDir -Recurse -Force
}

pyinstaller --noconfirm --clean --onefile --name MaiFocusRtspSnapshotService app.py

New-Item -ItemType Directory -Path $OutDir | Out-Null
Copy-Item -LiteralPath (Join-Path $ScriptDir "dist\MaiFocusRtspSnapshotService.exe") -Destination $OutDir
Copy-Item -LiteralPath (Join-Path $ScriptDir "cameras.json") -Destination $OutDir
Copy-Item -LiteralPath (Join-Path $ScriptDir "README.md") -Destination $OutDir
Copy-Item -LiteralPath (Join-Path $ScriptDir "BUILD_AND_TEST_ROUTE.md") -Destination $OutDir
Copy-Item -LiteralPath (Join-Path $ScriptDir "open_firewall_port_8088.ps1") -Destination $OutDir
Copy-Item -LiteralPath (Join-Path $ScriptDir "Open Firewall Port 8088 - Run as Administrator.bat") -Destination $OutDir

$FfmpegCmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($FfmpegCmd) {
    $FfmpegItem = Get-Item $FfmpegCmd.Source
    $FfmpegSource = $FfmpegCmd.Source
    if ($FfmpegItem.Target) {
        $FfmpegSource = $FfmpegItem.Target[0]
    }
    Copy-Item -LiteralPath $FfmpegSource -Destination (Join-Path $OutDir "ffmpeg.exe")
} else {
    Write-Warning "ffmpeg was not found on this build machine. Install FFmpeg or copy ffmpeg.exe next to the service EXE on the Edge Device."
}

@'
@echo off
cd /d "%~dp0"
MaiFocusRtspSnapshotService.exe
pause
'@ | Set-Content -Encoding ASCII -Path (Join-Path $OutDir "Start MaiFocus RTSP Snapshot Service.bat")

Compress-Archive -Path (Join-Path $OutDir "*") -DestinationPath (Join-Path $RepoDir "MaiFocusRtspSnapshotService-Windows.zip") -Force

$GcpOutDir = Join-Path $RepoDir "MaiFocusRtspSnapshotService-GCP"
if (Test-Path $GcpOutDir) {
    Remove-Item -LiteralPath $GcpOutDir -Recurse -Force
}
New-Item -ItemType Directory -Path $GcpOutDir | Out-Null
Copy-Item -LiteralPath (Join-Path $ScriptDir "gcp_webhook_server.py") -Destination $GcpOutDir
Copy-Item -LiteralPath (Join-Path $ScriptDir "gcp_request_snapshot.sh") -Destination $GcpOutDir
Copy-Item -LiteralPath (Join-Path $ScriptDir "BUILD_AND_TEST_ROUTE.md") -Destination $GcpOutDir
Compress-Archive -Path (Join-Path $GcpOutDir "*") -DestinationPath (Join-Path $RepoDir "MaiFocusRtspSnapshotService-GCP.zip") -Force

Write-Host "Built package:"
Write-Host $OutDir
Write-Host (Join-Path $RepoDir "MaiFocusRtspSnapshotService-Windows.zip")
Write-Host $GcpOutDir
Write-Host (Join-Path $RepoDir "MaiFocusRtspSnapshotService-GCP.zip")
