$envFile = Join-Path $PSScriptRoot "agent.env"

if (-not (Test-Path $envFile)) {
    Write-Host "[!] Missing agent.env"
    Write-Host "[*] Copy agent.env.example to agent.env and set WEBHOOK_URL"
    exit 1
}

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) {
        return
    }

    $parts = $line.Split("=", 2)
    if ($parts.Count -eq 2) {
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
    }
}

python (Join-Path $PSScriptRoot "local_agent.py")
