@echo off
chcp 65001 >nul
title Генератор застройки · Интерактивный дашборд ТЭП
echo.
echo ==============================================================
echo   🏗️ Запуск интерактивного веб-дашборда застройки по ТЭП...
echo ==============================================================
echo.

cd /d "%~dp0"

if exist "..\.venv\Scripts\python.exe" (
    "..\.venv\Scripts\python.exe" server.py
) else (
    python server.py
)

pause
