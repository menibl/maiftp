$ErrorActionPreference = "Continue"

$agentHome = "C:\ProgramData\MaiFocusEdgeAgent"
$agentBin = Join-Path $agentHome "bin"
$configPath = Join-Path $agentHome "config.json"
$serviceLogPath = Join-Path $agentHome "logs\edge-agent-service.log"
$installLogPath = Join-Path $agentHome "logs\edge-agent-install-start.log"
$watchdogLogPath = Join-Path $agentHome "logs\service-watchdog.log"
$healthPath = Join-Path $agentHome "agent_health.json"
$exePath = Join-Path $agentBin "MaiFocusEdgeAgent.exe"
$startScript = Join-Path $agentBin "Start-EdgeAgent-From-Saved-Config.ps1"

Write-Host "=== MaiFocus Edge Agent Startup Diagnosis ==="
Write-Host ""

Write-Host "[1] Installed files"
Get-Item $exePath,$startScript,$configPath,$healthPath -ErrorAction SilentlyContinue |
    Select-Object FullName,Length,LastWriteTime |
    Format-Table

Write-Host ""
Write-Host "[2] Config"
if (Test-Path $configPath) {
    Get-Content -Raw -Path $configPath
} else {
    Write-Host "[FAIL] Missing config: $configPath"
}

Write-Host ""
Write-Host "[3] Processes"
Get-Process -Name "MaiFocusEdgeAgent" -ErrorAction SilentlyContinue |
    Select-Object Id,SI,StartTime,CPU,Responding,Path |
    Format-Table

Write-Host ""
Write-Host "[4] Ports"
Get-NetTCPConnection -LocalPort 2121 -ErrorAction SilentlyContinue |
    Select-Object LocalAddress,LocalPort,State,OwningProcess |
    Format-Table

Write-Host ""
Write-Host "[5] Tasks"
$taskNames = @(
    "MaiFocus Edge Agent Auto Start",
    "MaiFocus Edge Agent User Logon Fallback",
    "MaiFocus Services Watchdog",
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
Write-Host "[6] Last logs"
Write-Host "--- install start log ---"
Get-Content -LiteralPath $installLogPath -Tail 80 -ErrorAction SilentlyContinue
Write-Host "--- edge service log ---"
Get-Content -LiteralPath $serviceLogPath -Tail 120 -ErrorAction SilentlyContinue
Write-Host "--- watchdog log ---"
Get-Content -LiteralPath $watchdogLogPath -Tail 120 -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "[7] Manual start attempt"
if (-not (Test-Path $startScript)) {
    Write-Host "[FAIL] Missing start script: $startScript"
    return
}

& $startScript
Start-Sleep -Seconds 20

Write-Host ""
Write-Host "[8] Port check after manual start"
Test-NetConnection 127.0.0.1 -Port 2121

Write-Host ""
Write-Host "Diagnosis complete."
