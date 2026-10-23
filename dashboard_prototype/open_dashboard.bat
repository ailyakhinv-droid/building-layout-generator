@echo off
chcp 65001 >nul
echo Открытие автономного дашборда ТЭП в браузере...
start "" "%~dp0index.html"
exit
