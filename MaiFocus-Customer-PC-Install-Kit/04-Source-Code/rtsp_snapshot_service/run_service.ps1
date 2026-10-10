$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$Candidates = @()
$PythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($PythonCmd) {
    $Candidates += $PythonCmd.Source
}
$PyCmd = Get-Command py -ErrorAction SilentlyContinue
if ($PyCmd) {
    $Candidates += $PyCmd.Source
}
$BundledPython = Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path $BundledPython) {
    $Candidates += $BundledPython
}

$Python = $null
foreach ($Candidate in $Candidates) {
    try {
        & $Candidate --version *> $null
        if ($LASTEXITCODE -eq 0) {
            $Python = $Candidate
            break
        }
    } catch {
    }
}

if (-not $Python) {
    throw "Python was not found or could not run. Install Python 3.10+ and add it to PATH."
}

& $Python app.py
