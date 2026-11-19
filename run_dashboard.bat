@echo off
cd /d "%~dp0"
title Urban TEP Dashboard
echo Starting Dashboard Server...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" dashboard_prototype\server.py
) else (
    python dashboard_prototype\server.py
)
pause
