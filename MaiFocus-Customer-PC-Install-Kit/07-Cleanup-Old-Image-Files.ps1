$ErrorActionPreference = "Continue"

$retentionDays = 7
$agentHome = "C:\ProgramData\MaiFocusEdgeAgent"
$configPath = Join-Path $agentHome "config.json"
$legacyConfigPath = Join-Path $env:USERPROFILE "MaiFocusEdgeAgent\config.json"
$logDir = Join-Path $agentHome "logs"
$logPath = Join-Path $logDir "image-cleanup.log"
$allowedExtensions = @(".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff", ".mp4", ".avi", ".mov", ".mkv")

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-CleanupLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Encoding UTF8 -Path $logPath -Value $line
    Write-Host $line
}

function Get-WatchDir {
    $pathToRead = $null
    if (Test-Path $configPath) {
        $pathToRead = $configPath
    } elseif (Test-Path $legacyConfigPath) {
        $pathToRead = $legacyConfigPath
    }

    if ($pathToRead) {
        try {
            $config = Get-Content -Raw -Path $pathToRead | ConvertFrom-Json
            if (-not [string]::IsNullOrWhiteSpace([string]$config.watch_dir)) {
                return [string]$config.watch_dir
            }
        } catch {
            Write-CleanupLog "Could not read config $pathToRead`: $($_.Exception.Message)"
        }
    }

    return (Join-Path $agentHome "hikvision_images")
}

function Test-SafeCleanupPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $false
    }

    try {
        $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
        $root = [System.IO.Path]::GetPathRoot($resolved)
        if ($resolved.TrimEnd("\") -eq $root.TrimEnd("\")) {
            return $false
        }
        if ($resolved.Length -lt 10) {
            return $false
        }
        return $true
    } catch {
        return $false
    }
}

$watchDir = Get-WatchDir

if (-not (Test-Path -LiteralPath $watchDir)) {
    Write-CleanupLog "Image folder does not exist, nothing to clean: $watchDir"
    exit 0
}

if (-not (Test-SafeCleanupPath -Path $watchDir)) {
    Write-CleanupLog "Refusing cleanup because image folder path is not safe: $watchDir"
    exit 1
}

$cutoff = (Get-Date).AddDays(-1 * $retentionDays)
$deletedCount = 0
$deletedBytes = 0
$failedCount = 0

Write-CleanupLog "Starting cleanup. Folder=$watchDir RetentionDays=$retentionDays Cutoff=$($cutoff.ToString("yyyy-MM-dd HH:mm:ss"))"

Get-ChildItem -LiteralPath $watchDir -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
        $allowedExtensions -contains $_.Extension.ToLowerInvariant() -and
        $_.LastWriteTime -lt $cutoff
    } |
    ForEach-Object {
        try {
            $size = $_.Length
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
            $deletedCount += 1
            $deletedBytes += $size
        } catch {
            $failedCount += 1
            Write-CleanupLog "Failed to delete $($_.FullName): $($_.Exception.Message)"
        }
    }

Write-CleanupLog "Cleanup finished. DeletedFiles=$deletedCount DeletedBytes=$deletedBytes Failed=$failedCount"
