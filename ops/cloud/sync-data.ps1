# PC のデータ (RAGコーパス・市場データ・APIキー) をクラウドVMへ同期する。
# PC 側で実行:
#   powershell -ExecutionPolicy Bypass -File ops\cloud\sync-data.ps1
# 前提: PC と VM が同じ tailnet に居ること (転送は WireGuard で暗号化される)。
param(
    [string]$VmHost = "invest-vm",
    [string]$VmUser = "ubuntu"
)
$ErrorActionPreference = "Stop"

$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dest = "${VmUser}@${VmHost}"

foreach ($dir in @("data", "local_docs", "local_data")) {
    $src = Join-Path $repo $dir
    if (Test-Path $src) {
        Write-Host "sync $dir ..."
        scp -r -q $src "${dest}:~/Web-Scraping/"
    }
}

$envFile = Join-Path $repo ".env.local"
if (Test-Path $envFile) {
    Write-Host "sync .env.local (APIキー) ..."
    scp -q $envFile "${dest}:~/Web-Scraping/.env.local"
}

Write-Host "restart service ..."
ssh $dest "sudo systemctl restart investment-assistant"
Start-Sleep -Seconds 3
ssh $dest "curl -s http://127.0.0.1:8000/api/health"
Write-Host ""
Write-Host "done."
