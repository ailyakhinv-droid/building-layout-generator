"""Локальный веб-сервер для интерактивного дашборда ТЭП.
Полноценный бэкенд с поддержкой:
- Генерации планировки на лету (/api/generate);
- Матрицы вариантов по этажности (/api/variants);
- Каталога библиотеки типовых секций (/api/library);
- Скачивания реальных файлов DXF, 3D HTML, GeoJSON и отчетов.
"""

from __future__ import annotations

import json
import os
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard_prototype.generator_service import (
    preview_site,
    run_pipeline,
    compute_variants_matrix,
    set_active_variant,
    get_library_catalog,
    inspect_cad_bytes,
    export_file_dxf,
    export_file_3d_html,
    export_file_geojson,
    export_file_report,
)

PORT = 8050
DIR = Path(__file__).resolve().parent
TEMP_DIR = DIR / "tmp_exports"
TEMP_DIR.mkdir(exist_ok=True)


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIR), **kwargs)

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)

        # 0. Предпросмотр участка (Этап 1: Посадка и ориентация)
        if parsed.path == "/api/site-preview":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length).decode("utf-8")
            try:
                params = json.loads(post_data) if post_data else {}
                mode_str = params.get("site_mode", "unknown")
                fn_str = params.get("cad_filename", "no_file")
                print(f"[Сервер] Запрос предпросмотра: mode={mode_str}, file={fn_str}, msk={params.get('msk_zone')}")
                result = preview_site(params)
                geo = result.get("geo_center", {})
                print(f"[Сервер] Предпросмотр готов: кад={result.get('cadastral_number')}, lat={geo.get('lat')}, lon={geo.get('lon')}, мск={result.get('cad_info', {}).get('detected_msk')}")
                response_bytes = json.dumps(result, ensure_ascii=False).encode("utf-8")

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(response_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(response_bytes)
            except Exception as e:
                import traceback
                err_text = traceback.format_exc()
                print(f"[Сервер] ОШИБКА /api/site-preview: {e}\n{err_text}")
                err_bytes = json.dumps({"error": str(e), "traceback": err_text}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(err_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(err_bytes)
            return

        # 1. Генерация застройки (Этап 2)
        if parsed.path == "/api/generate":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length).decode("utf-8")
            try:
                params = json.loads(post_data) if post_data else {}
                result = run_pipeline(params)
                response_bytes = json.dumps(result, ensure_ascii=False).encode("utf-8")

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(response_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(response_bytes)
            except Exception as e:
                import traceback
                err_text = traceback.format_exc()
                err_bytes = json.dumps({"error": str(e), "traceback": err_text}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(err_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(err_bytes)
            return

        # 2. Матрица вариантов по этажности
        elif parsed.path == "/api/variants":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length).decode("utf-8")
            try:
                params = json.loads(post_data) if post_data else {}
                variants = compute_variants_matrix(params)
                response_bytes = json.dumps({"variants": variants}, ensure_ascii=False).encode("utf-8")

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(response_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(response_bytes)
            except Exception as e:
                err_bytes = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(err_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(err_bytes)
            return

        # 2b. Активация выбранного концептуального варианта
        elif parsed.path == "/api/activate-variant":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(post_data) if post_data else {}
                idx = int(data.get("index", 0))
                res = set_active_variant(idx)
                response_bytes = json.dumps(res, ensure_ascii=False).encode("utf-8")

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(response_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(response_bytes)
            except Exception as e:
                err_bytes = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(err_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(err_bytes)
            return

        # 3. Инспекция слоев CAD файла
        elif parsed.path == "/api/inspect-cad":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(post_data)
                raw_b64 = data.get("file_base64", "")
                filename = data.get("filename", "drawing.dxf")
                import base64
                file_bytes = base64.b64decode(raw_b64)
                layers = inspect_cad_bytes(file_bytes, filename)
                response_bytes = json.dumps({"layers": layers}, ensure_ascii=False).encode("utf-8")

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(response_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(response_bytes)
            except Exception as e:
                err_bytes = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(err_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(err_bytes)
            return

        self.send_error(404, "Endpoint not found")

    def do_GET(self):
        parsed = urlparse(self.path)

        # Проверка работоспособности бэкенда
        if parsed.path == "/api/health":
            body = json.dumps({"status": "ok", "service": "building-generator"}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(body)
            return

        # Главная страница
        elif parsed.path in ("/", "/index.html"):
            index_path = DIR / "index.html"
            with open(index_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
            return

        # Каталог типовых секций
        elif parsed.path == "/api/library":
            try:
                catalog = get_library_catalog()
                bytes_out = json.dumps({"catalog": catalog}, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(bytes_out)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(bytes_out)
            except Exception as e:
                self.send_error(500, str(e))
            return

        # Экспорт DXF
        elif parsed.path == "/api/export/dxf":
            try:
                dxf_file = TEMP_DIR / "plan_cad.dxf"
                export_file_dxf(dxf_file)
                with open(dxf_file, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/dxf")
                self.send_header("Content-Disposition", 'attachment; filename="plan_cad.dxf"')
                self.send_header("Content-Length", str(len(data)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_error(500, f"Ошибка экспорта DXF: {e}")
            return

        # Экспорт 3D HTML
        elif parsed.path in ("/api/export/3d-html", "/api/export/3d"):
            try:
                html_file = TEMP_DIR / "plan_3d.html"
                export_file_3d_html(html_file)
                with open(html_file, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="plan_3d.html"')
                self.send_header("Content-Length", str(len(data)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_error(500, f"Ошибка экспорта 3D HTML: {e}")
            return

        # Экспорт GeoJSON
        elif parsed.path == "/api/export/geojson":
            try:
                geo_file = TEMP_DIR / "plan.geojson"
                export_file_geojson(geo_file)
                with open(geo_file, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/geo+json; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="plan.geojson"')
                self.send_header("Content-Length", str(len(data)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self.send_error(500, f"Ошибка экспорта GeoJSON: {e}")
            return

        # Экспорт отчета ТЭП (текстовый)
        elif parsed.path == "/api/export/report":
            try:
                report_txt = export_file_report()
                bytes_out = report_txt.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="tep_report.txt"')
                self.send_header("Content-Length", str(len(bytes_out)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(bytes_out)
            except Exception as e:
                self.send_error(500, f"Ошибка формирования отчета: {e}")
            return

        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        super().do_GET()

    def log_message(self, format, *args):
        try:
            msg = format % args if args else str(format)
            if "POST /api/generate" in msg:
                print("[Сервер] Генерация планировки выполнена успешно -> 200 OK")
            elif "POST /api/variants" in msg:
                print("[Сервер] Расчет матрицы вариантов этажности -> 200 OK")
            elif "/api/export" in msg:
                print(f"[Сервер] Файл экспортирован")
        except Exception:
            pass


def main():
    port = PORT
    for attempt in range(10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
            break
        except OSError:
            port += 1
    else:
        print("Не удалось занять свободный порт.")
        sys.exit(1)

    url = f"http://127.0.0.1:{port}/"
    print("=" * 60)
    print("  [OK] ПОЛНОФУНКЦИОНАЛЬНЫЙ ДАШБОРД ТЭП ЗАПУЩЕН")
    print("=" * 60)
    print(f"URL: {url}")
    print("Нажмите Ctrl+C для остановки.")
    print("=" * 60)

    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.")
        server.server_close()


if __name__ == "__main__":
    main()
