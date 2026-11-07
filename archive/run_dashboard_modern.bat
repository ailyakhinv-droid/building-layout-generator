@echo off
chcp 65001 >nul
title Дашборд ТЭП (Modern Design Skills)
cd /d "%~dp0"
echo Сборка и запуск современного дашборда ТЭП на порту 8060...
".venv\Scripts\python.exe" dashboard_modern\build_modern_dashboard.py
".venv\Scripts\python.exe" dashboard_modern\server_modern.py
pause
