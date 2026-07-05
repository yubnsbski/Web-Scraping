# Register the sleep/wake operation tasks for the investment-assistant PC.
# Run once. Times are easy to change: edit the $wakeAt / $sleepAt values and re-run.
# NOTE: enabling wake timers (powercfg) needs an elevated prompt — see the message at the end.
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$ps = "powershell.exe"

$wakeAt  = "06:30"   # PC wakes and refreshes market data (before JPX open)
$sleepAt = "23:30"   # PC goes to sleep

# 1) Logon: start the webapi (survives sleep/resume; this covers reboots)
$a1 = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$repo\ops\serve-app.ps1`""
$t1 = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "InvestmentAssistant-Serve" -Action $a1 -Trigger $t1 -Force | Out-Null

# 2) Morning: wake the PC and refresh data, then ensure server is up
$a2 = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$repo\ops\morning-refresh.ps1`""
$t2 = New-ScheduledTaskTrigger -Daily -At $wakeAt
$s2 = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable
Register-ScheduledTask -TaskName "InvestmentAssistant-MorningRefresh" -Action $a2 -Trigger $t2 -Settings $s2 -Force | Out-Null

# 3) Night: put the PC to sleep
$sleepCmd = "-NoProfile -Command `"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState('Suspend',`$false,`$false)`""
$a3 = New-ScheduledTaskAction -Execute $ps -Argument $sleepCmd
$t3 = New-ScheduledTaskTrigger -Daily -At $sleepAt
Register-ScheduledTask -TaskName "InvestmentAssistant-NightSleep" -Action $a3 -Trigger $t3 -Force | Out-Null

Write-Host "Registered: Serve(at logon), MorningRefresh($wakeAt, wakes PC), NightSleep($sleepAt)"
Write-Host ""
Write-Host "REQUIRED ONCE (elevated PowerShell) — allow wake timers on AC power:"
Write-Host '  powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1; powercfg /SETACTIVE SCHEME_CURRENT'
