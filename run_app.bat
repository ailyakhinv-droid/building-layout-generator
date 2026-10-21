@echo off
chcp 65001 >nul
title Генератор застройки по ТЭП
cd /d "%~dp0"
echo Запуск Генератора застройки...
".venv\Scripts\streamlit.exe" run app\streamlit_app.py
pause
