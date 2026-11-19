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

# Патч устранения наложений машиномест (zero-touch policy: не изменяет src/core/*.py)
try:
    import src.core.parking_layout as pl_mod
    from shapely.ops import unary_union

    _orig_generate_parking = pl_mod.generate_parking_layout

    def _safe_generate_parking_layout(*args, **kwargs):
        res = _orig_generate_parking(*args, **kwargs)
        if res and getattr(res, "slots", None):
            clean_slots = []
            for s in res.slots:
                # Исключаем машиноместа, которые пересекаются с уже размещенными более чем на 0.05 м²
                if not any(s.polygon.intersection(cs.polygon).area > 0.05 for cs in clean_slots):
                    clean_slots.append(s)
            if len(clean_slots) < len(res.slots):
                res.slots = clean_slots
                res.bays_polygon = unary_union([s.polygon.buffer(0.05) for s in clean_slots]) if clean_slots else None
                res.total_area_sqm = sum(s.polygon.area for s in clean_slots)
        return res

    pl_mod.generate_parking_layout = _safe_generate_parking_layout
except Exception as ex:
    print(f"Предупреждение: не удалось инициализировать фильтр парковок: {ex}")

# Патч оптического распознавания сканированных документов ГПЗУ (OCR fallback)
# Zero-touch policy: не изменяет файлы src/core/*.py
try:
    import src.core.gpzu_parser as gp_mod
    import dashboard_prototype.generator_service as gs_mod
    from dashboard_studio.ocr_gpzu import is_scanned_pdf, process_scanned_gpzu

    _orig_parse_gpzu_file = gp_mod.parse_gpzu_file

    def _smart_parse_gpzu_file(file_bytes, filename, msk_zone_override=None):
        res = _orig_parse_gpzu_file(file_bytes, filename, msk_zone_override=msk_zone_override)
        if (not res.get("success") or res.get("points_count", 0) < 3) and filename.lower().endswith(".pdf"):
            if is_scanned_pdf(file_bytes):
                print(f"[OCR] Обнаружен растровый скан ГПЗУ '{filename}', запускается оптическое распознавание...")
                ocr_res = process_scanned_gpzu(file_bytes, filename, msk_zone=msk_zone_override)
                if ocr_res.get("success"):
                    print(f"[OCR] Успешно распознано {ocr_res.get('points_count')} точек, КН {ocr_res.get('cadastral_number')}")
                    return ocr_res
                else:
                    print(f"[OCR] Ошибка распознавания: {ocr_res.get('error')}")
        return res

    gp_mod.parse_gpzu_file = _smart_parse_gpzu_file
    gs_mod.parse_gpzu_file = _smart_parse_gpzu_file
except Exception as ex:
    print(f"Предупреждение: не удалось инициализировать OCR fallback: {ex}")

# Калибровка МСК-66 Зона 1 (Свердловская обл.) по официальным параметрам Росреестра/ГИС
try:
    import src.geo.msk_converter as mc
    for k in ("МСК-66 Зона 1 (Свердловская обл.)", "МСК-66 зона 1", "МСК-66"):
        if k in mc.MSK_PRESETS:
            mc.MSK_PRESETS[k]["false_northing"] = -5911057.63
            mc.MSK_PRESETS[k]["x0"] = -5911057.63
except Exception as ex:
    print(f"Предупреждение: не удалось откалибровать МСК-66: {ex}")

