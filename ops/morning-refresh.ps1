# Morning wake task: refresh market data, then make sure the webapi is up.
# Scheduled with "wake the computer to run this task" (see register-tasks.ps1).
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $repo ".venv\Scripts\investment-assistant.exe"
$logDir = Join-Path $repo "ops\logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "morning-refresh.log"

Add-Content $log "$(Get-Date -Format s) refresh start"
& $exe market-daily-refresh *>> $log
Add-Content $log "$(Get-Date -Format s) refresh done (exit=$LASTEXITCODE)"

& (Join-Path $PSScriptRoot "serve-app.ps1")
