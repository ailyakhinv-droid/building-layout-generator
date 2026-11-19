@echo off
title Urban TEP Generator
cd /d "%~dp0"
echo Starting TEP Generator...
".venv\Scripts\streamlit.exe" run app\streamlit_app.py
pause
