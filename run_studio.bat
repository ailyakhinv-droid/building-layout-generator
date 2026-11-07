@echo off
chcp 65001 >nul
echo ========================================================
echo  Запуск URBAN / TEP STUDIO (Порт 8070)
echo  Новый интерфейс: Пошаговый пайплайн + CAD Холст
echo ========================================================

set SCRIPT_DIR=%~dp0
set VENV_PYTHON=%SCRIPT_DIR%.venv\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    set VENV_PYTHON=python
)

start "" http://localhost:8070
"%VENV_PYTHON%" "%SCRIPT_DIR%dashboard_studio\server.py" 8070
pause
