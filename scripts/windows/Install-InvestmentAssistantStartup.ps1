[CmdletBinding()]
param(
    [string]$TaskName = "InvestmentAssistantLocalKeepAlive",
    [int]$FrontendPort = 5173,
    [int]$BackendPort = 8000,
    [int]$IntervalSeconds = 30,
    [switch]$AllowRobotsBypass,
    [switch]$StartNow
)

$ErrorActionPreference = "Stop"

$WatchScript = Join-Path $PSScriptRoot "Watch-InvestmentAssistant.ps1"
if (-not (Test-Path $WatchScript)) {
    throw "watch script not found: $WatchScript"
}

$argList = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$WatchScript`"",
    "-FrontendPort", "$FrontendPort",
    "-BackendPort", "$BackendPort",
    "-IntervalSeconds", "$IntervalSeconds"
)
if ($AllowRobotsBypass) {
    $argList += "-AllowRobotsBypass"
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ($argList -join " ")
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Keeps Investment Assistant local frontend/backend available on 5173/8000." `
    -Force | Out-Null

Write-Host "registered scheduled task: $TaskName"

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "started scheduled task: $TaskName"
}
