@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0code"
python -m backend.demo
pause
