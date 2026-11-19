@echo off
title Urban TEP Modern Dashboard
cd /d "%~dp0"
echo Building and starting dashboard on port 8060...
".venv\Scripts\python.exe" dashboard_modern\build_modern_dashboard.py
".venv\Scripts\python.exe" dashboard_modern\server_modern.py
pause
