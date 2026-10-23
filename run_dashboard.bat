@echo off
chcp 65001 >nul
title Дашборд ТЭП и генерации застройки
cd /d "%~dp0"
echo Запуск локального сервера дашборда...
".venv\Scripts\python.exe" dashboard_prototype\server.py
pause
