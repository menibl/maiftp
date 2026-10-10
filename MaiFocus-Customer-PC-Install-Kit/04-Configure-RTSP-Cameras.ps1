$ErrorActionPreference = "Stop"
. "$PSScriptRoot\00-MASTER-CONFIG.ps1"

$rtspDir = Join-Path $PSScriptRoot "02-RTSP-Snapshot-Service"
$configPath = Join-Path $rtspDir "cameras.json"
$programDataDir = "C:\ProgramData\MaiFocusEdgeAgent"
$rtspRuntimeDir = "C:\ProgramData\MaiFocusRtspSnapshotService"
$runtimeConfigPath = Join-Path $rtspRuntimeDir "cameras.json"
$persistentCsvPath = Join-Path $programDataDir "rtsp-cameras.csv"
$kitCsvPath = Join-Path $PSScriptRoot ([string]$MaiFocusConfig.RtspCameraCsv)
$csvPath = $persistentCsvPath

if (-not (Test-Path $rtspDir)) {
    throw "Missing RTSP Snapshot Service folder: $rtspDir"
}

New-Item -ItemType Directory -Force -Path $programDataDir | Out-Null
New-Item -ItemType Directory -Force -Path $rtspRuntimeDir | Out-Null

if (-not (Test-Path $persistentCsvPath)) {
    $legacyUserDir = Join-Path $env:USERPROFILE "MaiFocusEdgeAgent"
    $candidateCsvs = @(
        (Join-Path $legacyUserDir "rtsp-cameras.csv"),
        (Join-Path $legacyUserDir "RTSP-CAMERAS.CSV"),
        (Join-Path $legacyUserDir "RTSP_CAMERAS.CSV"),
        (Join-Path $legacyUserDir "RTSP_CSMERAS.CSV"),
        (Join-Path $legacyUserDir "rtsp_csmeras.csv"),
        $kitCsvPath
    )

    $sourceCsv = $candidateCsvs | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($sourceCsv) {
        Copy-Item -LiteralPath $sourceCsv -Destination $persistentCsvPath -Force
        Write-Host "[i] Created persistent customer RTSP CSV: $persistentCsvPath"
        Write-Host "[i] Source CSV: $sourceCsv"
    }
}

if ((Test-Path $persistentCsvPath) -and -not (Test-Path $kitCsvPath)) {
    Copy-Item -LiteralPath $persistentCsvPath -Destination $kitCsvPath -Force
}

if ((Test-Path $persistentCsvPath) -and (Test-Path $kitCsvPath)) {
    $persistentResolved = (Resolve-Path -LiteralPath $persistentCsvPath).Path
    $kitResolved = (Resolve-Path -LiteralPath $kitCsvPath).Path
    if ($persistentResolved -ne $kitResolved) {
        Write-Host "[i] Using persistent customer RTSP CSV: $persistentCsvPath"
        Write-Host "[i] Kit CSV is only a template and will not overwrite customer data."
    }
}

