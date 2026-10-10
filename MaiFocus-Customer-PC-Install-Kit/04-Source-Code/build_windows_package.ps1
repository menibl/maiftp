$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

pyinstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --exclude-module transformers `
  --exclude-module nltk `
  --exclude-module librosa `
  --exclude-module sklearn `
  --exclude-module sqlalchemy `
  --exclude-module openpyxl `
  --exclude-module yt_dlp `
  --exclude-module jupyter `
  --exclude-module notebook `
  --name MaiFocusEdgeAgent `
  maifocus_edge_agent.py

$packageDir = Join-Path $PSScriptRoot "package"
$distDir = Join-Path $PSScriptRoot "dist"
$exe = Join-Path $distDir "MaiFocusEdgeAgent.exe"

if (Test-Path $packageDir) {
    Remove-Item -LiteralPath $packageDir -Recurse -Force
}

New-Item -ItemType Directory -Path $packageDir | Out-Null
Copy-Item -LiteralPath $exe -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README_PACKAGE.md") -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "install_firewall_rules.ps1") -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Start-MaiFocusEdgeAgent-Auto.ps1") -Destination $packageDir
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Install-MaiFocusEdgeAgent-Startup.ps1") -Destination $packageDir

@'
@echo off
start "" "%~dp0MaiFocusEdgeAgent.exe"
'@ | Set-Content -Encoding ASCII (Join-Path $packageDir "Start MaiFocus Edge Agent.bat")

@'
@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0Start-MaiFocusEdgeAgent-Auto.ps1"
'@ | Set-Content -Encoding ASCII (Join-Path $packageDir "Start Auto Default Settings.bat")

@'
@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0Start-MaiFocusEdgeAgent-Auto.ps1" -NoPrompt
'@ | Set-Content -Encoding ASCII (Join-Path $packageDir "Start Silent From Saved Settings.bat")

@'
@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0Install-MaiFocusEdgeAgent-Startup.ps1"
'@ | Set-Content -Encoding ASCII (Join-Path $packageDir "Install Startup Autostart.bat")

@'
@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0install_firewall_rules.ps1"
pause
'@ | Set-Content -Encoding ASCII (Join-Path $packageDir "Install Firewall Rules - Run as Administrator.bat")

Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath (Join-Path $PSScriptRoot "MaiFocusEdgeAgent-Windows.zip") -Force

Write-Host "Package ready:"
Write-Host (Join-Path $PSScriptRoot "MaiFocusEdgeAgent-Windows.zip")
