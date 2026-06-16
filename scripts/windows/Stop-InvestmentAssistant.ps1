[CmdletBinding()]
param(
    [int[]]$Ports = @(5173, 8000)
)

$ErrorActionPreference = "Continue"

function Get-ListeningPids {
    param([int]$Port)

    $pids = New-Object System.Collections.Generic.HashSet[int]
    $lines = netstat -ano -p tcp | Select-String "LISTENING"
    foreach ($line in $lines) {
        $text = [string]$line
        if ($text -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            [void]$pids.Add([int]$Matches[1])
        }
    }
    return $pids
}

foreach ($port in $Ports) {
    $pids = Get-ListeningPids -Port $port
    foreach ($processId in $pids) {
        try {
            Stop-Process -Id $processId -Force
            Write-Host "stopped pid=$processId port=$port"
        } catch {
            Write-Host "failed to stop pid=$processId port=${port}: $($_.Exception.Message)"
        }
    }
}
