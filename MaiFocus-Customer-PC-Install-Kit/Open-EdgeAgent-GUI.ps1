$ErrorActionPreference = "Stop"

$agentHome = "C:\ProgramData\MaiFocusEdgeAgent"
$agentBin = Join-Path $agentHome "bin"
$installedExe = Join-Path $agentBin "MaiFocusEdgeAgent.exe"

if (-not (Test-Path -LiteralPath $installedExe)) {
    throw "Missing Edge Agent EXE: $installedExe"
}

New-Item -ItemType Directory -Force -Path $agentHome | Out-Null
$env:MAIFOCUS_AGENT_HOME = $agentHome

# Open the GUI without --auto-start. The background service keeps running FTP,
# YOLO, heartbeat, and webhooks; this window is for viewing/editing settings.
Start-Process `
    -FilePath $installedExe `
    -WorkingDirectory $agentBin `
    -WindowStyle Normal
