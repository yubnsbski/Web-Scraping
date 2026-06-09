Write-Host 'Build frontend and serve with backend'

$root = Split-Path -Path $MyInvocation.MyCommand.Definition -Parent | Split-Path -Parent
Push-Location $root

if(-not (Test-Path .\web\package.json)){
  Write-Host 'No web/package.json found. Aborting.'; exit 1
}

Write-Host 'Building frontend (npm run build:no-check)'
Set-Location .\web
npm install
npm run build:no-check

Write-Host 'Copy dist to backend/web/dist'
$dist = Join-Path -Path $root -ChildPath 'web\dist'
$target = Join-Path -Path $root -ChildPath 'web\dist'
# Ensure backend will see web/dist at repository root location
Set-Location $root

Write-Host 'Starting backend to serve the built frontend'
Set-Location .\backend
if(-not (Test-Path .venv)){
  python -m venv .venv
}
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
if(Test-Path requirements.txt){ pip install -r requirements.txt }
Start-Process -FilePath .\.venv\Scripts\python.exe -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory (Get-Location)

Pop-Location
Write-Host 'Serving at http://127.0.0.1:8000/'