# Патч строгого соблюдения предельной высоты зданий (zero-touch policy: не меняет src/core/*.py)
try:
    import src.core.placement as pl_core
    _orig_clamp_floors = pl_core.PlacementEngine._clamp_floors

    def _safe_clamp_floors(self, sec, req_floors: int) -> int:
        fl = _orig_clamp_floors(self, sec, req_floors)
        max_h = getattr(self, "_max_building_height_m", None)
        if max_h and max_h > 0:
            fh = getattr(sec, "floor_height", 3.0) or 3.0
            gfh = getattr(sec, "ground_floor_height", None) or fh
            has_comm = getattr(sec, "has_commercial_ground", False)
            if has_comm and max_h >= gfh:
                max_sec_f = 1 + int((max_h - gfh) // fh)
            else:
                max_sec_f = int(max_h // fh)
            if max_sec_f >= 1:
                fl = min(fl, max_sec_f)
        return fl

    pl_core.PlacementEngine._clamp_floors = _safe_clamp_floors
except Exception as ex:
    print(f"Предупреждение: не удалось откалибровать _clamp_floors: {ex}")

# Патч нормализации типологии SECTIONAL -> LINEAR (zero-touch policy)
try:
    import dashboard_prototype.generator_service as gs_mod
    _orig_gs_run_pipeline = gs_mod.run_pipeline

    def _safe_run_pipeline(params: dict):
        if params and params.get("typology") == "SECTIONAL":
            params["typology"] = "LINEAR"
        return _orig_gs_run_pipeline(params)

    gs_mod.run_pipeline = _safe_run_pipeline
except Exception as ex:
    print(f"Предупреждение: не удалось инициализировать патч типологии: {ex}")

import dashboard_prototype.server as dp_server
dp_server.run_pipeline = gs_mod.run_pipeline

from dashboard_prototype.server import DashboardHandler

STUDIO_DIR = Path(__file__).resolve().parent
PROTOTYPE_DIR = PROJECT_ROOT / "dashboard_prototype"
PORT = 8070


class StudioHandler(DashboardHandler):
    def __init__(self, *args, **kwargs):
        # Передаем STUDIO_DIR как директорию для отдачи статики
        super(DashboardHandler, self).__init__(*args, directory=str(STUDIO_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/upload-gpzu":
            self._handle_upload_gpzu()
            return
        if parsed.path == "/api/pkk-lookup":
            self._handle_pkk_lookup()
            return
        if parsed.path in ("/api/generate", "/api/variants", "/api/site-preview"):
            self._handle_diagnostic_api_post(parsed.path)
            return
        super().do_POST()

    def _handle_pkk_lookup(self):
        import json
        from dashboard_prototype.generator_service import lookup_pkk_parcel
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            data = json.loads(post_data) if post_data else {}
            cad_num = (data.get("cadastral_number") or "").strip()
            print(f"[Studio PKK] Запрос кадастрового номера: '{cad_num}'", flush=True)
            res = lookup_pkk_parcel(cad_num)
            print(f"[Studio PKK] Результат: success={res.get('success')}, source={res.get('source')}, address='{res.get('address')}'", flush=True)
            response_bytes = json.dumps(res, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(response_bytes)))
            self._send_cors_headers()
            self.end_headers()
            self._safe_write(response_bytes)
        except Exception as e:
            err_bytes = json.dumps({"success": False, "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_bytes)))
            self._send_cors_headers()
            self.end_headers()
            self._safe_write(err_bytes)

    def _handle_diagnostic_api_post(self, api_path: str):
        import json
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            params = json.loads(post_data) if post_data else {}
        except Exception as ex:
            params = {}

        # ── Диагностика входящего сетевого пакета (только для ключевых операций генерации) ──
        is_preview = (api_path == "/api/site-preview")
        if not is_preview:
            entry_pts = params.get("entry_points") or []
            custom_rds = params.get("custom_roads") or []
            print("\n" + "=" * 65, flush=True)
            print(f"[DIAG SERVER] Входящий запрос POST {api_path}", flush=True)
            print(f"  stage: {params.get('stage')}, cad_query: {params.get('cad_query')}, site_mode: {params.get('site_mode')}", flush=True)
            print(f"  uds_mode: '{params.get('uds_mode')}', entry_road_mode: '{params.get('entry_road_mode')}'", flush=True)
            print(f"  entry_points ({len(entry_pts)}), custom_roads: {len(custom_rds)}, gen_mode: {params.get('gen_mode')}", flush=True)
            print("-" * 65, flush=True)

        try:
            if api_path == "/api/site-preview":
                from dashboard_prototype.generator_service import preview_site
                result = preview_site(params)
                resp_obj = result
            elif api_path == "/api/generate":
                result = gs_mod.run_pipeline(params)
                resp_obj = result
            elif api_path == "/api/variants":
                from dashboard_prototype.generator_service import compute_variants_matrix
                variants = compute_variants_matrix(params)
                resp_obj = {"variants": variants}
                result = {"roads": {}}
            else:
                resp_obj = {}
                result = {}

            # Диагностика результата расчета (для ключевых операций)
            if not is_preview and isinstance(result, dict):
                r_dict = result.get("roads", {}) or {}
                sb_data = r_dict.get("sub_blocks_data") or []
                print(f"[DIAG SERVER] Результат {api_path}:", flush=True)
                print(f"  sub_blocks: {len(sb_data)}, buildings: {len(result.get('buildings') or [])}", flush=True)
                print("=" * 65 + "\n", flush=True)

            response_bytes = json.dumps(resp_obj, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(response_bytes)))
            self._send_cors_headers()
            self.end_headers()
            self._safe_write(response_bytes)
        except Exception as e:
            import traceback
            err_text = traceback.format_exc()
            print(f"[DIAG SERVER ERROR] {api_path}: {e}\n{err_text}")
            err_bytes = json.dumps({"error": str(e), "traceback": err_text}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_bytes)))
            self._send_cors_headers()
            self.end_headers()
            self._safe_write(err_bytes)

    def _handle_upload_gpzu(self):
        import json, base64
        from dashboard_prototype.generator_service import process_gpzu_upload
        from dashboard_studio.ocr_gpzu import is_scanned_pdf, process_scanned_gpzu

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode("utf-8")
        try:
            data = json.loads(post_data) if post_data else {}
            raw_b64 = data.get("file_base64", "")
            if "," in raw_b64 and raw_b64.startswith("data:"):
                raw_b64 = raw_b64.split(",", 1)[1]
            filename = data.get("filename", "gpzu_document.pdf")
            msk_zone = data.get("msk_zone")
            file_bytes = base64.b64decode(raw_b64)

            # 1. Попытка стандартного парсинга
            res = process_gpzu_upload(file_bytes, filename, msk_zone=msk_zone)

            # 2. Если файл — скан (или точек < 3), запускаем OCR fallback
            if (not res.get("success") or res.get("points_count", 0) < 3) and filename.lower().endswith(".pdf"):
                if is_scanned_pdf(file_bytes):
                    print(f"[Studio OCR] Запуск оптического распознавания скана '{filename}'...")
                    try:
                        ocr_res = process_scanned_gpzu(file_bytes, filename, msk_zone=msk_zone)
                        if ocr_res.get("success"):
                            res = ocr_res
                            print(f"[Studio OCR] Успешно распознано {res.get('points_count')} точек, КН {res.get('cadastral_number')}")
                        elif ocr_res.get("error") and not res.get("success"):
                            res = ocr_res
                    except Exception as ocr_err:
                        print(f"[Studio OCR Exception] {ocr_err}")
                        if not res.get("success"):
                            res = {"success": False, "error": f"Ошибка оптического распознавания скана: {ocr_err}"}

            response_bytes = json.dumps(res, ensure_ascii=False).encode("utf-8")
            self.send_response(200 if res.get("success") else 400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(response_bytes)))
            self._send_cors_headers()
            self.end_headers()
            self._safe_write(response_bytes)
        except Exception as e:
            err_bytes = json.dumps({"success": False, "error": str(e)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_bytes)))
            self._send_cors_headers()
            self.end_headers()
            self._safe_write(err_bytes)

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
            v3d = STUDIO_DIR / "viewer_3d.html"
            if not v3d.exists():
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

        if parsed.path.startswith("/libs/"):
            rel_file = parsed.path.replace("/libs/", "")
            lib_path = STUDIO_DIR / "libs" / rel_file
            if not lib_path.exists():
                lib_path = PROTOTYPE_DIR / "libs" / rel_file
            if lib_path.exists():
                with open(lib_path, "rb") as f:
                    content = f.read()
                mime = "application/javascript" if rel_file.endswith(".js") else "text/css"
                self.send_response(200)
                self.send_header("Content-Type", f"{mime}; charset=utf-8")
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

    ThreadingHTTPServer.allow_reuse_address = True
    server = None
    for attempt in range(5):
        try:
            server = ThreadingHTTPServer(("0.0.0.0", port), StudioHandler)
            break
        except OSError:
            import time
            time.sleep(0.5)
    if server is None:
        server = ThreadingHTTPServer(("0.0.0.0", port), StudioHandler)

    server.daemon_threads = True

    if open_browser:
        webbrowser.open(f"http://localhost:{port}")

    while True:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nСервер остановлен пользователем.")
            server.server_close()
            break
        except Exception as ex:
            print(f"[Сервер Studio] Исключение в цикле serve_forever: {ex}")
            import time
            time.sleep(0.5)


if __name__ == "__main__":
    import traceback
    try:
        port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
        run_studio_server(port=port, open_browser=False)
    except BaseException as e:
        try:
            with open("scratch/server_crash.txt", "a", encoding="utf-8") as f:
                f.write(f"\n--- CRASH: {type(e).__name__}: {e} ---\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        raise
