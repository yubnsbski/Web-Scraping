@echo off
cd /d "%~dp0"
echo ダッシュボード再生成中...
py -3.11 "%~dp0jpx_viz_gen.py"
if errorlevel 1 python "%~dp0jpx_viz_gen.py"
echo.
echo 完了: JPX_NeuroFinance_Dashboard.html
start "" "%~dp0JPX_NeuroFinance_Dashboard.html"
