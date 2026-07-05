@echo off
cd /d "%~dp0web"
echo Building frontend...
npm run build
echo Done! (exitcode=%errorlevel%)
pause
