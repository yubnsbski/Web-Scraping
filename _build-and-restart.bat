@echo off
cd /d "%~dp0"
echo Building frontend...
cd web
call npm run build
if errorlevel 1 (
  echo BUILD FAILED
  pause
  exit /b 1
)
cd ..
echo Build OK. Restarting server on port 5173...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul
start "" cmd /c "python -m investment_assistant.webapi --host 0.0.0.0 --port 5173"
echo Done! Server restarted.
timeout /t 3 /nobreak
