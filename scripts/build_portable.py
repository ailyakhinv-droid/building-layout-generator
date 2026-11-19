# scripts/build_portable.py
"""
Build portable standalone ZIP for Urban / TEP Studio.
// ponytail: сборка переиспользует уже протестированное окружение tmp/test_portable
(или собирает из локального Python + .venv) и упаковывает через stdlib zipfile —
upgrade path: при необходимости сборки на CI добавить скачивание embeddable zip.
"""

from __future__ import annotations

import os
import sys
import shutil
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
RELEASE_NAME = "Urban_TEP_Studio"
STAGE_DIR = DIST_DIR / RELEASE_NAME
ZIP_PATH = DIST_DIR / f"{RELEASE_NAME}_Portable.zip"

PROJECT_FOLDERS = [
    "src",
    "dashboard_studio",
    "dashboard_prototype",
    "config",
    "data",
]

EXCLUDE_DIRS = {"__pycache__", ".git", ".venv", "tests", "archive", "scratch"}
EXCLUDE_EXTS = {".pyc", ".log", ".tmp"}

def copy_tree_filtered(src: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_dir():
            if item.name in EXCLUDE_DIRS:
                continue
            copy_tree_filtered(item, dst / item.name)
        elif item.is_file():
            if item.suffix in EXCLUDE_EXTS:
                continue
            shutil.copy2(item, dst / item.name)

def main():
    print(f"=== Сборка {RELEASE_NAME} ===")

    if STAGE_DIR.exists():
        print(f"Очистка предыдущей папки сборки: {STAGE_DIR}")
        shutil.rmtree(STAGE_DIR, ignore_errors=True)
    STAGE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Python runtime
    target_python = STAGE_DIR / "python"
    base_py = Path(sys.base_prefix)
    venv_site_pkgs = Path(sys.prefix) / "Lib" / "site-packages"

    print(f"Сборка автономного Python runtime из {base_py}...")
    target_python.mkdir(parents=True, exist_ok=True)
    for f in base_py.glob("*.exe"):
        shutil.copy2(f, target_python / f.name)
    for f in base_py.glob("*.dll"):
        shutil.copy2(f, target_python / f.name)

    base_dlls = base_py / "DLLs"
    if base_dlls.exists():
        os.system(f'robocopy "{base_dlls}" "{target_python / "DLLs"}" /E /NFL /NDL /NJH /NJS /nc /ns /np')

    base_lib = base_py / "Lib"
    os.system(f'robocopy "{base_lib}" "{target_python / "Lib"}" /E /XD site-packages __pycache__ /NFL /NDL /NJH /NJS /nc /ns /np')

    print(f"Копирование установленных библиотек из {venv_site_pkgs}...")
    target_site_pkgs = target_python / "Lib" / "site-packages"
    os.system(f'robocopy "{venv_site_pkgs}" "{target_site_pkgs}" /E /XD __pycache__ .agents tests test /NFL /NDL /NJH /NJS /nc /ns /np')

    # 2. Project modules
    for folder_name in PROJECT_FOLDERS:
        src_folder = PROJECT_ROOT / folder_name
        if src_folder.exists():
            print(f"Копирование модуля: {folder_name}...")
            copy_tree_filtered(src_folder, STAGE_DIR / folder_name)

    # 3. Create clean output directory
    (STAGE_DIR / "output").mkdir(exist_ok=True)

    # 4. Create launcher .bat
    bat_content = """@echo off
chcp 65001 >nul
title Генератор Застройки - Urban / TEP Studio

echo ========================================================
echo   Запуск Генератора Застройки (Urban / TEP Studio)
echo   Порт: 8070
echo   Пожалуйста, не закрывайте это окно во время работы.
echo ========================================================

set SCRIPT_DIR=%~dp0
set PYTHON_EXE=%SCRIPT_DIR%python\\python.exe

if not exist "%PYTHON_EXE%" (
    echo [ОШИБКА] Не найден встроенный интерпретатор python\\python.exe!
    pause
    exit /b 1
)

rem Автоматическое открытие браузера при готовности сервера (до 20 сек)
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -Command "for($i=0;$i -lt 40;$i++){try{$c=New-Object Net.Sockets.TcpClient('127.0.0.1',8070);$c.Close();Start-Process 'http://localhost:8070';exit}catch{Start-Sleep -Milliseconds 500}}"

"%PYTHON_EXE%" "%SCRIPT_DIR%dashboard_studio\\server.py" 8070
pause
"""
    (STAGE_DIR / "Запустить_Генератор.bat").write_text(bat_content, encoding="utf-8")
    (STAGE_DIR / "START.bat").write_text(bat_content, encoding="utf-8")

    # 5. Create README / Instructions
    docs_source_md = PROJECT_ROOT / "docs" / "ИНСТРУКЦИЯ_ДЛЯ_ТЕСТИРОВЩИКОВ.md"
    if docs_source_md.exists():
        shutil.copy2(docs_source_md, STAGE_DIR / "РУКОВОДСТВО_АРХИТЕКТОРА.md")
        shutil.copy2(docs_source_md, STAGE_DIR / "MANUAL.md")
    docs_source_pdf = PROJECT_ROOT / "docs" / "ИНСТРУКЦИЯ_ДЛЯ_ТЕСТИРОВЩИКОВ.pdf"
    if docs_source_pdf.exists():
        shutil.copy2(docs_source_pdf, STAGE_DIR / "РУКОВОДСТВО_АРХИТЕКТОРА.pdf")
        shutil.copy2(docs_source_pdf, STAGE_DIR / "MANUAL.pdf")

    readme_content = """============================================================
URBAN / TEP STUDIO — PORTABLE EDITION
============================================================

Программа полностью автономна и не требует установки Python, 
библиотек или прав администратора на компьютере.

ИНСТРУКЦИЯ ПО ЗАПУСКУ:
1. Распакуйте весь архив в любую папку (например, C:\\app или на Рабочий стол).
   ВНИМАНИЕ: не запускайте программу прямо из архива, обязательно распакуйте!
2. Запустите файл "Запустить_Генератор.bat" или "START.bat" (двойным кликом).
3. Через несколько секунд в вашем браузере автоматически откроется страница генератора:
   http://localhost:8070
4. Во время работы не закрывайте черное окно командной строки.
5. Для завершения работы закройте вкладку в браузере и черное окно командной строки.

Иллюстрированное руководство архитектора: "РУКОВОДСТВО_АРХИТЕКТОРА.pdf" (или "MANUAL.pdf").
Все сгенерированные файлы (DXF, отчеты, изображения) сохраняются в папку "output".
"""
    (STAGE_DIR / "ИНСТРУКЦИЯ.txt").write_text(readme_content, encoding="utf-8")
    (STAGE_DIR / "README.txt").write_text(readme_content, encoding="utf-8")

    # 6. Compress to ZIP
    print(f"Создание ZIP-архива: {ZIP_PATH} ...")
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    file_count = 0
    with zipfile.ZipFile(ZIP_PATH, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(STAGE_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for file in files:
                if any(file.endswith(ext) for ext in EXCLUDE_EXTS):
                    continue
                full_path = Path(root) / file
                arcname = full_path.relative_to(DIST_DIR)
                zf.write(full_path, arcname=arcname)
                file_count += 1
                if file_count % 1000 == 0:
                    print(f"  Упаковано файлов: {file_count}...")

    zip_size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    print(f"\nСборка завершена успешно!")
    print(f"Упаковано файлов: {file_count}")
    print(f"Размер архива: {zip_size_mb:.1f} МБ")
    print(f"Архив готов для отправки: {ZIP_PATH}")

if __name__ == "__main__":
    main()
