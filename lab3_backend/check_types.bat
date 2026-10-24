@echo off
chcp 65001 >nul
cd /d "%~dp0code"
python -m pip install -r requirements-dev.txt
python -m mypy backend shared
pause
