@echo off
cd /d "%~dp0"
title Urban / TEP Studio (Port 8070)
echo ========================================================
echo   Starting Urban / TEP Studio (Port 8070)
echo   Please do not close this window during work.
echo ========================================================

if exist ".venv\Scripts\python.exe" (
    set "VENV_PYTHON=.venv\Scripts\python.exe"
) else (
    set "VENV_PYTHON=python"
)

rem Free port 8070 from previous runs
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8070 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

rem Open browser when port 8070 is ready (up to 20 s)
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=8070; for($i=0;$i -lt 40;$i++){try{$c=New-Object Net.Sockets.TcpClient('127.0.0.1',$port);$c.Close();Start-Process ('http://localhost:'+$port);exit}catch{Start-Sleep -Milliseconds 500}}"

"%VENV_PYTHON%" "dashboard_studio\server.py" 8070
pause
