[CmdletBinding()]
param(
    [int]$FrontendPort = 5173,
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "0.0.0.0",
    [string]$BackendHost = "127.0.0.1",
    [switch]$AllowRobotsBypass,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$WebRoot = Join-Path $RepoRoot "web"
$LogDir = Join-Path $RepoRoot "local_docs\logs\runtime"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-TcpPort {
    param([string]$HostName, [int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(1000)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-NodePath {
    $bundled = Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
    if (Test-Path $bundled) {
        return $bundled
    }
    $cmd = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    throw "node.exe was not found. Install Node.js or check the Codex bundled runtime."
}

function Get-PythonPath {
    $venv = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venv) {
        return $venv
    }
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    throw "python.exe was not found. Prepare Python 3.11+ and .venv."
}

function Get-LanUrls {
    param([int]$Port)

    $urls = New-Object System.Collections.Generic.List[string]
    $ipconfig = ipconfig
    foreach ($line in $ipconfig) {
        if ($line -match "IPv4.*?:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)") {
            $ip = $Matches[1]
            if ($ip -notlike "169.254.*" -and $ip -ne "127.0.0.1") {
                $urls.Add("http://$ip`:$Port/")
            }
        }
    }
    return $urls
}

function Start-Backend {
    if (Test-TcpPort -HostName "127.0.0.1" -Port $BackendPort) {
        Write-Host "backend already running: http://127.0.0.1:$BackendPort/"
        return
    }

    $python = Get-PythonPath
    $backendOut = Join-Path $LogDir "backend.out.log"
    $backendErr = Join-Path $LogDir "backend.err.log"
    $oldPythonPath = $env:PYTHONPATH
    $oldBypass = $env:MARKET_ALLOW_ROBOTS_BYPASS

    try {
        $env:PYTHONPATH = Join-Path $RepoRoot "src"
        if ($AllowRobotsBypass) {
            $env:MARKET_ALLOW_ROBOTS_BYPASS = "1"
        }
        Start-Process `
            -WindowStyle Hidden `
            -FilePath $python `
            -ArgumentList @("-m", "investment_assistant.webapi", "--host", $BackendHost, "--port", "$BackendPort") `
            -WorkingDirectory $RepoRoot `
            -RedirectStandardOutput $backendOut `
            -RedirectStandardError $backendErr | Out-Null
    } finally {
        $env:PYTHONPATH = $oldPythonPath
        $env:MARKET_ALLOW_ROBOTS_BYPASS = $oldBypass
    }

    Start-Sleep -Seconds 2
    if (-not (Test-TcpPort -HostName "127.0.0.1" -Port $BackendPort)) {
        throw "backend failed to start. See $backendErr"
    }
    Write-Host "backend started: http://127.0.0.1:$BackendPort/"
}

function Start-Frontend {
    if (Test-TcpPort -HostName "127.0.0.1" -Port $FrontendPort) {
        Write-Host "frontend already running: http://127.0.0.1:$FrontendPort/"
        return
    }

    $node = Get-NodePath
    $vite = Join-Path $WebRoot "node_modules\vite\bin\vite.js"
    if (-not (Test-Path $vite)) {
        throw "Vite was not found. Run npm install in web first: $vite"
    }

    $frontendOut = Join-Path $LogDir "frontend.out.log"
    $frontendErr = Join-Path $LogDir "frontend.err.log"
    Start-Process `
        -WindowStyle Hidden `
        -FilePath $node `
        -ArgumentList @("--preserve-symlinks", ".\node_modules\vite\bin\vite.js", "--host", $FrontendHost, "--port", "$FrontendPort", "--strictPort") `
        -WorkingDirectory $WebRoot `
        -RedirectStandardOutput $frontendOut `
        -RedirectStandardError $frontendErr | Out-Null

    Start-Sleep -Seconds 2
    if (-not (Test-TcpPort -HostName "127.0.0.1" -Port $FrontendPort)) {
        throw "frontend failed to start. See $frontendErr"
    }
    Write-Host "frontend started: http://127.0.0.1:$FrontendPort/"
}

Start-Backend
Start-Frontend

Write-Host ""
Write-Host "Investment Assistant is ready."
Write-Host "Local: http://127.0.0.1:$FrontendPort/"
$lanUrls = Get-LanUrls -Port $FrontendPort
foreach ($url in $lanUrls) {
    Write-Host "LAN:   $url"
}
Write-Host "Logs:  $LogDir"

if (-not $NoOpen) {
    Start-Process "http://127.0.0.1:$FrontendPort/"
}
