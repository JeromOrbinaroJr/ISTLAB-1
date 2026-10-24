@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0code"
python -m unittest discover -s backend/tests -t . -v
pause