function Get-RowValue {
    param(
        [Parameter(Mandatory=$true)]$Row,
        [Parameter(Mandatory=$true)][string[]]$Names
    )

    foreach ($name in $Names) {
        $property = $Row.PSObject.Properties | Where-Object { $_.Name -ieq $name } | Select-Object -First 1
        if ($property -and -not [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            return [string]$property.Value
        }
    }
    return ""
}

function Test-EnabledValue {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $true
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    return @("1", "yes", "y", "true", "enabled", "active", "on") -contains $normalized
}

$cameras = @()

if (Test-Path $csvPath) {
    $rows = Import-Csv -LiteralPath $csvPath
    foreach ($row in $rows) {
        $enabled = Get-RowValue -Row $row -Names @("enabled", "active")
        if (-not (Test-EnabledValue -Value $enabled)) {
            continue
        }

        $name = Get-RowValue -Row $row -Names @("edge_camera_name", "camera_name", "name", "server_camera_name")
        $ip = Get-RowValue -Row $row -Names @("edge_ip", "ip", "camera_ip")
        if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($ip)) {
            Write-Host "[WARN] Skipping camera row without name/ip."
            continue
        }

        $item = [ordered]@{
            name = $name
            ip = $ip
        }

        $cameraId = Get-RowValue -Row $row -Names @("camera_id")
        if ($cameraId) {
            $item["camera_id"] = $cameraId
        }

        $username = Get-RowValue -Row $row -Names @("rtsp_username", "username", "user")
        $password = Get-RowValue -Row $row -Names @("rtsp_password", "password", "pass")
        $port = Get-RowValue -Row $row -Names @("rtsp_port", "port")
        $path = Get-RowValue -Row $row -Names @("rtsp_path", "path", "stream_path")

        if ($username) { $item["username"] = $username }
        if ($password) { $item["password"] = $password }
        if ($port) { $item["port"] = [int]$port }
        if ($path) { $item["path"] = $path }

        $cameras += $item
    }
} else {
    if (-not $MaiFocusConfig.Contains("RtspCameras") -or -not $MaiFocusConfig.RtspCameras -or $MaiFocusConfig.RtspCameras.Count -eq 0) {
        throw "RtspCameraCsv is missing and RtspCameras is empty in 00-MASTER-CONFIG.ps1"
    }

    foreach ($camera in $MaiFocusConfig.RtspCameras) {
        $name = [string]$camera.Name
        $ip = [string]$camera.Ip
        if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($ip)) {
            throw "Each RTSP camera must include Name and Ip."
        }

        $item = [ordered]@{
            name = $name
            ip = $ip
        }

        foreach ($overrideKey in @("username", "password", "port", "path")) {
            $matchingKey = $camera.Keys | Where-Object { $_ -ieq $overrideKey } | Select-Object -First 1
            if ($matchingKey) {
                $item[$overrideKey] = $camera[$matchingKey]
            }
        }

        $cameras += $item
    }
}

if ($cameras.Count -eq 0) {
    throw "No enabled RTSP cameras found. Check $csvPath"
}

$config = [ordered]@{
    rtsp = [ordered]@{
        username = [string]$MaiFocusConfig.RtspUsername
        password = [string]$MaiFocusConfig.RtspPassword
        port = [int]$MaiFocusConfig.RtspPort
        path = [string]$MaiFocusConfig.RtspPath
        transport = [string]$MaiFocusConfig.RtspTransport
    }
    server = [ordered]@{
        host = "0.0.0.0"
        port = [int]$MaiFocusConfig.RtspServicePort
        api_token = [string]$MaiFocusConfig.RtspApiToken
    }
    capture = [ordered]@{
        timeout_seconds = 12
        gap_seconds_between_cameras = 0.5
        jpeg_quality = 2
    }
    warm_capture = [ordered]@{
        enabled = $true
        max_streams = 2
        idle_timeout_seconds = 120
        frame_max_age_seconds = 5
        first_frame_timeout_seconds = 2.0
        fps = 1
    }
    cameras = $cameras
}

$json = $config | ConvertTo-Json -Depth 8
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($configPath, $json, $utf8NoBom)
[System.IO.File]::WriteAllText($runtimeConfigPath, $json, $utf8NoBom)

Write-Host "[OK] RTSP cameras configured."
Write-Host "Config: $configPath"
Write-Host "Runtime config: $runtimeConfigPath"
Write-Host "Camera count: $($cameras.Count)"
if (Test-Path $csvPath) {
    Write-Host "Camera CSV: $csvPath"
    Write-Host "This file is persistent and is not overwritten by software updates."
}
Write-Host "Default RTSP URL template:"
Write-Host "  rtsp://$($MaiFocusConfig.RtspUsername):********@<camera-ip>:$($MaiFocusConfig.RtspPort)$($MaiFocusConfig.RtspPath)"
