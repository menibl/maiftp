$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

python -m pip install pyinstaller pillow

pyinstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name MaiFocusCameraSimulator `
  camera_simulator.py

$packageDir = Join-Path $PSScriptRoot "camera_simulator_package"
$exe = Join-Path $PSScriptRoot "dist\MaiFocusCameraSimulator.exe"

if (Test-Path $packageDir) {
    Remove-Item -LiteralPath $packageDir -Recurse -Force
}

New-Item -ItemType Directory -Path $packageDir | Out-Null
Copy-Item -LiteralPath $exe -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README_CAMERA_SIMULATOR.md") -Destination $packageDir

@'
@echo off
start "" "%~dp0MaiFocusCameraSimulator.exe"
'@ | Set-Content -Encoding ASCII (Join-Path $packageDir "Start Camera Simulator.bat")

Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath (Join-Path $PSScriptRoot "MaiFocusCameraSimulator-Windows.zip") -Force

Write-Host "Package ready:"
Write-Host (Join-Path $PSScriptRoot "MaiFocusCameraSimulator-Windows.zip")
