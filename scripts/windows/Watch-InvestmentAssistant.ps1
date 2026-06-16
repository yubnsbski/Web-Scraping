[CmdletBinding()]
param(
    [int]$FrontendPort = 5173,
    [int]$BackendPort = 8000,
    [int]$IntervalSeconds = 30,
    [switch]$AllowRobotsBypass
)

$ErrorActionPreference = "Continue"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$LogDir = Join-Path $RepoRoot "local_docs\logs\runtime"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$WatchLog = Join-Path $LogDir "watchdog.log"
$StartScript = Join-Path $PSScriptRoot "Start-InvestmentAssistant.ps1"

function Write-WatchLog {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Encoding utf8 -Path $WatchLog -Value $line
    Write-Host $line
}

Write-WatchLog "watchdog started frontend=$FrontendPort backend=$BackendPort interval=$IntervalSeconds"

while ($true) {
    try {
        $args = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $StartScript,
            "-FrontendPort", "$FrontendPort",
            "-BackendPort", "$BackendPort",
            "-NoOpen"
        )
        if ($AllowRobotsBypass) {
            $args += "-AllowRobotsBypass"
        }
        & powershell.exe @args | ForEach-Object { Write-WatchLog $_ }
    } catch {
        Write-WatchLog ("restart check failed: " + $_.Exception.Message)
    }
    Start-Sleep -Seconds $IntervalSeconds
}
