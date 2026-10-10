param(
    [Parameter(Mandatory=$true)][string]$FfmpegPath
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$stage = Join-Path $root 'release-staging'
$assets = Join-Path $root 'release-assets'
if ((Test-Path $stage) -or (Test-Path $assets)) {
    throw 'Release staging/output already exists. Use a fresh checkout for packaging.'
}
$binaries = @{
    '01-EdgeAgent-FTP\MaiFocusEdgeAgent.exe' = Join-Path $root 'dist\MaiFocusEdgeAgent.exe'
    '02-RTSP-Snapshot-Service\MaiFocusRtspSnapshotService.exe' = Join-Path $root 'rtsp_snapshot_service\dist\MaiFocusRtspSnapshotService.exe'
    '02-RTSP-Snapshot-Service\ffmpeg.exe' = $FfmpegPath
    '03-Camera-Simulator\MaiFocusCameraSimulator.exe' = Join-Path $root 'dist-simulator\MaiFocusCameraSimulator.exe'
}
foreach ($binary in $binaries.Values) {
    if (!(Test-Path -LiteralPath $binary -PathType Leaf)) { throw "Missing binary: $binary" }
}
New-Item -ItemType Directory -Path $stage,$assets | Out-Null
$kitName = 'MaiFocus-Customer-PC-Install-Kit'
$kit = Join-Path $stage $kitName
$tracked = & git -C $root ls-files
if ($LASTEXITCODE -ne 0) { throw 'Cannot list tracked source files' }
foreach ($relative in $tracked) {
    if (!$relative.StartsWith($kitName + '/')) { continue }
    $target = Join-Path $stage $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
    Copy-Item -LiteralPath (Join-Path $root $relative) -Destination $target
}
foreach ($relative in $binaries.Keys) {
    Copy-Item -LiteralPath $binaries[$relative] -Destination (Join-Path $kit $relative)
}
Copy-Item -LiteralPath (Join-Path $root 'README.md') -Destination (Join-Path $kit 'BACKUP-README.md')
Add-Type -AssemblyName System.IO.Compression.FileSystem
$packages = [ordered]@{
    'MaiFocus-Customer-PC-Install-Kit-v3.18-backup.1.zip' = $kit
    'MaiFocusEdgeAgent-Windows-v3.18-backup.1.zip' = Join-Path $kit '01-EdgeAgent-FTP'
    'MaiFocusRtspSnapshotService-Windows-v3.18-backup.1.zip' = Join-Path $kit '02-RTSP-Snapshot-Service'
    'MaiFocusCameraSimulator-Windows-v3.18-backup.1.zip' = Join-Path $kit '03-Camera-Simulator'
    'MaiFocusRtspSnapshotService-GCP-v3.18-backup.1.zip' = Join-Path $root 'MaiFocusRtspSnapshotService-GCP'
}
foreach ($entry in $packages.GetEnumerator()) {
    [IO.Compression.ZipFile]::CreateFromDirectory($entry.Value, (Join-Path $assets $entry.Key))
    Write-Host "Packaged $($entry.Key)"
}
$sourceArchive = Join-Path $assets 'MaiFocus-Source-v3.18-backup.1.zip'
& git -C $root archive --format=zip "--output=$sourceArchive" HEAD
if ($LASTEXITCODE -ne 0) { throw 'Source archive failed' }
$checksums = Get-ChildItem $assets -Filter '*.zip' | Sort-Object Name | ForEach-Object {
    $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
    "$($hash.Hash.ToLowerInvariant())  $($_.Name)"
}
$checksums | Set-Content -LiteralPath (Join-Path $assets 'SHA256SUMS.txt') -Encoding ascii
Write-Host "Release assets ready: $assets"
