@echo off
title Urban TEP Dashboard
echo ==============================================================
echo   Starting Interactive TEP Dashboard...
echo ==============================================================
cd /d "%~dp0"
if exist "..\.venv\Scripts\python.exe" (
    "..\.venv\Scripts\python.exe" server.py
) else if exist "..\python\python.exe" (
    "..\python\python.exe" server.py
) else (
    python server.py
)
pause
