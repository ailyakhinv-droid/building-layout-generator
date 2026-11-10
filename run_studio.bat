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

rem Browser opens automatically when port 8070 answers (up to 20 s)
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -Command "for($i=0;$i -lt 40;$i++){try{$c=New-Object Net.Sockets.TcpClient('127.0.0.1',8070);$c.Close();Start-Process 'http://localhost:8070';exit}catch{Start-Sleep -Milliseconds 500}}"
"%VENV_PYTHON%" "%SCRIPT_DIR%dashboard_studio\server.py" 8070
pause
