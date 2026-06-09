param(
  [switch]$SkipFrontend
)

Write-Host 'Starting development environment...'

Push-Location (Split-Path -Path $MyInvocation.MyCommand.Definition -Parent)\..\

# Backend
Write-Host '-> Backend'
Set-Location .\backend
if(-not (Test-Path .venv)){
  python -m venv .venv
}
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
if(Test-Path requirements.txt){ pip install -r requirements.txt }
Start-Process -FilePath .\.venv\Scripts\python.exe -ArgumentList '-m','uvicorn','app.main:app','--reload','--host','127.0.0.1','--port','8000'

if(-not $SkipFrontend){
  Write-Host '-> Frontend'
  Set-Location ..\web
  if(Test-Path package.json){ npm install; Start-Process -FilePath 'npm' -ArgumentList 'run','dev' }
}

Pop-Location
Write-Host 'Done. Backend -> http://127.0.0.1:8000; UI -> http://127.0.0.1:8000/ui/; Frontend -> http://127.0.0.1:5173 (if started)'
