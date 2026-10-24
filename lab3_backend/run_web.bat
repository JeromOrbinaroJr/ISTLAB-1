@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0code"
echo Откроется браузер: http://127.0.0.1:8765  (остановить - Ctrl+C)
python -m backend.web_demo
pause
