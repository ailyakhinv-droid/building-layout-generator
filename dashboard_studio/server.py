"""Сервер для нового интерфейса Dashboard Studio.
Переиспользует обработчики API из dashboard_prototype без дублирования кода.
// ponytail: повторное использование существующего сервера через наследование — upgrade path: вынести общий роутер при полном отделении.
"""

from __future__ import annotations

import os
import sys
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard_prototype.server import DashboardHandler

STUDIO_DIR = Path(__file__).resolve().parent
PROTOTYPE_DIR = PROJECT_ROOT / "dashboard_prototype"
PORT = 8070


class StudioHandler(DashboardHandler):
    def __init__(self, *args, **kwargs):
        # Передаем STUDIO_DIR как директорию для отдачи статики
        super(DashboardHandler, self).__init__(*args, directory=str(STUDIO_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path in ("/", "/index.html"):
            index_path = STUDIO_DIR / "index.html"
            if not index_path.exists():
                self.send_error(404, "index.html not created yet")
                return
            with open(index_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self._send_cors_headers()
            self.end_headers()
            self._safe_write(content)
            return

        if parsed.path == "/viewer_3d.html":
            v3d = PROTOTYPE_DIR / "viewer_3d.html"
            if v3d.exists():
                with open(v3d, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self._send_cors_headers()
                self.end_headers()
                self._safe_write(content)
                return

        super().do_GET()


def run_studio_server(port: int = PORT, open_browser: bool = True):
    print(f"\n========================================================")
    print(f" URBAN / TEP STUDIO — Сервер запущен на http://localhost:{port}")
    print(f" Режим: Пошаговый пайплайн + Живой CAD холст")
    print(f" Статика: {STUDIO_DIR}")
    print(f"========================================================\n")

    server = ThreadingHTTPServer(("0.0.0.0", port), StudioHandler)

    if open_browser:
        webbrowser.open(f"http://localhost:{port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.")
        server.server_close()


if __name__ == "__main__":
    p = PORT
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        p = int(sys.argv[1])
    run_studio_server(p, open_browser=False)
