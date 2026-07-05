# Start the investment-assistant webapi if it is not already running.
# Registered as a logon task; safe to run repeatedly (no-op when the port is in use).
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $repo ".venv\Scripts\investment-assistant.exe"
$logDir = Join-Path $repo "ops\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null

$listening = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Add-Content (Join-Path $logDir "serve.log") "$(Get-Date -Format s) already running"
    exit 0
}

Start-Process -FilePath $exe -ArgumentList "serve" -WorkingDirectory $repo -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir "serve.out.log") `
    -RedirectStandardError (Join-Path $logDir "serve.err.log")
Add-Content (Join-Path $logDir "serve.log") "$(Get-Date -Format s) started"
