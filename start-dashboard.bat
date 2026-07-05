@echo off
cd /d "%~dp0"
echo Freeing port 5173...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
:: Security: bind to 127.0.0.1 only (loopback). Change to 0.0.0.0 only if LAN access is needed.
python -m investment_assistant.webapi --host 127.0.0.1 --port 5173
