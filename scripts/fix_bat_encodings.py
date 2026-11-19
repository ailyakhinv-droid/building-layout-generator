import os

run_studio_content = (
    b"@echo off\r\n"
    b"cd /d \"%~dp0..\"\r\n"
    b"title Urban / TEP Studio (Port 8070)\r\n"
    b"echo ========================================================\r\n"
    b"echo   Starting Urban / TEP Studio (Port 8070)\r\n"
    b"echo ========================================================\r\n\r\n"
    b"set \"SCRIPT_DIR=%~dp0..\\\"\r\n"
    b"set \"VENV_PYTHON=%SCRIPT_DIR%.venv\\Scripts\\python.exe\"\r\n\r\n"
    b"if not exist \"%VENV_PYTHON%\" (\r\n"
    b"    if exist \"%SCRIPT_DIR%python\\python.exe\" (\r\n"
    b"        set \"VENV_PYTHON=%SCRIPT_DIR%python\\python.exe\"\r\n"
    b"    ) else (\r\n"
    b"        set \"VENV_PYTHON=python\"\r\n"
    b"    )\r\n"
    b")\r\n\r\n"
    b"start \"\" http://localhost:8070\r\n"
    b"\"%VENV_PYTHON%\" \"%~dp0server.py\" 8070\r\n"
    b"pause\r\n"
)

run_dashboard_content = (
    b"@echo off\r\n"
    b"title Urban TEP Dashboard\r\n"
    b"echo ==============================================================\r\n"
    b"echo   Starting Interactive TEP Dashboard...\r\n"
    b"echo ==============================================================\r\n"
    b"cd /d \"%~dp0\"\r\n"
    b"if exist \"..\\.venv\\Scripts\\python.exe\" (\r\n"
    b"    \"..\\.venv\\Scripts\\python.exe\" server.py\r\n"
    b") else if exist \"..\\python\\python.exe\" (\r\n"
    b"    \"..\\python\\python.exe\" server.py\r\n"
    b") else (\r\n"
    b"    python server.py\r\n"
    b")\r\n"
    b"pause\r\n"
)

open_dashboard_content = (
    b"@echo off\r\n"
    b"echo Opening TEP Dashboard in browser...\r\n"
    b"start \"\" \"%~dp0index.html\"\r\n"
    b"exit\r\n"
)

archive_run_app = (
    b"@echo off\r\n"
    b"title Urban TEP Generator\r\n"
    b"cd /d \"%~dp0\"\r\n"
    b"echo Starting TEP Generator...\r\n"
    b"\".venv\\Scripts\\streamlit.exe\" run app\\streamlit_app.py\r\n"
    b"pause\r\n"
)

archive_run_modern = (
    b"@echo off\r\n"
    b"title Urban TEP Modern Dashboard\r\n"
    b"cd /d \"%~dp0\"\r\n"
    b"echo Building and starting dashboard on port 8060...\r\n"
    b"\".venv\\Scripts\\python.exe\" dashboard_modern\\build_modern_dashboard.py\r\n"
    b"\".venv\\Scripts\\python.exe\" dashboard_modern\\server_modern.py\r\n"
    b"pause\r\n"
)

with open('dist/Urban_TEP_Studio/dashboard_studio/run_studio.bat', 'wb') as f:
    f.write(run_studio_content)
with open('dist/Генератор_Застройки_Portable/dashboard_studio/run_studio.bat', 'wb') as f:
    f.write(run_studio_content)

with open('dist/Urban_TEP_Studio/dashboard_prototype/run_dashboard.bat', 'wb') as f:
    f.write(run_dashboard_content)
with open('dist/Urban_TEP_Studio/dashboard_prototype/open_dashboard.bat', 'wb') as f:
    f.write(open_dashboard_content)

with open('dist/Генератор_Застройки_Portable/dashboard_prototype/run_dashboard.bat', 'wb') as f:
    f.write(run_dashboard_content)
with open('dist/Генератор_Застройки_Portable/dashboard_prototype/open_dashboard.bat', 'wb') as f:
    f.write(open_dashboard_content)

with open('dashboard_prototype/run_dashboard.bat', 'wb') as f:
    f.write(run_dashboard_content)
with open('dashboard_prototype/open_dashboard.bat', 'wb') as f:
    f.write(open_dashboard_content)

with open('archive/run_app.bat', 'wb') as f:
    f.write(archive_run_app)
with open('archive/run_dashboard_modern.bat', 'wb') as f:
    f.write(archive_run_modern)

print('ALL BAT FILES WRITTEN SUCCESSFULLY')
