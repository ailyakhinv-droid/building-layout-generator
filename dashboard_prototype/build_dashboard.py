"""Сборщик полнофункционального HTML-дашборда ТЭП.
Включает 100% возможностей Streamlit:
- Участок: Режим 1 (по кадастру/адресу/координатам + прикрепление CAD) и Режим 2 (по чертежу DWG/DXF со слоями);
- Точные координаты WGS-84 (ручная широта/долгота);
- Убрана лишняя строка сценариев (дублирующая сайдбар);
- Интерактивный генератор застройки;
- Территориальный баланс РНГП (парковки, гостевые, подземный дефицит в м², площадки);
- Матрица вариантов этажности (Optimizer);
- Квартирография по корпусам;
- Скачивание файлов: DXF (AutoCAD), 3D HTML, GeoJSON, TXT отчет.
"""

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DIR = Path(__file__).resolve().parent
DATA_PATH = DIR / "data.json"
OUT_HTML = DIR / "index.html"

from dashboard_prototype.generator_service import get_library_catalog


def build():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        scenarios = json.load(f)

    catalog = get_library_catalog()

    # Безопасное экранирование
    data_json_str = (
        json.dumps(scenarios, ensure_ascii=False)
        .replace("</script", "<\\/script")
        .replace("</Script", "<\\/Script")
    )
    catalog_json_str = (
        json.dumps(catalog, ensure_ascii=False)
        .replace("</script", "<\\/script")
        .replace("</Script", "<\\/Script")
    )

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Генератор застройки · Интерактивный дашборд ТЭП</title>
  <style>
    /* ==========================================================================
       1. ДИЗАЙН-СИСТЕМА (СТИЛЬ MIASS DASHBOARD)
       ========================================================================== */
    :root {{
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      --background: #f8fafc;
      --surface: #ffffff;
      --surface-raised: #ffffff;
      --muted: #f1f5f9;
      --border: #e2e8f0;
      --border-strong: #cbd5e1;
      --text: #0f172a;
      --secondary: #64748b;
      --accent: #538db2;
      --accent-hover: #407596;
      --positive: #059669;
      --negative: #dc2626;
      --warning: #d97706;
      --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 10px 15px -3px rgba(0,0,0,0.03);
      --shadow-lg: 0 4px 6px -1px rgba(0,0,0,0.05), 0 20px 25px -5px rgba(0,0,0,0.05);
      --radius-sm: 6px;
      --radius: 10px;
      --radius-lg: 14px;
      --sidebar-width: 380px;
    }}

    [data-theme="dark"] {{
      --background: #0f172a;
      --surface: #1e293b;
      --surface-raised: #1e293b;
      --muted: #334155;
      --border: #334155;
      --border-strong: #475569;
      --text: #f8fafc;
      --secondary: #94a3b8;
      --accent: #6ba6cd;
      --accent-hover: #82b9dc;
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: var(--font-sans);
      background-color: var(--background);
      color: var(--text);
      line-height: 1.5;
      font-size: 14px;
      -webkit-font-smoothing: antialiased;
      padding-bottom: 60px;
    }}

    /* ЕДИНАЯ ЧИСТАЯ ШАПКА */
    .app-header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 12px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 30;
      box-shadow: 0 1px 2px rgba(0,0,0,0.02);
    }}

    .app-title-group {{ display: flex; align-items: center; gap: 12px; }}

    .app-logo {{
      width: 38px; height: 38px;
      background: var(--muted);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      display: flex; align-items: center; justify-content: center;
      font-size: 20px;
    }}

    .app-title {{ font-size: 17px; font-weight: 700; color: var(--text); }}
    
    .app-status-strip {{
      font-size: 12px;
      color: var(--secondary);
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 2px;
    }}
    .app-status-strip a {{
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }}
    .app-status-strip a:hover {{ text-decoration: underline; }}

    .header-actions {{ display: flex; align-items: center; gap: 10px; }}

    .btn-toggle-sidebar {{
      background: var(--surface);
      border: 1px solid var(--border-strong);
      color: var(--text);
      border-radius: var(--radius-sm);
      padding: 7px 12px;
      font-size: 13px; font-weight: 600;
      cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
      transition: all 0.15s ease;
    }}
    .btn-toggle-sidebar:hover {{ background: var(--muted); }}
    .btn-toggle-sidebar.active {{
      background: var(--accent); border-color: var(--accent); color: #fff;
    }}

    .theme-toggle {{
      background: var(--muted); border: 1px solid var(--border);
      color: var(--text); border-radius: var(--radius-sm);
      padding: 7px 12px; cursor: pointer; font-size: 13px; font-weight: 500;
    }}

    /* ==========================================================================
       2. ВЫДВИЖНАЯ ПАНЕЛЬ ПАРАМЕТРОВ (SIDEBAR)
       ========================================================================== */
    .app-layout {{
      display: flex; position: relative; min-height: calc(100vh - 65px);
    }}

    .settings-drawer {{
      width: var(--sidebar-width); min-width: var(--sidebar-width);
      background: var(--surface); border-right: 1px solid var(--border);
      height: calc(100vh - 65px); position: sticky; top: 65px;
      overflow-y: auto; padding: 18px; display: flex; flex-direction: column; gap: 18px;
      transition: margin-left 0.25s cubic-bezier(0.4, 0, 0.2, 1);
      z-index: 25;
    }}
    .settings-drawer.collapsed {{ margin-left: calc(-1 * var(--sidebar-width)); }}

    .settings-section {{
      display: flex; flex-direction: column; gap: 10px;
      padding-bottom: 14px; border-bottom: 1px solid var(--border);
    }}
    .settings-section:last-child {{ border-bottom: none; }}

    .settings-section-title {{
      font-size: 11px; font-weight: 700; color: var(--secondary);
      text-transform: uppercase; letter-spacing: 0.04em;
    }}

    .segmented-control {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      background: var(--muted);
      border-radius: var(--radius-sm);
      padding: 3px;
      gap: 3px;
    }}
    .segmented-btn {{
      border: 0;
      background: transparent;
      padding: 6px 8px;
      font-size: 11px;
      font-weight: 600;
      color: var(--secondary);
      border-radius: 4px;
      cursor: pointer;
      text-align: center;
      transition: all 0.12s ease;
    }}
    .segmented-btn.active {{
      background: var(--surface);
      color: var(--text);
      box-shadow: 0 1px 2px rgba(0,0,0,0.06);
    }}

    .control-row {{ display: flex; flex-direction: column; gap: 4px; }}
    .control-label {{ font-size: 12px; font-weight: 600; color: var(--text); display: flex; justify-content: space-between; }}
    .control-hint {{ font-size: 11px; color: var(--secondary); }}

    .input-text {{
      font-family: inherit; font-size: 13px; padding: 6px 10px;
      border: 1px solid var(--border-strong); border-radius: var(--radius-sm);
      background: var(--surface); color: var(--text); width: 100%;
    }}

    .slider-container {{ display: flex; align-items: center; gap: 8px; }}
    .slider-input {{ flex: 1; height: 5px; accent-color: var(--accent); cursor: pointer; }}
    .slider-badge {{
      font-size: 11px; font-weight: 700; color: var(--text);
      background: var(--muted); padding: 2px 6px; border-radius: var(--radius-sm);
      min-width: 44px; text-align: center;
    }}

    /* Кнопки быстрого поворота участка */
    .rot-buttons-row {{
      display: flex; gap: 4px; margin-top: 6px;
    }}
    .btn-rot {{
      flex: 1; padding: 4px 0; font-size: 11px; font-weight: 600;
      background: var(--muted); color: var(--text); border: 1px solid var(--border);
      border-radius: var(--radius-sm); cursor: pointer; transition: all 0.15s ease;
      text-align: center;
    }}
    .btn-rot:hover {{
      background: var(--surface-raised); border-color: var(--accent); color: var(--accent);
    }}
    .btn-rot-reset {{
      flex: 1.4; color: var(--secondary);
    }}
    .btn-rot-reset:hover {{
      color: var(--text); border-color: var(--border-strong);
    }}

    .toggle-row {{
      display: flex; align-items: center; justify-content: space-between; gap: 10px; cursor: pointer;
    }}
    .toggle-switch {{ position: relative; width: 36px; height: 20px; flex-shrink: 0; }}
    .toggle-switch input {{ opacity: 0; width: 0; height: 0; }}
    .toggle-slider {{
      position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0;
      background-color: var(--border-strong); transition: .2s; border-radius: 20px;
    }}
    .toggle-slider:before {{
      position: absolute; content: ""; height: 14px; width: 14px; left: 3px; bottom: 3px;
      background-color: white; transition: .2s; border-radius: 50%;
    }}
    input:checked + .toggle-slider {{ background-color: var(--accent); }}
    input:checked + .toggle-slider:before {{ transform: translateX(16px); }}

    /* Загрузка CAD файла (Drag & Drop box) */
    .file-dropzone {{
      border: 1px dashed var(--border-strong);
      border-radius: var(--radius-sm);
      padding: 12px 14px;
      text-align: center;
      background: var(--muted);
      cursor: pointer;
      transition: all 0.15s ease;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;
    }}
    .file-dropzone:hover {{
      border-color: var(--accent);
      background: rgba(83, 141, 178, 0.05);
    }}
    .file-dropzone-text {{ font-size: 12px; font-weight: 600; color: var(--text); }}
    .file-dropzone-hint {{ font-size: 11px; color: var(--secondary); }}
    .file-badge {{
      display: inline-flex; align-items: center; gap: 6px; font-size: 11px;
      font-weight: 600; padding: 3px 8px; border-radius: 4px;
      background: rgba(5, 150, 105, 0.12); color: var(--positive); margin-top: 4px;
    }}

    /* Аккордеон тонких настроек */
    details.expander {{
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      padding: 8px 10px; background: var(--surface);
    }}
    details.expander summary {{
      font-size: 11px; font-weight: 700; color: var(--secondary);
      cursor: pointer; user-select: none; text-transform: uppercase; letter-spacing: 0.02em;
    }}

    .sub-col-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}

    .select-custom {{
      font-family: inherit; font-size: 13px; font-weight: 500;
      color: var(--text); background: var(--surface);
      border: 1px solid var(--border-strong); border-radius: var(--radius-sm);
      padding: 5px 26px 5px 10px; cursor: pointer; appearance: none;
      background-image: url("data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2212%22%20height%3D%2212%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22%2364748b%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%3E%3Cpolyline%20points%3D%226%209%2012%2015%2018%209%22%3E%3C%2Fpolyline%3E%3C%2Fsvg%3E");
      background-repeat: no-repeat; background-position: right 8px center;
    }}

    /* Чипсы секций */
    .pref-sections-chips {{
      display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;
    }}
    .section-chip {{
      font-size: 11px; font-weight: 500; padding: 3px 7px; border-radius: 4px;
      border: 1px solid var(--border-strong); background: var(--surface);
      cursor: pointer; user-select: none;
    }}
    .section-chip.selected {{
      background: var(--accent); border-color: var(--accent); color: #fff;
    }}

    .btn-generate {{
      font-family: inherit; font-size: 14px; font-weight: 700;
      background: var(--accent); color: #ffffff; border: 0;
      border-radius: var(--radius); padding: 12px 18px; cursor: pointer;
      display: flex; align-items: center; justify-content: center; gap: 8px;
      box-shadow: 0 4px 12px rgba(83, 141, 178, 0.3); width: 100%;
    }}
    .btn-generate:hover {{ background: var(--accent-hover); }}
    .btn-generate:disabled {{ opacity: 0.6; cursor: not-allowed; }}

    /* СТАТУС БЭКЕНДА В ШАПКЕ */
    .backend-badge {{
      display: inline-flex; align-items: center; gap: 7px;
      font-size: 11.5px; font-weight: 600; padding: 5px 12px;
      border-radius: 20px; cursor: pointer; transition: all 0.2s ease;
      user-select: none; border: 1px solid transparent;
    }}
    .backend-badge.online {{
      background: rgba(16, 185, 129, 0.12); color: #059669; border-color: rgba(16, 185, 129, 0.3);
    }}
    .backend-badge.online:hover {{
      background: rgba(16, 185, 129, 0.18);
    }}
    .backend-badge.offline {{
      background: rgba(245, 158, 11, 0.12); color: #d97706; border-color: rgba(245, 158, 11, 0.35);
    }}
    .backend-badge.offline:hover {{
      background: rgba(245, 158, 11, 0.2);
    }}
    .status-dot {{
      width: 8px; height: 8px; border-radius: 50%; display: inline-block;
    }}
    .online .status-dot {{ background: #10b981; box-shadow: 0 0 6px #10b981; }}
    .offline .status-dot {{ background: #f59e0b; }}

    /* СТЕППЕР ЭТАПОВ */
    .stepper-container {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--muted);
      padding: 3px 8px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border);
    }}
    .stepper-step {{
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 11.5px;
      font-weight: 600;
      color: var(--secondary);
      padding: 3px 8px;
      border-radius: 4px;
      transition: all 0.2s ease;
      cursor: pointer;
      user-select: none;
    }}
    .stepper-step.active {{
      background: var(--surface);
      color: var(--accent);
      box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    }}
    .stepper-step.completed {{
      color: var(--positive);
    }}
    .stepper-num {{
      width: 17px; height: 17px; border-radius: 50%;
      background: var(--border-strong); color: #fff;
      display: inline-flex; align-items: center; justify-content: center;
      font-size: 10px; font-weight: 700;
    }}
    .active .stepper-num {{ background: var(--accent); }}
    .completed .stepper-num {{ background: var(--positive); }}
    .stepper-arrow {{ color: var(--secondary); font-size: 11px; }}

    /* БАННЕРЫ ЭТАПОВ */
    .stage-banner {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-left: 4px solid var(--accent);
      border-radius: var(--radius);
      padding: 13px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      box-shadow: var(--shadow);
      transition: all 0.25s ease;
    }}
    .stage-banner-locked {{
      border-left-color: var(--positive);
      background: rgba(5, 150, 105, 0.03);
    }}
    .stage-banner-content {{
      display: flex;
      align-items: center;
      gap: 12px;
      flex: 1;
    }}
    .stage-banner-badge {{
      display: inline-flex;
      align-items: center;
      font-size: 10.5px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      padding: 4px 9px;
      border-radius: 20px;
      background: rgba(83, 141, 178, 0.12);
      color: var(--accent);
      white-space: nowrap;
    }}
    .stage-banner-badge-locked {{
      background: rgba(5, 150, 105, 0.12);
      color: var(--positive);
    }}
    .stage-banner-texts h2 {{
      font-size: 14.5px;
      font-weight: 700;
      color: var(--text);
      line-height: 1.25;
      margin-bottom: 2px;
    }}
    .stage-banner-desc {{
      font-size: 12px;
      color: var(--secondary);
      line-height: 1.35;
    }}
    .stage-banner-actions {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }}
    .btn-lock-site {{
      background: #059669 !important;
      border-color: #059669 !important;
      color: #ffffff !important;
      font-weight: 700 !important;
      box-shadow: 0 4px 12px rgba(5, 150, 105, 0.35) !important;
      transition: all 0.15s ease;
      cursor: pointer;
    }}
    .btn-lock-site:hover {{
      background: #047857 !important;
      transform: translateY(-1px);
    }}
    .btn-unlock-site {{
      background: var(--surface) !important;
      border: 1px solid var(--border-strong) !important;
      color: var(--text) !important;
      font-weight: 600 !important;
      cursor: pointer;
    }}
    .btn-unlock-site:hover {{
      background: var(--muted) !important;
    }}
    .sidebar-stage2-locked {{
      opacity: 0.45;
      pointer-events: none;
      filter: grayscale(0.5);
      position: relative;
    }}
    .sidebar-lock-notice {{
      background: rgba(217, 119, 6, 0.08);
      border: 1px dashed var(--warning);
      border-radius: var(--radius-sm);
      padding: 8px 10px;
      font-size: 11px;
      color: var(--warning);
      line-height: 1.35;
      margin-top: 4px;
      font-weight: 500;
    }}

    /* ГЛАВНАЯ ОБЛАСТЬ */
    .content-area {{
      flex: 1; min-width: 0; padding: 20px 24px;
      display: flex; flex-direction: column; gap: 24px;
    }}

    /* KPI СЕТКА ИЗ 10 КАРТОЧЕК */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 12px;
    }}
    @media (max-width: 1550px) {{ .kpi-grid {{ grid-template-columns: repeat(4, 1fr); }} }}
    @media (max-width: 1200px) {{ .kpi-grid {{ grid-template-columns: repeat(3, 1fr); }} }}
    @media (max-width: 860px) {{ .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
    @media (max-width: 540px) {{ .kpi-grid {{ grid-template-columns: 1fr; }} }}

    .metric-card {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 13px 15px; box-shadow: var(--shadow);
      display: flex; flex-direction: column; gap: 3px; position: relative;
      transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
    }}
    .metric-card:hover {{
      box-shadow: var(--shadow-lg);
      border-color: var(--border-strong);
      transform: translateY(-2px);
    }}
    .metric-card-header {{
      display: flex; align-items: center; justify-content: space-between; gap: 6px;
    }}
    .metric-card-title {{
      font-size: 11px; font-weight: 700; color: var(--secondary); text-transform: uppercase; letter-spacing: 0.04em;
      display: flex; align-items: center; gap: 5px;
    }}
    .metric-card-value {{
      font-size: 22px; font-weight: 700; color: var(--text); letter-spacing: -0.02em; line-height: 1.15; margin: 4px 0 2px 0;
    }}
    .metric-card-desc {{
      font-size: 11.5px; color: var(--secondary); line-height: 1.35; flex-grow: 1;
    }}
    .metric-card-desc strong {{ color: var(--text); }}

    .badge-status {{
      display: inline-flex; align-items: center; gap: 4px; font-size: 10.5px; font-weight: 600;
      padding: 2px 6px; border-radius: 4px; width: fit-content; margin-top: 4px;
    }}
    .badge-ok {{ background: rgba(5, 150, 105, 0.12); color: var(--positive); }}
    .badge-warn {{ background: rgba(217, 119, 6, 0.12); color: var(--warning); }}
    .badge-info {{ background: rgba(83, 141, 178, 0.12); color: var(--accent); }}

    /* КАРТА И ИНСПЕКТОР */
    .spatial-split {{
      display: grid; grid-template-columns: minmax(0, 1.85fr) minmax(360px, 1fr);
      gap: 20px; align-items: stretch;
    }}
    @media (max-width: 1100px) {{ .spatial-split {{ grid-template-columns: 1fr; }} }}

    .card {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: var(--radius-lg); box-shadow: var(--shadow);
      overflow: hidden; display: flex; flex-direction: column;
    }}
    .card-header {{
      padding: 12px 20px; border-bottom: 1px solid var(--border);
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      background: var(--surface);
    }}
    .card-title {{ font-size: 15px; font-weight: 700; color: var(--text); }}
    .card-body {{ padding: 18px 20px; display: flex; flex-direction: column; gap: 14px; }}

    .view-tabs {{
      display: inline-flex; background: var(--muted); border-radius: var(--radius-sm);
      padding: 3px; gap: 2px;
    }}
    .view-tab-btn {{
      border: 0; background: transparent; padding: 4px 10px;
      font-size: 12px; font-weight: 500; color: var(--secondary);
      border-radius: 4px; cursor: pointer;
    }}
    .view-tab-btn.active {{
      background: var(--surface); color: var(--text); font-weight: 600;
      box-shadow: 0 1px 2px rgba(0,0,0,0.06);
    }}

    .map-canvas-container {{
      height: 640px; position: relative; overflow: hidden;
      background: #f1f5f9; user-select: none;
    }}
    [data-theme="dark"] .map-canvas-container {{ background: #0f172a; }}

    .map-svg {{ width: 100%; height: 100%; display: block; cursor: grab; }}
    .map-svg:active {{ cursor: grabbing; }}

    .map-floating-controls {{
      position: absolute; left: 14px; top: 14px; display: flex; flex-direction: column;
      border: 1px solid var(--border-strong); border-radius: var(--radius-sm);
      overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); background: var(--surface); z-index: 5;
    }}
    .map-btn {{
      width: 36px; height: 34px; border: 0; border-bottom: 1px solid var(--border);
      background: var(--surface); color: var(--text); font-size: 17px; font-weight: 600;
      cursor: pointer; display: flex; align-items: center; justify-content: center;
    }}
    .map-btn:last-child {{ border-bottom: 0; }}
    .map-btn:hover {{ background: var(--muted); }}

    .north-arrow {{
      position: absolute; top: 16px; right: 18px; text-align: center;
      font-weight: 700; color: var(--secondary); line-height: 1.1; font-size: 13px;
      background: rgba(255,255,255,0.85); backdrop-filter: blur(4px);
      padding: 4px 8px; border-radius: var(--radius-sm); border: 1px solid var(--border);
      pointer-events: none;
      transition: transform 0.25s ease-out;
      transform-origin: center center;
    }}

    .map-floating-legend {{
      position: absolute; left: 14px; bottom: 14px; padding: 12px 14px;
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
      box-shadow: var(--shadow-lg); max-width: 250px; font-size: 11px; line-height: 1.5; z-index: 5; pointer-events: none;
    }}
    .map-floating-legend strong {{ display: block; font-size: 12px; margin-bottom: 6px; color: var(--text); }}
    .legend-item {{ display: flex; align-items: center; gap: 8px; margin-bottom: 3px; color: var(--secondary); }}
    .legend-chip {{ width: 14px; height: 10px; border-radius: 2px; flex-shrink: 0; }}

    .map-tooltip {{
      position: absolute; pointer-events: none; background: var(--surface); color: var(--text);
      border: 1px solid var(--border-strong); border-radius: var(--radius-sm); padding: 8px 12px;
      font-size: 12px; line-height: 1.4; box-shadow: var(--shadow-lg); z-index: 10;
      transform: translate(-50%, -115%); white-space: nowrap; display: none;
    }}

    .svg-site-boundary {{ fill: none; stroke: #64748b; stroke-width: 1.8; stroke-dasharray: 6 4; }}
    .svg-buildable-area {{ fill: rgba(83, 141, 178, 0.05); stroke: rgba(83, 141, 178, 0.4); stroke-width: 1; }}
    .svg-red-line {{ fill: none; stroke: #ef4444; stroke-width: 2.2; }}
    .svg-section {{ stroke: #ffffff; stroke-width: 1; cursor: pointer; transition: stroke 0.15s ease; }}
    .svg-section:hover {{ stroke: #0f172a; stroke-width: 2.6; }}
    .svg-section.selected {{
      stroke: #f59e0b !important; stroke-width: 3.5 !important;
      filter: drop-shadow(0 0 6px rgba(245, 158, 11, 0.6));
    }}

    /* ИНСПЕКТОР */
    .inspector-card {{
      padding: 20px; display: flex; flex-direction: column; gap: 16px;
      overflow-y: auto; max-height: 640px;
    }}
    .inspector-empty {{
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      text-align: center; padding: 60px 20px; color: var(--secondary); gap: 12px; height: 100%;
    }}
    .inspector-header {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }}
    .inspector-title {{ font-size: 17px; font-weight: 700; color: var(--text); }}
    .category-badge {{
      display: inline-block; font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 9999px; color: #fff;
    }}
    .detail-grid {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
      background: var(--muted); border-radius: var(--radius); padding: 12px;
    }}
    .detail-item dt {{ font-size: 11px; color: var(--secondary); text-transform: uppercase; font-weight: 600; }}
    .detail-item dd {{ font-size: 14px; font-weight: 700; color: var(--text); }}

    .feature-box {{
      border: 1px solid var(--border); border-radius: var(--radius); padding: 12px 14px;
      display: flex; flex-direction: column; gap: 6px;
    }}
    .feature-box-title {{ font-size: 12px; font-weight: 600; color: var(--secondary); }}
    .apt-bar-row {{ display: flex; align-items: center; gap: 8px; font-size: 12px; }}
    .apt-bar-label {{ width: 60px; color: var(--secondary); }}
    .apt-bar-track {{ flex: 1; height: 7px; background: var(--muted); border-radius: 4px; overflow: hidden; }}
    .apt-bar-fill {{ height: 100%; background: var(--accent); border-radius: 4px; }}
    .apt-bar-val {{ width: 45px; text-align: right; font-weight: 600; color: var(--text); }}

    /* АНАЛИТИКА */
    .sub-grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
    @media (max-width: 900px) {{ .sub-grid-2 {{ grid-template-columns: 1fr; }} }}

    .sub-grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
    @media (max-width: 900px) {{ .sub-grid-4 {{ grid-template-columns: repeat(2, 1fr); }} }}

    .mini-stat-card {{
      background: var(--muted); border-radius: var(--radius); padding: 12px 14px;
      display: flex; flex-direction: column; gap: 4px;
    }}
    .mini-stat-title {{ font-size: 11px; color: var(--secondary); font-weight: 600; }}
    .mini-stat-val {{ font-size: 18px; font-weight: 700; color: var(--text); }}
    .mini-stat-sub {{ font-size: 11px; color: var(--secondary); }}

    .warning-banner {{
      padding: 10px 14px; border-radius: var(--radius-sm); font-size: 13px;
      display: flex; align-items: center; gap: 8px;
    }}
    .warning-warn {{ background: rgba(217, 119, 6, 0.1); color: var(--warning); border: 1px solid rgba(217, 119, 6, 0.25); }}
    .warning-info {{ background: rgba(83, 141, 178, 0.1); color: var(--accent); border: 1px solid rgba(83, 141, 178, 0.25); }}

    .progress-list {{ display: flex; flex-direction: column; gap: 10px; }}
    .progress-item {{ display: flex; flex-direction: column; gap: 4px; }}
    .progress-header {{ display: flex; justify-content: space-between; font-size: 12px; }}
    .progress-track {{ height: 8px; background: var(--muted); border-radius: 4px; overflow: hidden; }}
    .progress-fill {{ height: 100%; border-radius: 4px; }}

    /* ТАБЛИЦЫ */
    .table-wrapper {{
      overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius);
    }}
    .data-table {{ width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }}
    .data-table th {{
      background: var(--muted); padding: 10px 14px; font-weight: 600;
      color: var(--secondary); font-size: 11px; text-transform: uppercase; letter-spacing: 0.02em;
    }}
    .data-table td {{ padding: 10px 14px; border-top: 1px solid var(--border); color: var(--text); }}
    .data-table tbody tr:hover {{ background: var(--muted); }}
    .data-table tbody tr.selected-row {{ background: rgba(245, 158, 11, 0.12) !important; }}

    .btn {{
      font-family: inherit; font-size: 12px; font-weight: 600; padding: 6px 12px;
      border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--surface);
      color: var(--text); cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
      text-decoration: none;
    }}
    .btn:hover {{ background: var(--muted); }}
    .btn-primary {{ background: var(--accent); border-color: var(--accent); color: #ffffff; }}
    .btn-primary:hover {{ background: var(--accent-hover); }}

    .sections-catalog-grid {{
      display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px;
    }}
    @media (max-width: 1000px) {{ .sections-catalog-grid {{ grid-template-columns: 1fr; }} }}

    .catalog-item-card {{
      border: 1px solid var(--border); border-radius: var(--radius); padding: 14px;
      background: var(--surface); display: flex; flex-direction: column; gap: 8px;
    }}
    .catalog-item-header {{ display: flex; justify-content: space-between; align-items: flex-start; }}
    .catalog-item-name {{ font-size: 14px; font-weight: 700; color: var(--text); }}
    .catalog-item-code {{ font-size: 11px; color: var(--secondary); }}

    /* МОДАЛЬНОЕ ОКНО */
    .modal-backdrop {{
      position: fixed; top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.5); backdrop-filter: blur(3px);
      display: none; align-items: center; justify-content: center; z-index: 100;
    }}
    .modal-box {{
      background: var(--surface); border-radius: var(--radius-lg); width: 90%; max-width: 800px;
      max-height: 85vh; display: flex; flex-direction: column; overflow: hidden;
      box-shadow: 0 20px 25px -5px rgba(0,0,0,0.2);
    }}
    .modal-header {{
      padding: 16px 20px; border-bottom: 1px solid var(--border);
      display: flex; justify-content: space-between; align-items: center;
    }}
    .modal-body {{ padding: 20px; overflow-y: auto; font-family: monospace; font-size: 12px; white-space: pre-wrap; }}
    .modal-close {{ background: transparent; border: 0; font-size: 18px; cursor: pointer; color: var(--secondary); }}

    .toast-msg {{
      position: fixed; bottom: 24px; right: 24px; background: var(--surface); color: var(--text);
      border: 1px solid var(--border-strong); border-radius: var(--radius); padding: 12px 18px;
      box-shadow: var(--shadow-lg); font-size: 13px; font-weight: 500; display: flex; align-items: center;
      gap: 10px; z-index: 100; transform: translateY(100px); opacity: 0; transition: all 0.3s ease;
    }}
    .toast-msg.show {{ transform: translateY(0); opacity: 1; }}
  </style>
</head>
<body>

  <!-- ЕДИНАЯ ЧИСТАЯ ШАПКА -->
  <header class="app-header">
    <div class="app-title-group">
      <div class="app-logo">🏗️</div>
      <div>
        <h1 class="app-title">Генератор застройки · ТЭП</h1>
        <div class="app-status-strip" id="site-status-strip">
          <span id="site-cad-label">📍 63:01:0709002:2320</span>
          <span>·</span>
          <span id="site-region-label">Самара, Кировский р-н (4.25 га)</span>
          <span>·</span>
          <span id="site-coords-label">WGS-84: [53.25020, 50.31840]</span>
          <span>·</span>
          <a href="#" id="link-yandex" target="_blank" rel="noopener">🌐 Яндекс.Карты ↗</a>
          <span>·</span>
          <a href="#" id="link-pkk" target="_blank" rel="noopener">🗺️ ПКК Росреестра ↗</a>
        </div>
      </div>
    </div>
    <!-- СТЕППЕР ЭТАПОВ В ШАПКЕ -->
    <div class="stepper-container" id="stepper-container">
      <div class="stepper-step active" id="stepper-step-1" title="Этап 1: Посадка и ориентация контура">
        <span class="stepper-num" id="stepper-num-1">1</span>
        <span class="stepper-label">1. Посадка участка</span>
      </div>
      <span class="stepper-arrow">→</span>
      <div class="stepper-step" id="stepper-step-2" title="Этап 2: Застройка и ТЭП">
        <span class="stepper-num" id="stepper-num-2">2</span>
        <span class="stepper-label">2. Застройка и ТЭП</span>
      </div>
    </div>
    <div class="header-actions">
      <span class="backend-badge offline" id="backend-status-badge" title="Статус сервера генератора (нажмите для справки)">
        <span class="status-dot"></span>
        <span id="backend-status-text">Проверка сервера...</span>
      </span>
      <button class="btn-toggle-sidebar active" id="btn-toggle-sidebar" title="Открыть / скрыть панель параметров">
        ⚙️ Параметры застройки
      </button>
      <button class="theme-toggle" id="theme-btn" title="Переключить тему">🌙 Тема</button>
    </div>
  </header>

  <!-- ОСНОВНОЙ МАКЕТ С ВЫДВИЖНОЙ ПАНЕЛЬЮ НАСТРОЕК -->
  <div class="app-layout">

    <!-- ЛЕВАЯ ВЫДВИЖНАЯ ПАНЕЛЬ ПАРАМЕТРОВ -->
    <aside class="settings-drawer" id="settings-drawer">

      <!-- РАЗДЕЛ 1: УЧАСТОК -->
      <div class="settings-section">
        <span class="settings-section-title">📐 Земельный участок</span>

        <!-- Переключатель режима: Кадастр vs DWG/DXF -->
        <div class="segmented-control">
          <button class="segmented-btn active" id="btn-mode-cadastre" type="button">1. По кадастру</button>
          <button class="segmented-btn" id="btn-mode-cad" type="button">2. По чертежу CAD</button>
        </div>

        <!-- КОНТЕЙНЕР РЕЖИМА 1: КАДАСТР -->
        <div id="container-mode-cadastre" style="display:flex; flex-direction:column; gap:8px;">
          <div class="control-row">
            <label class="control-label" for="cfg-parcel-presets">Каталог участков (пресеты РФ)</label>
            <select class="select-custom" id="cfg-parcel-presets" style="width:100%;">
              <option value="63:01:0709002:2320">Самара, Зубчаниновка (4.2 га)</option>
              <option value="72:23:0222001:16187">Тюмень, Алебашево (4.4 га)</option>
              <option value="77:17:0120316:1024">Москва, Коммунарка (3.6 га)</option>
              <option value="78:34:0004286:115">Санкт-Петербург, Приморский (3.4 га)</option>
              <option value="23:43:0106012:450">Краснодар, Зап. обход (4.3 га)</option>
              <option value="66:41:0101001:500">Екатеринбург, Академический</option>
              <option value="16:50:010101:200">Казань, Ново-Савиновский</option>
            </select>
          </div>

          <div class="control-row">
            <label class="control-label" for="cfg-cad-input">Кадастровый номер, адрес или координаты</label>
            <input type="text" class="input-text" id="cfg-cad-input" value="63:01:0709002:2320" placeholder="72:23:0222001:16187 или 'Тюмень'" />
          </div>

          <!-- Аккордеон тонких настроек координат и площади -->
          <details class="expander" id="cadastre-fine-expander">
            <summary>⚙️ Настройка площади и координат WGS-84</summary>
            <div style="display:flex; flex-direction:column; gap:8px; margin-top:8px;">
              <div class="control-row">
                <label class="control-label" for="cfg-area-input">Площадь участка, м²</label>
                <input type="number" class="input-text" id="cfg-area-input" value="42500" step="500" min="5000" />
              </div>

              <div class="sub-col-2">
                <div class="control-row">
                  <label class="control-label" for="cfg-manual-lat">Широта (Lat)</label>
                  <input type="number" class="input-text" id="cfg-manual-lat" value="0.0" step="0.0001" placeholder="0.0 — авто" />
                </div>
                <div class="control-row">
                  <label class="control-label" for="cfg-manual-lon">Долгота (Lon)</label>
                  <input type="number" class="input-text" id="cfg-manual-lon" value="0.0" step="0.0001" placeholder="0.0 — авто" />
                </div>
              </div>

              <div class="toggle-row" style="margin-top:2px;">
                <div>
                  <div class="control-label">Красная линия (отступ УДС)</div>
                  <div class="control-hint">Ограничение застройки вдоль улицы</div>
                </div>
                <label class="toggle-switch">
                  <input type="checkbox" id="cfg-redline-toggle" />
                  <span class="toggle-slider"></span>
                </label>
              </div>

              <!-- Прикрепление DXF поверх кадастра -->
              <div class="control-row" style="margin-top:4px;">
                <label class="control-label">📎 Прикрепить контур из чертежа (.dxf, .dwg)</label>
                <div class="file-dropzone" id="dropzone-cad-sub">
                  <span class="file-dropzone-text">Нажмите для выбора файла</span>
                  <span class="file-dropzone-hint">Заменяет контур точной геометрией из CAD</span>
                  <input type="file" id="file-cad-sub" accept=".dxf,.dwg" style="display:none;" />
                </div>
                <div id="cad-sub-badge" style="display:none;"></div>
              </div>
            </div>
          </details>
        </div>

        <!-- КОНТЕЙНЕР РЕЖИМА 2: ЧЕРТЕЖ DWG/DXF -->
        <div id="container-mode-cad" style="display:none; flex-direction:column; gap:8px;">
          <div class="control-row">
            <label class="control-label">Загрузите чертёж границы (.dxf, .dwg)</label>
            <div class="file-dropzone" id="dropzone-cad-main">
              <span class="file-dropzone-text">Выберите или перетащите .dxf / .dwg</span>
              <span class="file-dropzone-hint">Чертёж генплана с границей участка</span>
              <input type="file" id="file-cad-main" accept=".dxf,.dwg" style="display:none;" />
            </div>
            <div id="cad-main-badge" style="display:none;"></div>
          </div>

          <div class="control-row">
            <label class="control-label" for="cfg-dwg-assigned-cad">Присвоить кадастровый номер / регион</label>
            <input type="text" class="input-text" id="cfg-dwg-assigned-cad" value="63:01:0709002:2320" placeholder="Кадастровый номер для РНГП" />
          </div>

          <!-- Инспектор слоев чертежа -->
          <div class="control-row" id="cad-layers-container" style="display:none;">
            <label class="control-label" for="cfg-boundary-layer">Слой границы участка</label>
            <select class="select-custom" id="cfg-boundary-layer" style="width:100%; margin-bottom:6px;"></select>

            <label class="control-label" for="cfg-redline-layer">Слой красных линий</label>
            <select class="select-custom" id="cfg-redline-layer" style="width:100%;"></select>
          </div>

          <div class="sub-col-2">
            <div class="control-row">
              <label class="control-label" for="cfg-dwg-lat">Широта (Lat)</label>
              <input type="number" class="input-text" id="cfg-dwg-lat" value="0.0" step="0.0001" placeholder="0.0 — авто" />
            </div>
            <div class="control-row">
              <label class="control-label" for="cfg-dwg-lon">Долгота (Lon)</label>
              <input type="number" class="input-text" id="cfg-dwg-lon" value="0.0" step="0.0001" placeholder="0.0 — авто" />
            </div>
          </div>
        </div>

        <!-- Управление ориентацией (поворот) -->
        <div class="control-row" style="margin-top:6px;">
          <div class="control-label">
            <span>Поворот участка</span>
            <span class="slider-badge" id="cfg-rot-badge">0°</span>
          </div>
          <div class="slider-container">
            <input type="range" class="slider-input" id="cfg-rot-slider" min="0" max="360" step="1" value="0" />
          </div>
          <div class="rot-buttons-row">
            <button type="button" class="btn-rot" data-step="-15" title="Повернуть на -15°">-15°</button>
            <button type="button" class="btn-rot" data-step="-5" title="Повернуть на -5°">-5°</button>
            <button type="button" class="btn-rot btn-rot-reset" data-reset="0" title="Сбросить поворот на 0°">0° Сброс</button>
            <button type="button" class="btn-rot" data-step="5" title="Повернуть на +5°">+5°</button>
            <button type="button" class="btn-rot" data-step="15" title="Повернуть на +15°">+15°</button>
          </div>
        </div>

        <!-- Отступы от границ участка и красных линий -->
        <div class="sub-col-2" style="margin-top:6px;">
          <div class="control-row">
            <label class="control-label" for="cfg-boundary-setback">Отступ границы (м)</label>
            <input type="number" class="input-text" id="cfg-boundary-setback" value="6" min="0" max="25" step="1" />
          </div>
          <div class="control-row">
            <label class="control-label" for="cfg-redline-setback">Отступ КЛ (м)</label>
            <input type="number" class="input-text" id="cfg-redline-setback" value="5" min="0" max="25" step="1" />
          </div>
        </div>

        <!-- Кнопки закрепления участка на Шаге 1 -->
        <button class="btn btn-primary btn-lock-site" id="btn-lock-sidebar" type="button" style="width:100%; margin-top:8px; padding:11px 14px; font-size:13px; font-weight:700;">
          🔒 Закрепить участок и перейти к застройке
        </button>
        <button class="btn btn-unlock-site" id="btn-unlock-sidebar" type="button" style="display:none; width:100%; margin-top:8px; padding:9px 12px; font-size:12px;">
          🔓 Изменить посадку участка
        </button>
      </div>

      <!-- ГРУППА ЭТАПА 2 В САЙДБАРЕ -->
      <div id="sidebar-stage2-group">
        <div class="sidebar-lock-notice" id="sidebar-lock-notice">
          🔒 Параметры застройки активируются после закрепления участка (Шаг 1)
        </div>

      <!-- РАЗДЕЛ 2: КОНЦЕПЦИЯ И БИБЛИОТЕКА СЕКЦИЙ -->
      <div class="settings-section">
        <span class="settings-section-title">🏛️ Концепция и библиотека секций</span>

        <div class="control-row">
          <label class="control-label" for="cfg-typology">Типология застройки</label>
          <select class="select-custom" id="cfg-typology" style="width:100%;">
            <option value="AUTO">Квартальная / Смешанная (AUTO)</option>
            <option value="PERIMETER">Периметральные урбан-блоки (R2-Style)</option>
            <option value="TOWER">Точечная / Башенная (Towers)</option>
            <option value="U_SHAPE">П-образные дворы (U-Shape)</option>
            <option value="L_SHAPE">Г-образные корпуса (L-Shape)</option>
            <option value="LINEAR">Линейная застройка (Пластины)</option>
          </select>
        </div>

        <!-- БЛОК НАСТРОЕК УРБАН-БЛОКОВ R2 -->
        <div id="container-peri-settings" style="display:none; flex-direction:column; gap:8px; margin-top:6px; padding:10px; background:rgba(37,99,235,0.04); border:1px dashed #bfdbfe; border-radius:8px;">
          <div style="font-size:11.5px; font-weight:700; color:#1d4ed8; text-transform:uppercase; letter-spacing:0.5px;">🧱 Концепция урбан-блоков (R2)</div>

          <div class="control-row">
            <label class="control-label" for="cfg-peri-style">Конфигурация двора</label>
            <select class="select-custom" id="cfg-peri-style" style="width:100%;">
              <option value="U_SHAPE">П-образный (раскрытый двор)</option>
              <option value="CLOSED">Замкнутый квартал (с арками/проездами)</option>
              <option value="LINEAR_WINGS">Двухсторонний фронт (пластины)</option>
            </select>
          </div>

          <div class="control-row">
            <div style="display:flex; justify-content:space-between;">
              <label class="control-label" for="cfg-peri-block-size">Размер квартала</label>
              <span id="badge-peri-block-size" style="font-size:11px; font-weight:600; color:#2563eb;">100 м</span>
            </div>
            <input type="range" class="slider-input" id="cfg-peri-block-size" min="70" max="160" step="5" value="100" />
            <div class="control-hint">70–90 м: 4–6 блоков | 100–120 м: 2–4 блока | >140 м: 1 блок</div>
          </div>

          <div class="control-row">
            <div style="display:flex; justify-content:space-between;">
              <label class="control-label" for="cfg-peri-road-width">Ширина проезда</label>
              <span id="badge-peri-road-width" style="font-size:11px; font-weight:600; color:#2563eb;">16 м</span>
            </div>
            <input type="range" class="slider-input" id="cfg-peri-road-width" min="12" max="24" step="2" value="16" />
            <div class="control-hint">Коридор УДС между кварталами (проезжая часть + тротуары)</div>
          </div>
        </div>

        <div class="control-row">
          <label class="control-label" for="cfg-court-orient">Раскрытие дворов</label>
          <select class="select-custom" id="cfg-court-orient" style="width:100%;">
            <option value="SOUTH">На Юг (макс. инсоляция)</option>
            <option value="AUTO">По оси участка (AUTO)</option>
            <option value="EAST">На Восток</option>
            <option value="WEST">На Запад</option>
            <option value="NORTH">На Север</option>
          </select>
        </div>

        <div class="toggle-row">
          <div>
            <div class="control-label">Башни-акценты на флангах</div>
            <div class="control-hint">Размещать точечные секции на углах</div>
          </div>
          <label class="toggle-switch">
            <input type="checkbox" id="cfg-towers-mixed" checked />
            <span class="toggle-slider"></span>
          </label>
        </div>

        <div class="toggle-row">
          <div>
            <div class="control-label">Переменный шаг инсоляции</div>
            <div class="control-hint">Сокращает торцевой пожарный разрыв</div>
          </div>
          <label class="toggle-switch">
            <input type="checkbox" id="cfg-var-insolation" checked />
            <span class="toggle-slider"></span>
          </label>
        </div>

        <div class="control-row">
          <div class="control-label">
            <span>Разрешенные типовые секции</span>
            <span class="control-hint" id="pref-count-hint">Все типы</span>
          </div>
          <div class="pref-sections-chips" id="pref-sections-container"></div>
        </div>
      </div>

      <!-- РАЗДЕЛ 3: ЭТАЖНОСТЬ И РЕЖИМ ГЕНЕРАЦИИ -->
      <div class="settings-section">
        <span class="settings-section-title">📏 Этажность и высотный регламент</span>

        <div class="control-row">
          <label class="control-label" for="cfg-gen-mode">Режим генерации</label>
          <select class="select-custom" id="cfg-gen-mode" style="width:100%;">
            <option value="fixed">Заданная этажность</option>
            <option value="target">Подбор под целевой ТЭП</option>
            <option value="maximize">Максимизация жилой площади</option>
          </select>
        </div>

        <div class="control-row" id="cfg-target-tep-container" style="display:none;">
          <label class="control-label" for="cfg-target-metric">Целевой показатель</label>
          <select class="select-custom" id="cfg-target-metric" style="width:100%; margin-bottom:6px;">
            <option value="far">Плотность (FAR)</option>
            <option value="apts">Количество квартир</option>
            <option value="gfa">Общая площадь (GFA, м²)</option>
          </select>
          <input type="number" class="input-text" id="cfg-target-val" value="1.8" step="0.1" />
        </div>

        <div class="control-row" id="cfg-floors-container">
          <div class="control-label">
            <span>Целевая этажность</span>
            <span class="slider-badge" id="cfg-floors-badge">14 эт.</span>
          </div>
          <div class="slider-container">
            <input type="range" class="slider-input" id="cfg-floors-slider" min="3" max="30" step="1" value="14" />
          </div>
        </div>

        <div class="toggle-row">
          <div>
            <div class="control-label">Понижение к югу (каскад)</div>
            <div class="control-hint">Север выше, юг понижается до 8 эт.</div>
          </div>
          <label class="toggle-switch">
            <input type="checkbox" id="cfg-cascade-floors" checked />
            <span class="toggle-slider"></span>
          </label>
        </div>

        <div class="toggle-row">
          <div>
            <div class="control-label">Асимметричные крылья</div>
            <div class="control-hint">Разная длина крыльев корпусов</div>
          </div>
          <label class="toggle-switch">
            <input type="checkbox" id="cfg-asymmetric-wings" checked />
            <span class="toggle-slider"></span>
          </label>
        </div>

        <div class="control-row">
          <label class="control-label" for="cfg-floor-h">Высота этажа (м)</label>
          <input type="number" class="input-text" id="cfg-floor-h" value="3.0" step="0.1" min="2.5" max="4.5" />
        </div>

        <div class="control-row">
          <label class="control-label" for="cfg-max-h">Макс. высота здания (лимит ПЗЗ), м</label>
          <input type="number" class="input-text" id="cfg-max-h" value="0" step="1" min="0" placeholder="0 — без лимита" />
        </div>

        <div class="control-row">
          <div class="control-label">
            <span>Макс. секций в одном доме</span>
            <span class="slider-badge" id="cfg-max-sections-badge">8</span>
          </div>
          <div class="slider-container">
            <input type="range" class="slider-input" id="cfg-max-sections-slider" min="2" max="14" step="1" value="8" />
          </div>
        </div>
      </div>

      <!-- РАЗДЕЛ 4: РЕГИОНАЛЬНЫЕ НОРМАТИВЫ -->
      <div class="settings-section">
        <span class="settings-section-title">📜 Региональные нормативы (РНГП)</span>

        <div class="control-row">
          <label class="control-label" for="cfg-regional-norm">Регион проектирования</label>
          <select class="select-custom" id="cfg-regional-norm" style="width:100%;">
            <option value="russia_sp42">РФ — СП 42.13330.2016</option>
            <option value="moscow_mngp">Москва — МНГП</option>
            <option value="moscow_oblast_rngp">Московская область — РНГП</option>
            <option value="spb_rngp">Санкт-Петербург — РНГП</option>
          </select>
        </div>

        <div class="control-row">
          <div class="control-label">
            <span>Макс. FAR (плотность)</span>
            <span class="slider-badge" id="cfg-far-badge">2.50</span>
          </div>
          <div class="slider-container">
            <input type="range" class="slider-input" id="cfg-far-slider" min="0.5" max="4.0" step="0.1" value="2.5" />
          </div>
        </div>

        <div class="control-row">
          <div class="control-label">
            <span>Макс. BCR (КЗ застройки)</span>
            <span class="slider-badge" id="cfg-bcr-badge">40%</span>
          </div>
          <div class="slider-container">
            <input type="range" class="slider-input" id="cfg-bcr-slider" min="0.1" max="0.7" step="0.05" value="0.4" />
          </div>
        </div>
      </div>

      <!-- КНОПКА ГЕНЕРАЦИИ -->
      <button class="btn-generate" id="btn-run-pipeline">
        <span>🚀 Сгенерировать застройку</span>
      </button>

      </div><!-- закрытие sidebar-stage2-group -->

    </aside>

    <!-- ОСНОВНАЯ ОБЛАСТЬ КОНТЕНТА -->
    <main class="content-area">

      <!-- БАННЕР ШАГА 1 -->
      <div class="stage-banner stage-banner-1" id="stage-banner-1">
        <div class="stage-banner-content">
          <span class="stage-banner-badge">🧭 Шаг 1 из 2</span>
          <div class="stage-banner-texts">
            <h2>Посадка и ориентация участка</h2>
            <p class="stage-banner-desc">
              Выровняйте контур участка на карте OSM / спутниковых снимках: зажмите контур мышью для перемещения или крутите за верхний оранжевый маркер для поворота.
              После выравнивания зафиксируйте участок для перехода к расстановке корпусов и ТЭП.
            </p>
          </div>
        </div>
        <div class="stage-banner-actions">
          <button class="btn btn-primary btn-lock-site" id="btn-lock-main" type="button">
            🔒 Закрепить участок и перейти к застройке
          </button>
          <button class="btn" id="btn-reset-rot-main" type="button">↺ Сбросить угол (0°)</button>
        </div>
      </div>

      <!-- БАННЕР ШАГА 2 -->
      <div class="stage-banner stage-banner-2 stage-banner-locked" id="stage-banner-2" style="display:none;">
        <div class="stage-banner-content">
          <span class="stage-banner-badge stage-banner-badge-locked">🔒 Шаг 2 из 2</span>
          <div class="stage-banner-texts">
            <h2>Застройка и расчёт ТЭП</h2>
            <p class="stage-banner-desc" id="stage-2-status-desc">
              Участок зафиксирован: 4.25 га • поворот +0.0° • WGS-84: [53.25020, 50.31840]
            </p>
          </div>
        </div>
        <div class="stage-banner-actions">
          <button class="btn btn-unlock-site" id="btn-unlock-main" type="button">
            🔓 Изменить посадку участка
          </button>
        </div>
      </div>

      <!-- 1. ВЕРХНИЕ KPI (10 КАРТОЧЕК ОСНОВНЫХ ТЭП) -->
      <section class="kpi-grid">
        <!-- 1. GFA -->
        <div class="metric-card">
          <div class="metric-card-header">
            <span class="metric-card-title">🏢 Общая площадь (GFA)</span>
          </div>
          <span class="metric-card-value" id="kpi-gfa">—</span>
          <p class="metric-card-desc" id="kpi-gfa-desc">Жилая: <strong>—</strong> · Нежилая: <strong>—</strong></p>
          <span class="badge-status badge-ok" id="kpi-gfa-badge">Выход К1: —</span>
        </div>

        <!-- 2. ЖИЛОЙ ФОНД -->
        <div class="metric-card">
          <div class="metric-card-header">
            <span class="metric-card-title">🏠 Жилая площадь</span>
          </div>
          <span class="metric-card-value" id="kpi-living">—</span>
          <p class="metric-card-desc" id="kpi-living-desc">Всего: <strong>— кв.</strong> · ср. <strong>— м²</strong></p>
          <span class="badge-status badge-ok" id="kpi-living-badge">Комфорт-класс (30 м²/чел)</span>
        </div>

        <!-- 3. ПЛОТНОСТЬ (FAR) -->
        <div class="metric-card">
          <div class="metric-card-header">
            <span class="metric-card-title">📊 Плотность (FAR)</span>
          </div>
          <span class="metric-card-value" id="kpi-far">—</span>
          <p class="metric-card-desc" id="kpi-far-desc">Плотность жилфонда: <strong>—</strong></p>
          <span class="badge-status badge-ok" id="kpi-far-badge">СП 42: FAR ≤ 2.50</span>
        </div>

        <!-- 4. ПРОЦЕНТ ЗАСТРОЙКИ (BCR) -->
        <div class="metric-card">
          <div class="metric-card-header">
            <span class="metric-card-title">📐 Застройка (BCR)</span>
          </div>
          <span class="metric-card-value" id="kpi-bcr">—</span>
          <p class="metric-card-desc" id="kpi-bcr-desc">Пятно зданий: <strong>—</strong></p>
          <span class="badge-status badge-ok" id="kpi-bcr-badge">Лимит ПЗЗ ≤ 40%</span>
        </div>

        <!-- 5. КОММЕРЦИЯ / РИТЕЙЛ -->
        <div class="metric-card">
          <div class="metric-card-header">
            <span class="metric-card-title">🛍️ Коммерция / Ритейл</span>
          </div>
          <span class="metric-card-value" id="kpi-comm">—</span>
          <p class="metric-card-desc" id="kpi-comm-desc">1-е этажи корпусов: <strong>—</strong></p>
          <span class="badge-status badge-info" id="kpi-comm-badge">Стрит-ритейл</span>
        </div>

        <!-- 6. НАСЕЛЕНИЕ -->
        <div class="metric-card">
          <div class="metric-card-header">
            <span class="metric-card-title">👥 Население и социум</span>
          </div>
          <span class="metric-card-value" id="kpi-pop">—</span>
          <p class="metric-card-desc" id="kpi-pop-desc">Детсады: <strong>—</strong> · Школы: <strong>—</strong></p>
          <span class="badge-status badge-ok" id="kpi-pop-badge">Нормативы РНГП</span>
        </div>

        <!-- 7. ПАРКОВОЧНЫЕ МЕСТА -->
        <div class="metric-card">
          <div class="metric-card-header">
            <span class="metric-card-title">🚗 Машиноместа (РНГП)</span>
          </div>
          <span class="metric-card-value" id="kpi-parking">—</span>
          <p class="metric-card-desc" id="kpi-parking-desc">Наземных: <strong>—</strong> · Подземных: <strong>—</strong></p>
          <span class="badge-status badge-ok" id="kpi-parking-badge">Обеспеченность 100%</span>
        </div>

        <!-- 8. ОЗЕЛЕНЕНИЕ -->
        <div class="metric-card">
          <div class="metric-card-header">
            <span class="metric-card-title">🌳 Озеленение участка</span>
          </div>
          <span class="metric-card-value" id="kpi-green">—</span>
          <p class="metric-card-desc" id="kpi-green-desc">Доля участка: <strong>—</strong></p>
          <span class="badge-status badge-ok" id="kpi-green-badge">СП 42: ≥ 25%</span>
        </div>

        <!-- 9. ДВОРОВЫЕ ПЛОЩАДКИ -->
        <div class="metric-card">
          <div class="metric-card-header">
            <span class="metric-card-title">⚽ Дворовые площадки</span>
          </div>
          <span class="metric-card-value" id="kpi-playgrounds">—</span>
          <p class="metric-card-desc" id="kpi-playgrounds-desc">Дети: <strong>—</strong> · Спорт: <strong>—</strong></p>
          <span class="badge-status badge-ok" id="kpi-playgrounds-badge">Благоустройство</span>
        </div>

        <!-- 10. КОРПУСА И СЕКЦИИ -->
        <div class="metric-card">
          <div class="metric-card-header">
            <span class="metric-card-title">🏗️ Корпуса и секции</span>
          </div>
          <span class="metric-card-value" id="kpi-morphology">—</span>
          <p class="metric-card-desc" id="kpi-morphology-desc">Секций: <strong>—</strong> · Этажность: <strong>—</strong></p>
          <span class="badge-status badge-info" id="kpi-morphology-badge">Каскадная форма</span>
        </div>
      </section>

      <!-- 2. ЦЕНТРАЛЬНЫЙ СПЛИТ: КАРТА + ИНСПЕКТОР -->
      <section class="spatial-split">

        <!-- КАРТА -->
        <div class="card">
          <div class="card-header">
            <div style="display:flex; align-items:center; gap:10px;">
              <h2 class="card-title">Генплан застройки</h2>
              <div class="view-tabs">
                <button class="view-tab-btn active" id="tab-svg">📐 2D Схема</button>
                <button class="view-tab-btn" id="tab-osm">🛰️ 2D OSM</button>
                <button class="view-tab-btn" id="tab-3d">🏙️ 3D Сцена</button>
              </div>
            </div>

            <div class="card-controls" id="svg-controls">
              <span class="filter-label" style="margin-right:4px;">Раскраска:</span>
              <select class="select-custom" id="map-metric-select">
                <option value="category">По типам секций</option>
                <option value="floors">По этажности</option>
                <option value="building">По корпусам</option>
                <option value="gfa">По площади GFA</option>
              </select>
            </div>
          </div>

          <div class="map-canvas-container" id="view-container-svg">
            <svg class="map-svg" id="masterplan-svg" role="img" aria-label="Интерактивный генплан застройки">
              <g id="svg-viewport">
                <g id="svg-site-world">
                  <path id="svg-site-bound" class="svg-site-boundary" />
                  <path id="svg-buildable" class="svg-buildable-area" />
                  <g id="svg-redlines-group"></g>
                  <g id="svg-sections-group"></g>
                </g>
              </g>
            </svg>

            <div class="map-floating-controls">
              <button class="map-btn" id="btn-zoom-in" title="Приблизить">+</button>
              <button class="map-btn" id="btn-zoom-out" title="Отдалить">−</button>
              <button class="map-btn" id="btn-zoom-reset" title="Показать весь участок">⌂</button>
              <button class="map-btn" id="btn-zoom-focus" title="Приблизить выбранную секцию">⌖</button>
            </div>

            <div class="north-arrow">↑<br>С</div>

            <div class="map-floating-legend" id="map-legend">
              <strong id="legend-title">Типы типовых секций</strong>
              <div id="legend-items"></div>
            </div>

            <div class="map-tooltip" id="map-tooltip"></div>
          </div>

          <div id="view-container-osm" style="display:none; height:640px;">
            <iframe id="iframe-osm" style="width:100%; height:100%; border:0;" title="OSM Карта"></iframe>
          </div>

          <div id="view-container-3d" style="display:none; height:640px;">
            <iframe id="iframe-3d" style="width:100%; height:100%; border:0;" title="3D Модель"></iframe>
          </div>
        </div>

        <!-- ИНСПЕКТОР СЕКЦИИ -->
        <div class="card">
          <div class="card-header">
            <h2 class="card-title">Инспектор секции</h2>
            <button class="btn" id="btn-clear-selection" style="display:none;">Снять выбор</button>
          </div>

          <div class="inspector-card" id="inspector-content">
            <div class="inspector-empty" id="inspector-empty">
              <div class="inspector-empty-icon">⌖</div>
              <strong style="font-size:15px; color:var(--text);">Выберите секцию на генплане</strong>
              <p>Кликните по любой секции на карте или выберите строку в ведомости ниже. Здесь отобразятся архитектурные параметры, квартирография и проверка высотных ограничений.</p>
            </div>

            <div id="inspector-active" style="display:none; display:flex; flex-direction:column; gap:14px;">
              <div class="inspector-header">
                <div>
                  <h3 class="inspector-title" id="insp-title">Дом Д1 · Секция 1</h3>
                  <p class="inspector-subtitle" id="insp-subtitle">Марка: Рядовая 14×26м</p>
                </div>
                <span class="category-badge" id="insp-cat-badge">Рядовая</span>
              </div>

              <dl class="detail-grid">
                <div class="detail-item"><dt>Этажность</dt><dd id="insp-floors">—</dd></div>
                <div class="detail-item"><dt>Высота здания</dt><dd id="insp-height">—</dd></div>
                <div class="detail-item"><dt>Габариты фасада</dt><dd id="insp-dims">—</dd></div>
                <div class="detail-item"><dt>Пятно секции</dt><dd id="insp-footprint">—</dd></div>
                <div class="detail-item"><dt>GFA секции</dt><dd id="insp-gfa">—</dd></div>
                <div class="detail-item"><dt>Всего квартир</dt><dd id="insp-apts-count">—</dd></div>
              </dl>

              <div class="feature-box">
                <span class="feature-box-title">Квартирография данной секции</span>
                <div class="apt-bars" id="insp-apt-bars"></div>
              </div>

              <div class="feature-box">
                <span class="feature-box-title">Инженерные узлы и лифты</span>
                <p style="font-size:13px; color:var(--text);" id="insp-elevators">Лифтов: 2 шт.</p>
                <p style="font-size:12px; color:var(--secondary);" id="insp-ground">1-й этаж: Коммерческие помещения</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 3. ДЕТАЛЬНЫЙ ТЕРРИТОРИАЛЬНЫЙ БАЛАНС (РНГП) -->
      <section class="card">
        <div class="card-header">
          <h2 class="card-title">🏛️ Баланс территории и машиномест (РНГП)</h2>
          <span style="font-size:12px; color:var(--secondary);" id="balance-region-label">РНГП Самарской области</span>
        </div>
        <div class="card-body">
          <div id="balance-warnings-container" style="display:flex; flex-direction:column; gap:6px;"></div>

          <div class="sub-grid-2" style="margin-top:6px;">
            <div class="mini-stat-card">
              <span class="mini-stat-title">Обеспеченность автостоянками</span>
              <span class="mini-stat-val" id="bal-parking-req">— м/м</span>
              <span class="mini-stat-sub" id="bal-parking-sub">в т.ч. гостевых: — м/м</span>
            </div>
            <div class="mini-stat-card">
              <span class="mini-stat-title">Открытые стоянки на участке</span>
              <span class="mini-stat-val" id="bal-parking-ground">— м/м</span>
              <span class="mini-stat-sub" id="bal-parking-ground-area">— м² открытых стоянок</span>
            </div>
          </div>

          <div class="warning-banner warning-info" id="bal-parking-underground-box">
            <span>🚗</span>
            <span id="bal-parking-underground-text">Дефицит в подземный паркинг: — м/м</span>
          </div>

          <span class="filter-label" style="margin-top:8px;">Обязательные дворовые площадки по нормативу (м²):</span>
          <div class="sub-grid-4">
            <div class="mini-stat-card">
              <span class="mini-stat-title">Детские игровые</span>
              <span class="mini-stat-val" id="pl-children">— м²</span>
            </div>
            <div class="mini-stat-card">
              <span class="mini-stat-title">Спортивные площадки</span>
              <span class="mini-stat-val" id="pl-sport">— м²</span>
            </div>
            <div class="mini-stat-card">
              <span class="mini-stat-title">Отдых взрослых</span>
              <span class="mini-stat-val" id="pl-relax">— м²</span>
            </div>
            <div class="mini-stat-card">
              <span class="mini-stat-title">Хоз. цели и ТКО</span>
              <span class="mini-stat-val" id="pl-utility">— м²</span>
            </div>
          </div>

          <span class="filter-label" style="margin-top:8px;">Структура использования земельного участка:</span>
          <div class="progress-list" id="balance-progress-list"></div>
        </div>
      </section>

      <!-- 4. КВАРТИРОГРАФИЯ И МАТРИЦА СРАВНЕНИЯ ВАРИАНТОВ -->
      <section class="sub-grid-2">
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">🏠 Квартирография жилого комплекса</h3>
          </div>
          <div class="card-body">
            <div class="progress-list" id="apts-progress-list"></div>
            <div class="table-wrapper" style="margin-top:10px;">
              <table class="data-table" id="buildings-apt-table">
                <thead>
                  <tr>
                    <th>Корпус</th>
                    <th>Этажность</th>
                    <th>Студии</th>
                    <th>1к</th>
                    <th>2к</th>
                    <th>3к</th>
                    <th>Всего</th>
                    <th>GFA, м²</th>
                  </tr>
                </thead>
                <tbody id="buildings-apt-tbody"></tbody>
              </table>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <h3 class="card-title">📋 Матрица вариантов этажности</h3>
            <button class="btn btn-primary" id="btn-calc-variants">⚡ Рассчитать варианты</button>
          </div>
          <div class="card-body">
            <p style="font-size:12px; color:var(--secondary);">Сравнение сценариев высотности от 8 до 24 этажей с проверкой лимитов плотности FAR и КЗ (BCR):</p>
            <div class="table-wrapper">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Этажность</th>
                    <th>GFA, м²</th>
                    <th>Жил.пл.</th>
                    <th>Квартир</th>
                    <th>BCR</th>
                    <th>FAR</th>
                    <th>Нормы</th>
                  </tr>
                </thead>
                <tbody id="variants-table-body">
                  <tr><td colspan="7" style="text-align:center; color:var(--secondary); padding:24px;">Нажмите кнопку «Рассчитать варианты», чтобы сформировать сравнение.</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      <!-- 5. КАТАЛОГ СЕКЦИЙ -->
      <section class="card">
        <div class="card-header">
          <h3 class="card-title">📦 Библиотека типовых секций ({len(catalog)} типов в каталоге)</h3>
          <span style="font-size:12px; color:var(--secondary);">Параметрические секции жилых корпусов</span>
        </div>
        <div class="card-body">
          <div class="sections-catalog-grid" id="catalog-grid"></div>
        </div>
      </section>

      <!-- 6. ВЕДОМОСТЬ СЕКЦИЙ И ЭКСПОРТ -->
      <section class="card">
        <div class="card-header">
          <h3 class="card-title">Ведомость жилых корпусов и секций</h3>
          <div class="export-buttons">
            <a class="btn" id="btn-export-dxf" href="/api/export/dxf" download="plan_cad.dxf">📐 Скачать DXF (AutoCAD)</a>
            <a class="btn" id="btn-export-3d" href="/api/export/3d-html" download="plan_3d.html">🏙️ Скачать 3D (HTML)</a>
            <a class="btn" id="btn-export-geojson" href="/api/export/geojson" download="plan.geojson">💾 Скачать GeoJSON</a>
            <button class="btn btn-primary" id="btn-show-report">📄 Просмотр отчёта</button>
          </div>
        </div>

        <div class="card-body">
          <div class="table-toolbar">
            <input type="text" class="search-input" id="table-search" placeholder="🔍 Поиск по дому, марке или категории секции..." />
            <span style="font-size:12px; color:var(--secondary);" id="table-count-label">Показано 26 секций</span>
          </div>

          <div class="table-wrapper">
            <table class="data-table">
              <thead>
                <tr>
                  <th>Маркировка</th>
                  <th>Корпус</th>
                  <th>Категория</th>
                  <th>Марка секции</th>
                  <th>Этажность</th>
                  <th>Высота (м)</th>
                  <th>Пятно (м²)</th>
                  <th>GFA (м²)</th>
                  <th>Квартир</th>
                </tr>
              </thead>
              <tbody id="table-sections-body"></tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- ПОДВАЛ -->
      <footer class="method-footer">
        <strong>Методика расчёта:</strong> ТЭП и градостроительный баланс сформированы по алгоритмам СП 42.13330.2016 «Градостроительство» и региональным нормативам градостроительного проектирования (РНГП). Норма расчетной площади на человека — 30 м² жилой площади. Нормативное машиноместо открытой автостоянки — 25 м² (с учетом маневрирования и проездов).
      </footer>

    </main>
  </div>

  <!-- МОДАЛЬНОЕ ОКНО ОТЧЕТА -->
  <div class="modal-backdrop" id="report-modal">
    <div class="modal-box">
      <div class="modal-header">
        <strong style="font-size:15px; color:var(--text);">📄 Текстовый отчёт ТЭП и баланса территории</strong>
        <button class="modal-close" id="modal-close-btn">&times;</button>
      </div>
      <div class="modal-body" id="modal-report-text">Загрузка отчёта...</div>
    </div>
  </div>

  <!-- МОДАЛЬНОЕ ОКНО СПРАВКИ О ЛОКАЛЬНОМ БЭКЕНДЕ -->
  <div class="modal-backdrop" id="backend-modal">
    <div class="modal-box" style="max-width: 620px;">
      <div class="modal-header">
        <strong style="font-size:16px; color:var(--text); display:flex; align-items:center; gap:8px;">
          <span>⚙️</span> Локальный Python-сервер генератора
        </strong>
        <button class="modal-close" id="backend-modal-close">&times;</button>
      </div>
      <div class="modal-body" style="font-family: var(--font-sans); font-size: 13.5px; line-height: 1.6; white-space: normal; padding: 22px;">
        <div style="margin-bottom: 14px;">
          Дашборд открыт как локальный файл (<code>file://</code>) или сервер остановлен.
        </div>
        <div style="background:rgba(83, 141, 178, 0.08); border-left: 4px solid var(--accent); padding: 12px 16px; border-radius: 0 var(--radius-sm) var(--radius-sm) 0; margin-bottom: 16px;">
          <strong>Для чего нужен Python-сервер?</strong><br>
          Для расчёта генерации застройки, оптимизации ТЭП, разметки геометрии и чтения DWG/DXF на лету задействуются расчётные алгоритмы бэкенда.
        </div>
        <div style="margin-bottom: 16px;">
          <strong>Как запустить расчёт «на лету» в 1 шаг:</strong>
          <ol style="margin-left: 20px; margin-top: 8px;">
            <li>В папке проекта откройте директорию <code>dashboard_prototype</code>.</li>
            <li>Запустите файл <strong><code>run_dashboard.bat</code></strong> (двойным кликом).</li>
            <li>Откроется веб-интерфейс по адресу <strong>http://127.0.0.1:8050/</strong>.</li>
          </ol>
        </div>
        <div style="display:flex; justify-content: flex-end; gap: 10px; margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border);">
          <button class="btn" id="btn-backend-modal-ok">Понятно</button>
          <a class="btn btn-primary" href="http://127.0.0.1:8050/" target="_blank" style="text-decoration:none;">Открыть http://127.0.0.1:8050 ↗</a>
        </div>
      </div>
    </div>
  </div>

  <div class="toast-msg" id="toast-msg"></div>

  <script type="application/json" id="scenarios-data">{data_json_str}</script>
  <script type="application/json" id="catalog-data">{catalog_json_str}</script>

  <!-- КЛИЕНТСКИЙ СКРИПТ -->
  <script>
    (function() {{
      "use strict";

      const SCENARIOS = JSON.parse(document.getElementById("scenarios-data").textContent);
      const CATALOG = JSON.parse(document.getElementById("catalog-data").textContent);

      let currentScenario = SCENARIOS[0];
      let selectedSectionId = null;
      let activeMetric = "category";
      let activeView = "osm";
      let preferredSectionIds = [];
      let siteMode = "cadastre"; // 'cadastre' или 'cad'

      // Состояние 2-этапного взаимодействия (Посадка -> Застройка)
      let isSiteLocked = false;
      let currentRotation = 0;
      let currentSiteLat = (currentScenario.geo_center && currentScenario.geo_center.lat) || 53.2502;
      let currentSiteLon = (currentScenario.geo_center && currentScenario.geo_center.lon) || 50.3184;
      let userHasMovedSite = false;

      // Элементы степпера и баннеров этапов
      const stepperStep1 = document.getElementById("stepper-step-1");
      const stepperStep2 = document.getElementById("stepper-step-2");
      const stepperNum1 = document.getElementById("stepper-num-1");
      const stepperNum2 = document.getElementById("stepper-num-2");
      const stageBanner1 = document.getElementById("stage-banner-1");
      const stageBanner2 = document.getElementById("stage-banner-2");
      const stage2StatusDesc = document.getElementById("stage-2-status-desc");
      const btnLockMain = document.getElementById("btn-lock-main");
      const btnResetRotMain = document.getElementById("btn-reset-rot-main");
      const btnUnlockMain = document.getElementById("btn-unlock-main");
      const btnLockSidebar = document.getElementById("btn-lock-sidebar");
      const btnUnlockSidebar = document.getElementById("btn-unlock-sidebar");
      const sidebarStage2Group = document.getElementById("sidebar-stage2-group");
      const sidebarLockNotice = document.getElementById("sidebar-lock-notice");
      const cfgBoundarySetback = document.getElementById("cfg-boundary-setback");
      const cfgRedlineSetback = document.getElementById("cfg-redline-setback");

      // Хранилище загруженного CAD файла (base64)
      let uploadedCadBase64 = null;
      let uploadedCadFilename = null;

      // SVG навигация
      let view = {{ zoom: 1, x: 0, y: 0 }};
      let isDragging = false;
      let dragStart = {{ x: 0, y: 0 }};

      // Шапка
      const siteCadLabel = document.getElementById("site-cad-label");
      const siteRegionLabel = document.getElementById("site-region-label");
      const siteCoordsLabel = document.getElementById("site-coords-label");
      const linkYandex = document.getElementById("link-yandex");
      const linkPkk = document.getElementById("link-pkk");

      // Сайдбар
      const settingsDrawer = document.getElementById("settings-drawer");
      const btnToggleSidebar = document.getElementById("btn-toggle-sidebar");
      const btnRunPipeline = document.getElementById("btn-run-pipeline");

      // Переключатель режима задания участка
      const btnModeCadastre = document.getElementById("btn-mode-cadastre");
      const btnModeCad = document.getElementById("btn-mode-cad");
      const containerModeCadastre = document.getElementById("container-mode-cadastre");
      const containerModeCad = document.getElementById("container-mode-cad");

      // Поля режима 1 (Кадастр)
      const cfgParcelPresets = document.getElementById("cfg-parcel-presets");
      const cfgCadInput = document.getElementById("cfg-cad-input");
      const cfgRotSlider = document.getElementById("cfg-rot-slider");
      const cfgRotBadge = document.getElementById("cfg-rot-badge");
      const cfgAreaInput = document.getElementById("cfg-area-input");
      const cfgManualLat = document.getElementById("cfg-manual-lat");
      const cfgManualLon = document.getElementById("cfg-manual-lon");
      const cfgRedlineToggle = document.getElementById("cfg-redline-toggle");
      const dropzoneCadSub = document.getElementById("dropzone-cad-sub");
      const fileCadSub = document.getElementById("file-cad-sub");
      const cadSubBadge = document.getElementById("cad-sub-badge");

      // Поля режима 2 (CAD чертеж)
      const dropzoneCadMain = document.getElementById("dropzone-cad-main");
      const fileCadMain = document.getElementById("file-cad-main");
      const cadMainBadge = document.getElementById("cad-main-badge");
      const cfgDwgAssignedCad = document.getElementById("cfg-dwg-assigned-cad");
      const cadLayersContainer = document.getElementById("cad-layers-container");
      const cfgBoundaryLayer = document.getElementById("cfg-boundary-layer");
      const cfgRedlineLayer = document.getElementById("cfg-redline-layer");
      const cfgDwgLat = document.getElementById("cfg-dwg-lat");
      const cfgDwgLon = document.getElementById("cfg-dwg-lon");

      // Общие поля
      const cfgTypology = document.getElementById("cfg-typology");
      const containerPeriSettings = document.getElementById("container-peri-settings");
      const cfgPeriStyle = document.getElementById("cfg-peri-style");
      const cfgPeriBlockSize = document.getElementById("cfg-peri-block-size");
      const badgePeriBlockSize = document.getElementById("badge-peri-block-size");
      const cfgPeriRoadWidth = document.getElementById("cfg-peri-road-width");
      const badgePeriRoadWidth = document.getElementById("badge-peri-road-width");
      const cfgCourtOrient = document.getElementById("cfg-court-orient");
      const cfgTowersMixed = document.getElementById("cfg-towers-mixed");
      const cfgVarInsolation = document.getElementById("cfg-var-insolation");
      const cfgGenMode = document.getElementById("cfg-gen-mode");
      const cfgTargetContainer = document.getElementById("cfg-target-tep-container");
      const cfgTargetMetric = document.getElementById("cfg-target-metric");
      const cfgTargetVal = document.getElementById("cfg-target-val");
      const cfgFloorsSlider = document.getElementById("cfg-floors-slider");
      const cfgFloorsBadge = document.getElementById("cfg-floors-badge");
      const cfgCascadeFloors = document.getElementById("cfg-cascade-floors");
      const cfgAsymmetricWings = document.getElementById("cfg-asymmetric-wings");
      const cfgFloorH = document.getElementById("cfg-floor-h");
      const cfgMaxH = document.getElementById("cfg-max-h");
      const cfgMaxSectionsSlider = document.getElementById("cfg-max-sections-slider");
      const cfgMaxSectionsBadge = document.getElementById("cfg-max-sections-badge");
      const cfgRegionalNorm = document.getElementById("cfg-regional-norm");
      const cfgFarSlider = document.getElementById("cfg-far-slider");
      const cfgFarBadge = document.getElementById("cfg-far-badge");
      const cfgBcrSlider = document.getElementById("cfg-bcr-slider");
      const cfgBcrBadge = document.getElementById("cfg-bcr-badge");
      const prefSectionsContainer = document.getElementById("pref-sections-container");
      const prefCountHint = document.getElementById("pref-count-hint");

      // 10 КАРТОЧЕК KPI
      const kpiGfa = document.getElementById("kpi-gfa");
      const kpiGfaDesc = document.getElementById("kpi-gfa-desc");
      const kpiGfaBadge = document.getElementById("kpi-gfa-badge");

      const kpiLiving = document.getElementById("kpi-living");
      const kpiLivingDesc = document.getElementById("kpi-living-desc");
      const kpiLivingBadge = document.getElementById("kpi-living-badge");

      const kpiFar = document.getElementById("kpi-far");
      const kpiFarDesc = document.getElementById("kpi-far-desc");
      const kpiFarBadge = document.getElementById("kpi-far-badge");

      const kpiBcr = document.getElementById("kpi-bcr");
      const kpiBcrDesc = document.getElementById("kpi-bcr-desc");
      const kpiBcrBadge = document.getElementById("kpi-bcr-badge");

      const kpiComm = document.getElementById("kpi-comm");
      const kpiCommDesc = document.getElementById("kpi-comm-desc");
      const kpiCommBadge = document.getElementById("kpi-comm-badge");

      const kpiPop = document.getElementById("kpi-pop");
      const kpiPopDesc = document.getElementById("kpi-pop-desc");
      const kpiPopBadge = document.getElementById("kpi-pop-badge");

      const kpiParking = document.getElementById("kpi-parking");
      const kpiParkingDesc = document.getElementById("kpi-parking-desc");
      const kpiParkingBadge = document.getElementById("kpi-parking-badge");

      const kpiGreen = document.getElementById("kpi-green");
      const kpiGreenDesc = document.getElementById("kpi-green-desc");
      const kpiGreenBadge = document.getElementById("kpi-green-badge");

      const kpiPlaygrounds = document.getElementById("kpi-playgrounds");
      const kpiPlaygroundsDesc = document.getElementById("kpi-playgrounds-desc");
      const kpiPlaygroundsBadge = document.getElementById("kpi-playgrounds-badge");

      const kpiMorphology = document.getElementById("kpi-morphology");
      const kpiMorphologyDesc = document.getElementById("kpi-morphology-desc");
      const kpiMorphologyBadge = document.getElementById("kpi-morphology-badge");

      // Бэкенд и модалки
      const API_BASE = window.location.protocol.startsWith("http") ? "" : "http://127.0.0.1:8050";
      const backendStatusBadge = document.getElementById("backend-status-badge");
      const backendStatusText = document.getElementById("backend-status-text");
      const backendModal = document.getElementById("backend-modal");
      const backendModalClose = document.getElementById("backend-modal-close");
      const btnBackendModalOk = document.getElementById("btn-backend-modal-ok");

      // SVG
      const mapMetricSelect = document.getElementById("map-metric-select");
      const svgRoot = document.getElementById("masterplan-svg");
      const svgViewport = document.getElementById("svg-viewport");
      const svgSiteBound = document.getElementById("svg-site-bound");
      const svgBuildable = document.getElementById("svg-buildable");
      const svgRedlinesGroup = document.getElementById("svg-redlines-group");
      const svgSectionsGroup = document.getElementById("svg-sections-group");
      const mapTooltip = document.getElementById("map-tooltip");
      const mapLegendTitle = document.getElementById("legend-title");
      const mapLegendItems = document.getElementById("legend-items");

      // Инспектор
      const inspectorEmpty = document.getElementById("inspector-empty");
      const inspectorActive = document.getElementById("inspector-active");
      const btnClearSelection = document.getElementById("btn-clear-selection");
      const inspTitle = document.getElementById("insp-title");
      const inspSubtitle = document.getElementById("insp-subtitle");
      const inspCatBadge = document.getElementById("insp-cat-badge");
      const inspFloors = document.getElementById("insp-floors");
      const inspHeight = document.getElementById("insp-height");
      const inspDims = document.getElementById("insp-dims");
      const inspFootprint = document.getElementById("insp-footprint");
      const inspGfa = document.getElementById("insp-gfa");
      const inspAptsCount = document.getElementById("insp-apts-count");
      const inspAptBars = document.getElementById("insp-apt-bars");
      const inspElevators = document.getElementById("insp-elevators");
      const inspGround = document.getElementById("insp-ground");

      // Баланс
      const balRegionLabel = document.getElementById("balance-region-label");
      const balWarningsContainer = document.getElementById("balance-warnings-container");
      const balParkingReq = document.getElementById("bal-parking-req");
      const balParkingSub = document.getElementById("bal-parking-sub");
      const balParkingGround = document.getElementById("bal-parking-ground");
      const balParkingGroundArea = document.getElementById("bal-parking-ground-area");
      const balParkingUndergroundBox = document.getElementById("bal-parking-underground-box");
      const balParkingUndergroundText = document.getElementById("bal-parking-underground-text");
      const plChildren = document.getElementById("pl-children");
      const plSport = document.getElementById("pl-sport");
      const plRelax = document.getElementById("pl-relax");
      const plUtility = document.getElementById("pl-utility");
      const balanceProgressList = document.getElementById("balance-progress-list");

      // Таблицы
      const buildingsAptTbody = document.getElementById("buildings-apt-tbody");
      const variantsTableBody = document.getElementById("variants-table-body");
      const btnCalcVariants = document.getElementById("btn-calc-variants");
      const catalogGrid = document.getElementById("catalog-grid");
      const tableBody = document.getElementById("table-sections-body");
      const tableSearch = document.getElementById("table-search");
      const tableCountLabel = document.getElementById("table-count-label");

      // Модалка
      const reportModal = document.getElementById("report-modal");
      const btnShowReport = document.getElementById("btn-show-report");
      const modalCloseBtn = document.getElementById("modal-close-btn");
      const modalReportText = document.getElementById("modal-report-text");

      const fmt = (n, digits = 0) => Number.isFinite(n) ? new Intl.NumberFormat("ru-RU", {{ maximumFractionDigits: digits }}).format(n) : "—";

      const CATEGORY_COLORS = {{
        "MIDDLE": "#538db2",
        "CORNER": "#c5a35b",
        "END": "#8d9f6b",
        "TOWER": "#924ff7"
      }};

      const BUILDING_PALETTE = ["#538db2", "#8d9f6b", "#c5a35b", "#924ff7", "#ce8c68", "#798392", "#00a240", "#3b82f6"];

      function showToast(msg, isWarn = false) {{
        const toast = document.getElementById("toast-msg");
        toast.textContent = msg;
        toast.style.borderColor = isWarn ? "var(--warning)" : "var(--accent)";
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 3500);
      }}

      // Управление статусом бэкенда и модалкой справки
      function updateBackendBadge(isOnline) {{
        if (!backendStatusBadge) return;
        backendStatusBadge.className = `backend-badge ${{isOnline ? "online" : "offline"}}`;
        backendStatusText.textContent = isOnline ? "🟢 Бэкенд онлайн" : "🟠 Офлайн · Нужен run_dashboard.bat";
      }}

      function openBackendModal() {{
        if (backendModal) backendModal.style.display = "flex";
      }}
      function closeBackendModal() {{
        if (backendModal) backendModal.style.display = "none";
      }}

      if (backendStatusBadge) backendStatusBadge.addEventListener("click", openBackendModal);
      if (backendModalClose) backendModalClose.addEventListener("click", closeBackendModal);
      if (btnBackendModalOk) btnBackendModalOk.addEventListener("click", closeBackendModal);
      if (backendModal) {{
        backendModal.addEventListener("click", e => {{
          if (e.target === backendModal) closeBackendModal();
        }});
      }}

      async function checkBackendHealth() {{
        try {{
          const resp = await fetch(API_BASE + "/api/health");
          if (resp.ok) {{
            updateBackendBadge(true);
            return true;
          }}
        }} catch (e) {{}}
        updateBackendBadge(false);
        return false;
      }}

      // Переключение режимов задания участка (Кадастр / CAD)
      btnModeCadastre.addEventListener("click", () => {{
        siteMode = "cadastre";
        btnModeCadastre.classList.add("active");
        btnModeCad.classList.remove("active");
        containerModeCadastre.style.display = "flex";
        containerModeCad.style.display = "none";
      }});

      btnModeCad.addEventListener("click", () => {{
        siteMode = "cad";
        btnModeCad.classList.add("active");
        btnModeCadastre.classList.remove("active");
        containerModeCadastre.style.display = "none";
        containerModeCad.style.display = "flex";
      }});

      // Загрузка CAD файла в режиме 1 (Прикрепление контура)
      dropzoneCadSub.addEventListener("click", () => fileCadSub.click());
      fileCadSub.addEventListener("change", e => {{
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = async () => {{
          uploadedCadBase64 = reader.result.split(",")[1];
          uploadedCadFilename = file.name;
          userHasMovedSite = false;
          currentSiteLat = null;
          currentSiteLon = null;
          if (cfgManualLat) cfgManualLat.value = "";
          if (cfgManualLon) cfgManualLon.value = "";
          cadSubBadge.style.display = "inline-flex";
          cadSubBadge.className = "file-badge";
          cadSubBadge.textContent = `✓ Прикреплен контур: ${{file.name}}`;
          showToast(`Контур ${{file.name}} прикреплен к участку`);
          isSiteLocked = false;
          loadSitePreview(true);
        }};
        reader.readAsDataURL(file);
      }});

      // Клиентский парсер слоев DXF (работает 100% автономно в браузере)
      function parseDxfLayersClientSide(dxfText) {{
        const layersMap = new Map();
        const cleanText = dxfText.replace(new RegExp(String.fromCharCode(13), "g"), "");
        const lines = cleanText.split(String.fromCharCode(10));
        for (let i = 0; i < lines.length - 1; i++) {{
          const code = lines[i].trim();
          if (code === "8") {{
            const layerName = lines[i + 1].trim();
            if (layerName && layerName.length > 0 && layerName.length < 100) {{
              layersMap.set(layerName, (layersMap.get(layerName) || 0) + 1);
            }}
            i++;
          }}
        }}
        const layers = [];
        layersMap.forEach((count, name) => {{
          const lower = name.toLowerCase();
          const isBound = lower.includes("границ") || lower.includes("участ") || lower.includes("bound") || lower.includes("cadastre") || lower.includes("земл");
          const isRed = lower.includes("красн") || lower.includes("red");
          layers.push({{
            name: name,
            total_entities: count,
            is_candidate: isBound,
            is_red_line_candidate: isRed
          }});
        }});
        layers.sort((a, b) => (b.is_candidate ? 1 : 0) - (a.is_candidate ? 1 : 0));
        return layers;
      }}

      // Загрузка CAD файла в режиме 2 (Чертёж генплана)
      dropzoneCadMain.addEventListener("click", () => fileCadMain.click());
      fileCadMain.addEventListener("change", e => {{
        const file = e.target.files[0];
        if (!file) return;
        const filename = file.name;
        const isDwg = filename.toLowerCase().endsWith(".dwg");

        if (isDwg) {{
          cadMainBadge.style.display = "flex";
          cadMainBadge.className = "file-badge badge-warn";
          cadMainBadge.innerHTML = `⚠️ Файл .DWG (${{file.name}}) — закрытый бинарный формат. Для мгновенного чтения слоёв сохраните чертёж как .DXF (в AutoCAD команда <code>DXFOUT</code>).`;
          showToast(`⚠️ Для чтения слоёв выберите файл .DXF (в AutoCAD: команда DXFOUT)`, true);
          return;
        }}

        // Мгновенное автономное чтение слоев DXF на стороне клиента
        const reader = new FileReader();
        reader.onload = () => {{
          const text = reader.result;
          const layers = parseDxfLayersClientSide(text);
          if (layers.length > 0) {{
            populateCadLayers(layers);
            cadMainBadge.style.display = "inline-flex";
            cadMainBadge.className = "file-badge";
            cadMainBadge.textContent = `✓ DXF загружен: ${{file.name}} (слоев: ${{layers.length}})`;
            showToast(`✓ Чертёж ${{file.name}} загружен: найдено ${{layers.length}} слоёв`);
          }} else {{
            showToast(`В файле ${{file.name}} не обнаружено слоев`, true);
          }}

          // Подготавливаем base64 для бэкенда и сразу обновляем предпросмотр
          const b64Reader = new FileReader();
          b64Reader.onload = () => {{
            uploadedCadBase64 = b64Reader.result.split(",")[1];
            uploadedCadFilename = file.name;
            userHasMovedSite = false;
            currentSiteLat = null;
            currentSiteLon = null;
            if (cfgDwgLat) cfgDwgLat.value = "";
            if (cfgDwgLon) cfgDwgLon.value = "";
            isSiteLocked = false;
            loadSitePreview(true);
          }};
          b64Reader.readAsDataURL(file);
        }};
        reader.readAsText(file);
      }});

      function populateCadLayers(layers) {{
        cadLayersContainer.style.display = "flex";
        cfgBoundaryLayer.innerHTML = "";
        cfgRedlineLayer.innerHTML = '<option value="">(нет красных линий)</option>';

        layers.forEach(l => {{
          const opt1 = document.createElement("option");
          opt1.value = l.name;
          opt1.textContent = `${{l.name}} (${{l.total_entities}} примитивов)`;
          if (l.is_candidate) opt1.selected = true;
          cfgBoundaryLayer.appendChild(opt1);

          const opt2 = document.createElement("option");
          opt2.value = l.name;
          opt2.textContent = `${{l.name}} (${{l.total_entities}} примитивов)`;
          if (l.is_red_line_candidate) opt2.selected = true;
          cfgRedlineLayer.appendChild(opt2);
        }});
      }}

      // Слушатели смены слоев CAD
      cfgBoundaryLayer.addEventListener("change", () => {{
        if (!isSiteLocked) loadSitePreview(false);
      }});
      cfgRedlineLayer.addEventListener("change", () => {{
        if (!isSiteLocked) loadSitePreview(false);
      }});

      // Слушатели параметров участка
      if (cfgBoundarySetback) {{
        cfgBoundarySetback.addEventListener("input", () => {{
          if (!isSiteLocked) onSidebarRotationChange();
        }});
      }}
      if (cfgRedlineSetback) {{
        cfgRedlineSetback.addEventListener("input", () => {{
          if (!isSiteLocked) onSidebarRotationChange();
        }});
      }}
      if (cfgAreaInput) {{
        cfgAreaInput.addEventListener("change", () => {{
          if (!isSiteLocked) loadSitePreview(false);
        }});
      }}
      if (cfgRedlineToggle) {{
        cfgRedlineToggle.addEventListener("change", () => {{
          if (!isSiteLocked) loadSitePreview(false);
        }});
      }}

      // Урбан-блоки R2
      if (cfgTypology && containerPeriSettings) {{
        cfgTypology.addEventListener("change", () => {{
          containerPeriSettings.style.display = cfgTypology.value === "PERIMETER" ? "flex" : "none";
        }});
      }}
      if (cfgPeriBlockSize && badgePeriBlockSize) {{
        cfgPeriBlockSize.addEventListener("input", (e) => {{
          badgePeriBlockSize.textContent = e.target.value + " м";
        }});
      }}
      if (cfgPeriRoadWidth && badgePeriRoadWidth) {{
        cfgPeriRoadWidth.addEventListener("input", (e) => {{
          badgePeriRoadWidth.textContent = e.target.value + " м";
        }});
      }}

      // Тоггл панели параметров
      btnToggleSidebar.addEventListener("click", () => {{
        const isCollapsed = settingsDrawer.classList.toggle("collapsed");
        btnToggleSidebar.classList.toggle("active", !isCollapsed);
      }});

      // Управление поворотом участка (живое вращение в реальном времени)
      let rotDebounceTimer = null;

      function onSidebarRotationChange() {{
        if (!isSiteLocked) {{
          clearTimeout(rotDebounceTimer);
          rotDebounceTimer = setTimeout(() => {{
            loadSitePreview();
          }}, 300);
        }}
      }}

      function setRotation(angle, updateSliderInput = true, syncIframe = false) {{
        currentRotation = (Math.round(angle) % 360 + 360) % 360;
        if (updateSliderInput && cfgRotSlider) {{
          cfgRotSlider.value = currentRotation;
        }}
        if (cfgRotBadge) {{
          cfgRotBadge.textContent = `${{currentRotation}}°`;
        }}

        // Визуальное вращение мира SVG вокруг центра участка
        const baseRot = currentScenario.site_rotation || 0;
        const visualDelta = currentRotation - baseRot;

        const world = document.getElementById("svg-site-world");
        if (world) {{
          world.setAttribute("transform", `rotate(${{visualDelta}}, 500, 350)`);
        }}

        // Стрелка севера вращается в противоход
        const northArrow = document.querySelector(".north-arrow");
        if (northArrow) {{
          northArrow.style.transform = `rotate(${{-currentRotation}}deg)`;
        }}

        currentScenario.site_rotation = currentRotation;

        if (syncIframe) {{
          onSidebarRotationChange();
        }}
      }}

      document.querySelectorAll(".btn-rot").forEach(btn => {{
        btn.addEventListener("click", () => {{
          if (btn.hasAttribute("data-reset")) {{
            setRotation(0, true, true);
          }} else {{
            const step = parseInt(btn.getAttribute("data-step"), 10) || 0;
            const cur = parseInt(cfgRotSlider.value, 10) || 0;
            setRotation(cur + step, true, true);
          }}
        }});
      }});

      cfgRotSlider.addEventListener("input", e => {{
        setRotation(parseInt(e.target.value, 10) || 0, false, true);
      }});

      cfgFloorsSlider.addEventListener("input", e => cfgFloorsBadge.textContent = `${{e.target.value}} эт.`);
      cfgMaxSectionsSlider.addEventListener("input", e => cfgMaxSectionsBadge.textContent = e.target.value);
      cfgFarSlider.addEventListener("input", e => cfgFarBadge.textContent = Number(e.target.value).toFixed(2));
      cfgBcrSlider.addEventListener("input", e => cfgBcrBadge.textContent = `${{Math.round(e.target.value * 100)}}%`);

      // Переключение пресетов участков (автоматически сбрасывает на Шаг 1)
      cfgParcelPresets.addEventListener("change", e => {{
        const cadNum = e.target.value;
        cfgCadInput.value = cadNum;
        userHasMovedSite = false;
        currentSiteLat = null;
        currentSiteLon = null;
        if (cfgManualLat) cfgManualLat.value = "";
        if (cfgManualLon) cfgManualLon.value = "";
        isSiteLocked = false;
        setRotation(0, true, false);
        loadSitePreview(true);
        showToast(`✓ Пресет выбран: ${{cadNum}} (Этап 1: настройте положение)`);
      }});

      // Изменение кадастрового номера в режиме 1
      cfgCadInput.addEventListener("change", () => {{
        userHasMovedSite = false;
        currentSiteLat = null;
        currentSiteLon = null;
        if (cfgManualLat) cfgManualLat.value = "";
        if (cfgManualLon) cfgManualLon.value = "";
        isSiteLocked = false;
        loadSitePreview(true);
      }});

      // Изменение кадастрового номера / региона в режиме 2
      if (cfgDwgAssignedCad) {{
        cfgDwgAssignedCad.addEventListener("change", () => {{
          userHasMovedSite = false;
          currentSiteLat = null;
          currentSiteLon = null;
          if (cfgDwgLat) cfgDwgLat.value = "";
          if (cfgDwgLon) cfgDwgLon.value = "";
          isSiteLocked = false;
          loadSitePreview(true);
        }});
      }}

      // Изменение ручных координат
      if (cfgManualLat) cfgManualLat.addEventListener("change", () => {{ userHasMovedSite = true; loadSitePreview(false); }});
      if (cfgManualLon) cfgManualLon.addEventListener("change", () => {{ userHasMovedSite = true; loadSitePreview(false); }});
      if (cfgDwgLat) cfgDwgLat.addEventListener("change", () => {{ userHasMovedSite = true; loadSitePreview(false); }});
      if (cfgDwgLon) cfgDwgLon.addEventListener("change", () => {{ userHasMovedSite = true; loadSitePreview(false); }});

      cfgGenMode.addEventListener("change", e => {{
        cfgTargetContainer.style.display = e.target.value === "target" ? "flex" : "none";
      }});

      // Чипсы секций
      function renderPrefSectionChips() {{
        prefSectionsContainer.innerHTML = "";
        CATALOG.forEach(s => {{
          const chip = document.createElement("span");
          chip.className = "section-chip";
          chip.textContent = `${{s.name}} (${{s.width}}×${{s.depth}}м)`;
          chip.setAttribute("data-id", s.id);
          chip.addEventListener("click", () => {{
            chip.classList.toggle("selected");
            updatePreferredSections();
          }});
          prefSectionsContainer.appendChild(chip);
        }});
      }}

      function updatePreferredSections() {{
        preferredSectionIds = Array.from(prefSectionsContainer.querySelectorAll(".section-chip.selected")).map(c => c.getAttribute("data-id"));
        prefCountHint.textContent = preferredSectionIds.length ? `Выбрано: ${{preferredSectionIds.length}}` : "Все типы";
      }}

      function renderCatalogCards() {{
        catalogGrid.innerHTML = "";
        CATALOG.forEach(s => {{
          const card = document.createElement("div");
          card.className = "catalog-item-card";
          card.innerHTML = `
            <div class="catalog-item-header">
              <div>
                <div class="catalog-item-name">${{s.name}}</div>
                <div class="catalog-item-code">${{s.code}} · ${{s.category_name}}</div>
              </div>
              <span class="category-badge" style="background:${{CATEGORY_COLORS[s.category] || '#798392'}}">${{s.category}}</span>
            </div>
            <div style="font-size:12px; color:var(--secondary); display:grid; grid-template-columns:1fr 1fr; gap:4px; margin-top:4px;">
              <div>Габариты: <strong style="color:var(--text);">${{s.width}} × ${{s.depth}} м</strong></div>
              <div>Пятно этажа: <strong style="color:var(--text);">${{s.floor_area}} м²</strong></div>
              <div>Этажность: <strong style="color:var(--text);">${{s.min_floors}}–${{s.max_floors}} эт.</strong></div>
              <div>Лифты: <strong style="color:var(--text);">${{s.elevators}} шт.</strong></div>
              <div>Квартир/этаж: <strong style="color:var(--text);">${{s.total_apartments_per_floor}} шт.</strong></div>
              <div>1-й этаж комм.: <strong style="color:var(--text);">${{s.has_commercial_ground ? 'Да' : 'Нет'}}</strong></div>
            </div>
          `;
          catalogGrid.appendChild(card);
        }});
      }}

      mapMetricSelect.addEventListener("change", e => {{
        activeMetric = e.target.value;
        updateSectionsColoring();
        updateLegend();
      }});

      // Тема
      const themeBtn = document.getElementById("theme-btn");
      themeBtn.addEventListener("click", () => {{
        const isDark = document.body.getAttribute("data-theme") === "dark";
        document.body.setAttribute("data-theme", isDark ? "light" : "dark");
        themeBtn.textContent = isDark ? "🌙 Тема" : "☀️ Тема";
      }});

      // Вкладки видов
      const tabSvg = document.getElementById("tab-svg");
      const tabOsm = document.getElementById("tab-osm");
      const tab3d = document.getElementById("tab-3d");
      const viewSvg = document.getElementById("view-container-svg");
      const viewOsm = document.getElementById("view-container-osm");
      const view3d = document.getElementById("view-container-3d");
      const svgControls = document.getElementById("svg-controls");

      function setViewTab(tab) {{
        activeView = tab;
        tabSvg.classList.toggle("active", tab === "svg");
        tabOsm.classList.toggle("active", tab === "osm");
        tab3d.classList.toggle("active", tab === "3d");

        viewSvg.style.display = tab === "svg" ? "block" : "none";
        viewOsm.style.display = tab === "osm" ? "block" : "none";
        view3d.style.display = tab === "3d" ? "block" : "none";
        svgControls.style.display = tab === "svg" ? "flex" : "none";

        if (tab === "osm") {{
          const iframeOsm = viewOsm.querySelector("iframe");
          if (iframeOsm && currentScenario.leaflet_html && (!iframeOsm.srcdoc || iframeOsm.srcdoc !== currentScenario.leaflet_html)) {{
            iframeOsm.srcdoc = currentScenario.leaflet_html;
          }}
        }}
        if (tab === "3d") {{
          const iframe3d = view3d.querySelector("iframe");
          if (iframe3d) {{
            if (currentScenario.viewer_3d_html && iframe3d.srcdoc !== currentScenario.viewer_3d_html) {{
              iframe3d.srcdoc = currentScenario.viewer_3d_html;
            }}
            setTimeout(() => {{
              try {{
                iframe3d.contentWindow.dispatchEvent(new Event("resize"));
                iframe3d.contentWindow.postMessage({{ type: "resize" }}, "*");
              }} catch (_) {{}}
            }}, 80);
          }}
        }}
      }}

      tabSvg.addEventListener("click", () => setViewTab("svg"));
      tabOsm.addEventListener("click", () => setViewTab("osm"));
      tab3d.addEventListener("click", () => setViewTab("3d"));

      // Сбор данных формы
      function getFormData() {{
        let sendOverrideLat = 0.0;
        let sendOverrideLon = 0.0;
        if (siteMode === "cadastre") {{
          const mLat = parseFloat(cfgManualLat ? cfgManualLat.value : "") || 0;
          const mLon = parseFloat(cfgManualLon ? cfgManualLon.value : "") || 0;
          if (mLat !== 0 && mLon !== 0) {{
            sendOverrideLat = mLat;
            sendOverrideLon = mLon;
          }} else if (userHasMovedSite && currentSiteLat && currentSiteLon) {{
            sendOverrideLat = currentSiteLat;
            sendOverrideLon = currentSiteLon;
          }}
        }} else {{
          const dLat = parseFloat(cfgDwgLat ? cfgDwgLat.value : "") || 0;
          const dLon = parseFloat(cfgDwgLon ? cfgDwgLon.value : "") || 0;
          if (dLat !== 0 && dLon !== 0) {{
            sendOverrideLat = dLat;
            sendOverrideLon = dLon;
          }} else if (userHasMovedSite && currentSiteLat && currentSiteLon) {{
            sendOverrideLat = currentSiteLat;
            sendOverrideLon = currentSiteLon;
          }}
        }}

        const base = {{
          site_mode: siteMode,
          site_rotation: currentRotation,
          override_lat: sendOverrideLat,
          override_lon: sendOverrideLon,
          boundary_setback: parseFloat(cfgBoundarySetback ? cfgBoundarySetback.value : 6) || 6,
          red_line_setback: parseFloat(cfgRedlineSetback ? cfgRedlineSetback.value : 5) || 5,
          typology: cfgTypology.value,
          courtyard_orientation: cfgCourtOrient.value,
          allow_towers_in_mixed: cfgTowersMixed.checked,
          variable_insolation: cfgVarInsolation.checked,
          gen_mode: cfgGenMode.value,
          target_metric: cfgTargetMetric.value,
          target_value: parseFloat(cfgTargetVal.value) || 1.5,
          target_floors: parseInt(cfgFloorsSlider.value, 10) || 14,
          cascade_floors: cfgCascadeFloors.checked,
          asymmetric_wings: cfgAsymmetricWings.checked,
          floor_height: parseFloat(cfgFloorH.value) || 3.0,
          max_building_height_m: parseFloat(cfgMaxH.value) || 0,
          max_sections: parseInt(cfgMaxSectionsSlider.value, 10) || 8,
          regional_norm_id: cfgRegionalNorm.value,
          max_far: parseFloat(cfgFarSlider.value) || 2.5,
          max_bcr: parseFloat(cfgBcrSlider.value) || 0.4,
          preferred_section_ids: preferredSectionIds.length ? preferredSectionIds : null,
          urban_block_size: cfgPeriBlockSize ? (parseFloat(cfgPeriBlockSize.value) || 100.0) : 100.0,
          internal_road_width: cfgPeriRoadWidth ? (parseFloat(cfgPeriRoadWidth.value) || 16.0) : 16.0,
          perimeter_layout_style: cfgPeriStyle ? cfgPeriStyle.value : "U_SHAPE"
        }};

        if (siteMode === "cadastre") {{
          base.cad_query = cfgCadInput.value.trim() || "63:01:0709002:2320";
          base.custom_area = parseFloat(cfgAreaInput.value) || 32000;
          base.enable_red_line = cfgRedlineToggle.checked;
          if (uploadedCadBase64) {{
            base.cad_file_base64 = uploadedCadBase64;
            base.cad_filename = uploadedCadFilename;
          }}
        }} else {{
          base.assigned_cad_query = cfgDwgAssignedCad.value.trim() || "63:01:0709002:2320";
          base.boundary_layer = cfgBoundaryLayer.value || null;
          base.red_lines_layer = cfgRedlineLayer.value || null;
          if (uploadedCadBase64) {{
            base.cad_file_base64 = uploadedCadBase64;
            base.cad_filename = uploadedCadFilename;
          }}
        }}
        return base;
      }}

      // УПРАВЛЕНИЕ ЭТАПАМИ (1: Посадка -> 2: Застройка)
      function updateStageUI() {{
        if (!isSiteLocked) {{
          // Этап 1: Посадка участка
          if (stepperStep1) stepperStep1.className = "stepper-step active";
          if (stepperNum1) stepperNum1.textContent = "1";
          if (stepperStep2) stepperStep2.className = "stepper-step";
          if (stepperNum2) stepperNum2.textContent = "2";

          if (stageBanner1) stageBanner1.style.display = "flex";
          if (stageBanner2) stageBanner2.style.display = "none";

          if (btnLockSidebar) btnLockSidebar.style.display = "block";
          if (btnUnlockSidebar) btnUnlockSidebar.style.display = "none";

          if (sidebarStage2Group) sidebarStage2Group.classList.add("sidebar-stage2-locked");
          if (sidebarLockNotice) sidebarLockNotice.style.display = "block";

          setViewTab("osm");
        }} else {{
          // Этап 2: Застройка и ТЭП
          if (stepperStep1) stepperStep1.className = "stepper-step completed";
          if (stepperNum1) stepperNum1.textContent = "✓";
          if (stepperStep2) stepperStep2.className = "stepper-step active";
          if (stepperNum2) stepperNum2.textContent = "2";

          if (stageBanner1) stageBanner1.style.display = "none";
          if (stageBanner2) stageBanner2.style.display = "flex";

          if (btnLockSidebar) btnLockSidebar.style.display = "none";
          if (btnUnlockSidebar) btnUnlockSidebar.style.display = "block";

          if (sidebarStage2Group) sidebarStage2Group.classList.remove("sidebar-stage2-locked");
          if (sidebarLockNotice) sidebarLockNotice.style.display = "none";

          if (stage2StatusDesc) {{
            const rotSign = currentRotation >= 0 ? "+" : "";
            const latStr = (currentSiteLat || (currentScenario.geo_center && currentScenario.geo_center.lat) || 53.2502).toFixed(5);
            const lonStr = (currentSiteLon || (currentScenario.geo_center && currentScenario.geo_center.lon) || 50.3184).toFixed(5);
            const haStr = currentScenario.site_area_ha || (currentScenario.site_area_sqm / 10000).toFixed(2);
            stage2StatusDesc.textContent = `Участок зафиксирован: ${{haStr}} га • поворот ${{rotSign}}${{currentRotation.toFixed(1)}}° • WGS-84: [${{latStr}}, ${{lonStr}}]`;
          }}
        }}
      }}

      // Загрузка предпросмотра участка (Этап 1: контур без зданий)
      async function loadSitePreview(resetRot = false) {{
        if (resetRot) {{
          setRotation(0, true, false);
        }}
        const payload = getFormData();
        payload.stage = 1;
        payload.preview_only = true;

        try {{
          const resp = await fetch(API_BASE + "/api/site-preview", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(payload)
          }});

          if (resp.ok) {{
            const result = await resp.json();
            currentScenario = result;
            if (result.geo_center) {{
              currentSiteLat = result.geo_center.lat;
              currentSiteLon = result.geo_center.lon;
            }}
            renderScenario();
            updateStageUI();
            updateBackendBadge(true);
            return;
          }}
        }} catch (err) {{
          console.warn("Ошибка предпросмотра участка:", err);
          updateBackendBadge(false);
        }}

        renderScenario();
        updateStageUI();
      }}

      // Фиксация участка и запуск генерации (Переход к Этапу 2)
      async function lockSiteAndGenerate() {{
        isSiteLocked = true;
        updateStageUI();

        if (btnLockMain) btnLockMain.disabled = true;
        if (btnLockSidebar) btnLockSidebar.disabled = true;
        if (btnRunPipeline) btnRunPipeline.disabled = true;
        showToast("🔒 Участок зафиксирован! Генерация застройки и расчёт ТЭП...");

        const payload = getFormData();
        payload.stage = 2;
        payload.site_locked = true;

        try {{
          const resp = await fetch(API_BASE + "/api/generate", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(payload)
          }});

          if (!resp.ok) {{
            const errData = await resp.json().catch(() => ({{}}));
            throw new Error(errData.error || `HTTP error ${{resp.status}}`);
          }}

          const result = await resp.json();
          currentScenario = result;
          selectedSectionId = null;

          resetSvgView();
          renderScenario();
          updateStageUI();
          updateBackendBadge(true);
          showToast(`✓ Застройка успешно сгенерирована: GFA ${{fmt(result.tep.gfa)}} м²`);
        }} catch (err) {{
          console.warn("Ошибка генерации:", err);
          updateBackendBadge(false);
          const msg = (err.message && (err.message.includes("Failed to fetch") || err.message.includes("NetworkError")))
            ? "Python-сервер не запущен. Для генерации на лету запустите 'run_dashboard.bat'"
            : (err.message || "Ошибка генерации застройки");
          showToast(`⚠️ ${{msg}}`, true);
          renderScenario();
          updateStageUI();
        }} finally {{
          if (btnLockMain) btnLockMain.disabled = false;
          if (btnLockSidebar) btnLockSidebar.disabled = false;
          if (btnRunPipeline) btnRunPipeline.disabled = false;
        }}
      }}

      // Разблокировка участка (Возврат к Этапу 1)
      async function unlockSite() {{
        isSiteLocked = false;
        updateStageUI();
        showToast("🔓 Режим посадки: выровняйте контур и закрепите его");
        await loadSitePreview(false);
      }}

      // Прослушивание сообщений от интерактивной карты Leaflet
      window.addEventListener("message", function(e) {{
        if (!e.data || !e.data.isMapTransform) return;
        const t = e.data.transform;
        if (!t) return;

        if (t.map_rot !== undefined && !isNaN(t.map_rot)) {{
          setRotation(t.map_rot, true, false);
        }}
        if (t.map_lat && t.map_lon && t.dist_m > 0.1) {{
          userHasMovedSite = true;
          currentSiteLat = t.map_lat;
          currentSiteLon = t.map_lon;
          if (cfgManualLat) cfgManualLat.value = t.map_lat.toFixed(5);
          if (cfgManualLon) cfgManualLon.value = t.map_lon.toFixed(5);
          if (cfgDwgLat) cfgDwgLat.value = t.map_lat.toFixed(5);
          if (cfgDwgLon) cfgDwgLon.value = t.map_lon.toFixed(5);
          if (siteCoordsLabel) {{
            siteCoordsLabel.textContent = `WGS-84: [${{t.map_lat.toFixed(5)}}, ${{t.map_lon.toFixed(5)}}]`;
          }}
        }}
        if (t.lock) {{
          lockSiteAndGenerate();
        }}
      }});

      // Кнопки блокировки / разблокировки
      if (btnLockMain) btnLockMain.addEventListener("click", lockSiteAndGenerate);
      if (btnLockSidebar) btnLockSidebar.addEventListener("click", lockSiteAndGenerate);
      if (btnUnlockMain) btnUnlockMain.addEventListener("click", unlockSite);
      if (btnUnlockSidebar) btnUnlockSidebar.addEventListener("click", unlockSite);
      if (btnResetRotMain) btnResetRotMain.addEventListener("click", () => setRotation(0, true, true));

      if (stepperStep1) stepperStep1.addEventListener("click", () => {{
        if (isSiteLocked) unlockSite();
      }});
      if (stepperStep2) stepperStep2.addEventListener("click", () => {{
        if (!isSiteLocked) lockSiteAndGenerate();
      }});

      // Кнопка в сайдбаре запускает генерацию с фиксацией
      btnRunPipeline.addEventListener("click", async () => {{
        await lockSiteAndGenerate();
      }});

      // МАТРИЦА ВАРИАНТОВ
      btnCalcVariants.addEventListener("click", async () => {{
        btnCalcVariants.disabled = true;
        btnCalcVariants.textContent = "⏳ Расчет вариантов...";

        try {{
          const payload = getFormData();
          const resp = await fetch(API_BASE + "/api/variants", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(payload)
          }});

          if (!resp.ok) throw new Error("Ошибка расчета вариантов");
          const data = await resp.json();
          renderVariantsTable(data.variants || []);
          updateBackendBadge(true);
          showToast(`✓ Рассчитано ${{data.variants.length}} вариантов этажности`);
        }} catch (err) {{
          console.warn("Ошибка расчета вариантов:", err);
          updateBackendBadge(false);
          const msg = (err.message && (err.message.includes("Failed to fetch") || err.message.includes("NetworkError")))
            ? "Python-сервер не запущен. Для расчета вариантов запустите 'run_dashboard.bat'"
            : (err.message || "Ошибка расчета вариантов");
          showToast(`⚠️ ${{msg}}`, true);
        }} finally {{
          btnCalcVariants.disabled = false;
          btnCalcVariants.textContent = "⚡ Рассчитать варианты";
        }}
      }});

      function renderVariantsTable(variants) {{
        variantsTableBody.innerHTML = "";
        if (!variants.length) {{
          variantsTableBody.innerHTML = `<tr><td colspan="7" style="text-align:center;">Нет вариантов</td></tr>`;
          return;
        }}
        variants.forEach(v => {{
          const tr = document.createElement("tr");
          const okBadge = v.normative_ok ? `<span class="badge-status badge-ok">✅ В норме</span>` : `<span class="badge-status badge-warn">⚠️ Превышение</span>`;
          tr.innerHTML = `
            <td><strong>${{v.floors}} эт.</strong></td>
            <td>${{fmt(v.gfa)}}</td>
            <td>${{fmt(v.residential_area)}}</td>
            <td>${{v.apartments_total}}</td>
            <td>${{v.bcr}}%</td>
            <td>${{v.far}}</td>
            <td>${{okBadge}}</td>
          `;
          variantsTableBody.appendChild(tr);
        }});
      }}

      // МОДАЛКА ОТЧЕТА
      btnShowReport.addEventListener("click", async () => {{
        reportModal.style.display = "flex";
        modalReportText.textContent = "Загрузка отчёта...";
        try {{
          const resp = await fetch(API_BASE + "/api/export/report");
          if (!resp.ok) throw new Error("HTTP " + resp.status);
          modalReportText.textContent = await resp.text();
          updateBackendBadge(true);
        }} catch (err) {{
          updateBackendBadge(false);
          modalReportText.textContent = `ТЕХНИКО-ЭКОНОМИЧЕСКИЕ ПОКАЗАТЕЛИ (ДЕМО-ОТЧЕТ)\n=========================================\nУчасток: ${{currentScenario.cadastral_number}}\nПлощадь: ${{currentScenario.site_area_sqm}} м²\nОбщая площадь (GFA): ${{currentScenario.tep.gfa}} м²\nПлотность FAR: ${{currentScenario.tep.far}}\nBCR: ${{currentScenario.tep.bcr}}\n\n💡 Для живого отчёта запустите run_dashboard.bat!`;
        }}
      }});

      modalCloseBtn.addEventListener("click", () => reportModal.style.display = "none");
      reportModal.addEventListener("click", e => {{ if (e.target === reportModal) reportModal.style.display = "none"; }});

      // РЕНДЕР СЦЕНАРИЯ
      function renderScenario() {{
        const s = currentScenario;

        // Обновление чистой шапки
        siteCadLabel.textContent = `📍 ${{s.cadastral_number || 'Участок без номера'}}`;
        siteRegionLabel.textContent = `${{s.region_name}} (${{s.site_area_ha}} га)`;
        if (s.geo_center) {{
          siteCoordsLabel.textContent = `WGS-84: [${{s.geo_center.lat.toFixed(5)}}, ${{s.geo_center.lon.toFixed(5)}}]`;
        }}
        linkYandex.href = s.yandex_maps_url || "#";
        linkPkk.href = s.pkk_url || "#";

        // 10 КАРТОЧЕК KPI
        const tep = s.tep || {{}};
        const siteSqm = s.site_area_sqm || 42500;
        const siteHa = s.site_area_ha || (siteSqm / 10000) || 1;
        const isStage1 = (!isSiteLocked) || (s.stage === 1);

        if (isStage1) {{
          // 1. GFA
          kpiGfa.textContent = "— м²";
          kpiGfaDesc.innerHTML = `Зона застройки: <strong>${{fmt(s.buildable_area_sqm || 0)}} м²</strong>`;
          kpiGfaBadge.className = "badge-status badge-warn";
          kpiGfaBadge.textContent = "Шаг 1: Посадка";

          // 2. ЖИЛОЙ ФОНД
          kpiLiving.textContent = "— м²";
          kpiLivingDesc.innerHTML = `Площадь участка: <strong>${{fmt(siteSqm)}} м²</strong> (${{siteHa}} га)`;
          kpiLivingBadge.textContent = "Ожидает фиксации";

          // 3. ПЛОТНОСТЬ (FAR)
          kpiFar.textContent = "FAR —";
          kpiFarDesc.innerHTML = `Лимит СП 42: <strong>FAR ≤ ${{cfgFarSlider ? cfgFarSlider.value : 2.5}}</strong>`;
          kpiFarBadge.className = "badge-status badge-ok";
          kpiFarBadge.textContent = "СП 42: FAR ≤ 2.50";

          // 4. ПРОЦЕНТ ЗАСТРОЙКИ (BCR)
          kpiBcr.textContent = "BCR —";
          kpiBcrDesc.innerHTML = `Лимит ПЗЗ: <strong>до ${{cfgBcrBadge ? cfgBcrBadge.textContent : '40%'}}</strong>`;
          kpiBcrBadge.className = "badge-status badge-ok";
          kpiBcrBadge.textContent = "Лимит застройки ≤ 40%";

          // 5. КОММЕРЦИЯ / РИТЕЙЛ
          kpiComm.textContent = "— м²";
          kpiCommDesc.innerHTML = "1-е этажи: расчет на Шаге 2";
          kpiCommBadge.textContent = "Стрит-ритейл";

          // 6. НАСЕЛЕНИЕ
          kpiPop.textContent = "— чел.";
          kpiPopDesc.innerHTML = "Расчет населения на Шаге 2";
          kpiPopBadge.textContent = "Норма 30 м²/чел";

          // 7. ПАРКОВОЧНЫЕ МЕСТА
          kpiParking.textContent = "— м/м";
          kpiParkingDesc.innerHTML = "Баланс парковок по РНГП";
          kpiParkingBadge.textContent = "Парковки РНГП";

          // 8. ОЗЕЛЕНЕНИЕ
          kpiGreen.textContent = "— м²";
          kpiGreenDesc.innerHTML = `Мин. озеленение: <strong>≥ 25%</strong> (${{fmt(Math.round(siteSqm * 0.25))}} м²)`;
          kpiGreenBadge.className = "badge-status badge-ok";
          kpiGreenBadge.textContent = "СП 42: ≥ 25%";

          // 9. ДВОРОВЫЕ ПЛОЩАДКИ
          kpiPlaygrounds.textContent = "— м²";
          kpiPlaygroundsDesc.innerHTML = "Дворовые площадки по нормам РНГП";
          kpiPlaygroundsBadge.textContent = "Благоустройство";

          // 10. КОРПУСА И СЕКЦИИ
          kpiMorphology.textContent = "0 корпусов";
          const rotDeg = currentRotation || 0;
          const rotSign = rotDeg >= 0 ? "+" : "";
          kpiMorphologyDesc.innerHTML = `Поворот: <strong>${{rotSign}}${{rotDeg.toFixed(1)}}°</strong> · Контур готов`;
          kpiMorphologyBadge.textContent = "Шаг 1: Посадка";

          // Баланс РНГП на Шаге 1
          balRegionLabel.textContent = s.norm_name || "СП 42.13330.2016";
          balParkingReq.textContent = "— м/м";
          balParkingSub.textContent = "—";
          balParkingGround.textContent = "— м/м";
          balParkingGroundArea.textContent = "—";
          balParkingUndergroundBox.className = "warning-banner warning-info";
          balParkingUndergroundText.textContent = "Норматив парковок будет рассчитан после генерации секций на Шаге 2.";
          plChildren.textContent = "— м²";
          plSport.textContent = "— м²";
          plRelax.textContent = "— м²";
          plUtility.textContent = "— м²";
          balWarningsContainer.innerHTML = `<div class="warning-banner warning-info">
            <span>🧭</span><span><strong>Шаг 1 из 2: Посадка и ориентация участка.</strong> Настройте положение и угол контура на карте OSM. Нажмите «🔒 Закрепить участок и перейти к застройке» на карте или панели.</span>
          </div>`;
          balanceProgressList.innerHTML = `<div style="color:var(--secondary); font-size:13px; padding:12px 0;">Баланс территории формируется на Шаге 2</div>`;
          buildingsAptTbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--secondary);">
            📍 <strong>Участок на Шаге 1 (Посадка и ориентация).</strong><br>
            Закрепите контур кнопкой «🔒 Закрепить участок и перейти к застройке», чтобы рассчитать корпуса и квартирографию.
          </td></tr>`;
        }} else {{
          // 1. GFA
          kpiGfa.textContent = `${{fmt(tep.gfa)}} м²`;
          kpiGfaDesc.innerHTML = `Жилая: <strong>${{fmt(tep.residential_area)}} м²</strong> · Коммерция: <strong>${{fmt(tep.commercial_area)}} м²</strong>`;
          const k1 = tep.gfa > 0 ? (tep.residential_area / tep.gfa).toFixed(2) : "0.65";
          kpiGfaBadge.textContent = `Выход К1: ${{k1}}`;

          // 2. ЖИЛОЙ ФОНД
          kpiLiving.textContent = `${{fmt(tep.residential_area)}} м²`;
          const avgApt = tep.apartments_total > 0 ? (tep.residential_area / tep.apartments_total).toFixed(1) : "—";
          kpiLivingDesc.innerHTML = `Всего: <strong>${{fmt(tep.apartments_total)}} кв.</strong> · ср. <strong>${{avgApt}} м²</strong>`;
          kpiLivingBadge.textContent = `Комфорт (30 м²/чел)`;

          // 3. ПЛОТНОСТЬ (FAR)
          kpiFar.textContent = `FAR ${{tep.far.toFixed(2)}}`;
          const density = (tep.residential_area / siteHa / 1000).toFixed(1);
          kpiFarDesc.innerHTML = `Плотность фонда: <strong>${{density}} тыс. м²/га</strong>`;
          if (tep.far > 2.50) {{
            kpiFarBadge.className = "badge-status badge-warn";
            kpiFarBadge.textContent = `⚠️ Превышение СП 42 (>2.50)`;
          }} else {{
            kpiFarBadge.className = "badge-status badge-ok";
            kpiFarBadge.textContent = `СП 42: FAR ≤ 2.50`;
          }}

          // 4. ПРОЦЕНТ ЗАСТРОЙКИ (BCR)
          kpiBcr.textContent = `${{(tep.bcr * 100).toFixed(1)}}%`;
          kpiBcrDesc.innerHTML = `Пятно зданий: <strong>${{fmt(tep.building_area)}} м²</strong>`;
          if (tep.bcr > 0.40) {{
            kpiBcrBadge.className = "badge-status badge-warn";
            kpiBcrBadge.textContent = `⚠️ Превышение ПЗЗ (>40%)`;
          }} else {{
            kpiBcrBadge.className = "badge-status badge-ok";
            kpiBcrBadge.textContent = `Лимит ПЗЗ ≤ 40%`;
          }}

          // 5. КОММЕРЦИЯ / РИТЕЙЛ
          kpiComm.textContent = `${{fmt(tep.commercial_area)}} м²`;
          const commPct = tep.gfa > 0 ? ((tep.commercial_area / tep.gfa) * 100).toFixed(1) : "0";
          kpiCommDesc.innerHTML = `1-е этажи: <strong>${{commPct}}%</strong> от GFA`;
          kpiCommBadge.textContent = `Стрит-ритейл и услуги`;

          // 6. НАСЕЛЕНИЕ
          kpiPop.textContent = `${{fmt(tep.population)}} чел.`;
          const kinder = Math.round(tep.population * 0.061);
          const school = Math.round(tep.population * 0.120);
          kpiPopDesc.innerHTML = `Детсады: <strong>~${{kinder}} мест</strong> · Школы: <strong>~${{school}} мест</strong>`;
          kpiPopBadge.textContent = `Норма 30 м²/чел`;

          // 7. ПАРКОВОЧНЫЕ МЕСТА
          kpiParking.textContent = `${{fmt(tep.parking_required)}} м/м`;
          kpiParkingDesc.innerHTML = `Наземных: <strong>${{fmt(tep.parking_ground)}}</strong> · Подземных: <strong>${{fmt(tep.parking_underground)}}</strong>`;
          kpiParkingBadge.textContent = `в т.ч. ${{fmt(tep.parking_required_guest)}} гостевых`;

          // 8. ОЗЕЛЕНЕНИЕ
          kpiGreen.textContent = `${{fmt(tep.green_area)}} м²`;
          const greenPct = siteSqm > 0 ? ((tep.green_area / siteSqm) * 100).toFixed(1) : "0";
          kpiGreenDesc.innerHTML = `Доля участка: <strong>${{greenPct}}%</strong>`;
          kpiGreenBadge.className = (parseFloat(greenPct) >= 25) ? "badge-status badge-ok" : "badge-status badge-warn";
          kpiGreenBadge.textContent = `СП 42: ≥ 25%`;

          // 9. ДВОРОВЫЕ ПЛОЩАДКИ
          kpiPlaygrounds.textContent = `${{fmt(tep.playgrounds_total)}} м²`;
          kpiPlaygroundsDesc.innerHTML = `Дети: <strong>${{fmt(tep.playgrounds_children)}} м²</strong> · Спорт: <strong>${{fmt(tep.playgrounds_sport)}} м²</strong>`;
          const perCap = tep.population > 0 ? (tep.playgrounds_total / tep.population).toFixed(2) : "0";
          kpiPlaygroundsBadge.textContent = `${{perCap}} м²/жителя`;

          // 10. КОРПУСА И СЕКЦИИ
          const bList = s.buildings || [];
          kpiMorphology.textContent = `${{bList.length}} корпусов`;
          const secCount = (s.sections || []).length;
          const flArray = bList.map(b => b.floors);
          const minF = flArray.length ? Math.min(...flArray) : 0;
          const maxF = flArray.length ? Math.max(...flArray) : 0;
          const flText = minF === maxF ? `${{maxF}} эт.` : `${{minF}}–${{maxF}} эт.`;
          kpiMorphologyDesc.innerHTML = `Секций: <strong>${{secCount}}</strong> · Этажность: <strong>${{flText}}</strong>`;
          kpiMorphologyBadge.textContent = `Каскадная форма`;

          // БАЛАНС РНГП
          balRegionLabel.textContent = s.norm_name;
          balParkingReq.textContent = `${{fmt(s.tep.parking_required)}} м/м`;
          balParkingSub.textContent = `в т.ч. гостевых: ${{fmt(s.tep.parking_required_guest)}} м/м`;
          balParkingGround.textContent = `${{fmt(s.tep.parking_ground)}} м/м`;
          balParkingGroundArea.textContent = `${{fmt(s.tep.parking_ground_area)}} м² открытых стоянок`;

          if (s.tep.parking_underground > 0) {{
            balParkingUndergroundBox.className = "warning-banner warning-warn";
            balParkingUndergroundText.textContent = `Дефицит в подземный паркинг: ${{fmt(s.tep.parking_underground)}} м/м (требуется ~${{fmt(s.tep.parking_underground_area_est)}} м² паркинга)`;
          }} else {{
            balParkingUndergroundBox.className = "warning-banner warning-info";
            balParkingUndergroundText.textContent = "Дефицита нет: 100% нормативных машиномест размещено на открытых стоянках участка.";
          }}

          plChildren.textContent = `${{fmt(s.tep.playgrounds_children)}} м²`;
          plSport.textContent = `${{fmt(s.tep.playgrounds_sport)}} м²`;
          plRelax.textContent = `${{fmt(s.tep.playgrounds_relax)}} м²`;
          plUtility.textContent = `${{fmt(s.tep.playgrounds_utility)}} м²`;

          balWarningsContainer.innerHTML = "";
          (s.warnings || []).forEach(w => {{
            const div = document.createElement("div");
            const isUnder = w.toLowerCase().includes("подземный");
            div.className = `warning-banner ${{isUnder ? 'warning-info' : 'warning-warn'}}`;
            div.innerHTML = `<span>${{isUnder ? '🚗' : '⚠️'}}</span><span>${{w}}</span>`;
            balWarningsContainer.appendChild(div);
          }});

          balanceProgressList.innerHTML = "";
          const balColors = {{
            "Застройка (дома)": "#538db2",
            "Застройка (пятно зданий)": "#538db2",
            "Озеленение территории": "#8d9f6b",
            "Озеленение": "#8d9f6b",
            "Детские и спорт. площадки": "#c5a35b",
            "Дворовые площадки": "#c5a35b",
            "Проезды, тротуары, стоянки": "#798392",
            "Проезды и тротуары": "#798392",
            "Наземные парковки": "#ce8c68"
          }};
          Object.entries(s.balance_shares || {{}}).forEach(([k, pct]) => {{
            const item = document.createElement("div");
            item.className = "progress-item";
            item.innerHTML = `
              <div class="progress-header"><span>${{k}}</span><strong>${{pct}}%</strong></div>
              <div class="progress-track"><div class="progress-fill" style="width:${{pct}}%; background:${{balColors[k] || '#538db2'}}"></div></div>
            `;
            balanceProgressList.appendChild(item);
          }});

          // Квартирография по домам
          buildingsAptTbody.innerHTML = "";
          (s.buildings || []).forEach(b => {{
            const tr = document.createElement("tr");
            const ap = b.apartments || {{}};
            const flStr = b.min_floors === b.floors ? `${{b.floors}} эт.` : `${{b.min_floors}}–${{b.floors}} эт.`;
            tr.innerHTML = `
              <td><strong>${{b.name}}</strong></td>
              <td>${{flStr}}</td>
              <td>${{ap.studio || 0}}</td>
              <td>${{ap['1k'] || 0}}</td>
              <td>${{ap['2k'] || 0}}</td>
              <td>${{ap['3k'] || 0}}</td>
              <td><strong>${{b.apartments_total}}</strong></td>
              <td>${{fmt(b.total_gfa)}}</td>
            `;
            buildingsAptTbody.appendChild(tr);
          }});
        }}

        // SVG
        svgRoot.setAttribute("viewBox", s.svg_viewbox);
        svgSiteBound.setAttribute("d", s.site_path);
        svgBuildable.setAttribute("d", s.buildable_path);

        svgRedlinesGroup.innerHTML = "";
        (s.red_lines_paths || []).forEach(rlPath => {{
          const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
          p.setAttribute("d", rlPath);
          p.setAttribute("class", "svg-red-line");
          svgRedlinesGroup.appendChild(p);
        }});

        svgSectionsGroup.innerHTML = "";
        (s.sections || []).forEach(sec => {{
          const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
          p.setAttribute("d", sec.path);
          p.setAttribute("class", "svg-section");
          p.setAttribute("data-id", sec.id);
          p.setAttribute("tabindex", "0");

          p.addEventListener("mouseenter", e => showTooltip(sec, e));
          p.addEventListener("mousemove", moveTooltip);
          p.addEventListener("mouseleave", hideTooltip);
          p.addEventListener("click", () => selectSection(sec.id));

          svgSectionsGroup.appendChild(p);
        }});

        updateSectionsColoring();
        updateLegend();
        renderTable();
        updateInspector();

        // Синхронизация поворота участка
        if (s.site_rotation !== undefined && !isNaN(s.site_rotation)) {{
          currentRotation = (Math.round(s.site_rotation) % 360 + 360) % 360;
        }}
        if (cfgRotSlider) cfgRotSlider.value = currentRotation;
        if (cfgRotBadge) cfgRotBadge.textContent = `${{currentRotation}}°`;

        const baseRot = s.site_rotation || 0;
        const visualDelta = currentRotation - baseRot;
        const world = document.getElementById("svg-site-world");
        if (world) {{
          world.setAttribute("transform", `rotate(${{visualDelta}}, 500, 350)`);
        }}
        const northArrow = document.querySelector(".north-arrow");
        if (northArrow) {{
          northArrow.style.transform = `rotate(${{-currentRotation}}deg)`;
        }}

        if (s.leaflet_html) {{
          const iframeOsm = viewOsm.querySelector("iframe");
          if (iframeOsm) {{
            iframeOsm.srcdoc = s.leaflet_html;
          }}
        }}
        if (s.viewer_3d_html) {{
          const iframe3d = view3d.querySelector("iframe");
          if (iframe3d) {{
            iframe3d.srcdoc = s.viewer_3d_html;
          }}
        }}
      }}

      // Цвета секций
      function getSectionColor(sec) {{
        if (activeMetric === "category") {{
          return CATEGORY_COLORS[sec.category] || "#798392";
        }} else if (activeMetric === "floors") {{
          const minF = 8, maxF = 22;
          const ratio = Math.max(0, Math.min(1, (sec.floors - minF) / (maxF - minF)));
          const r = Math.round(178 - ratio * (178 - 25));
          const g = Math.round(208 - ratio * (208 - 83));
          const b = Math.round(227 - ratio * (227 - 111));
          return `rgb(${{r}}, ${{g}}, ${{b}})`;
        }} else if (activeMetric === "building") {{
          const bIdx = parseInt(sec.building_id.replace("b", ""), 10) - 1;
          return BUILDING_PALETTE[bIdx % BUILDING_PALETTE.length];
        }} else if (activeMetric === "gfa") {{
          const ratio = Math.max(0, Math.min(1, sec.gfa / 8000));
          return `hsl(205, 55%, ${{75 - ratio * 45}}%)`;
        }}
        return "#538db2";
      }}

      function updateSectionsColoring() {{
        svgSectionsGroup.querySelectorAll(".svg-section").forEach(el => {{
          const secId = el.getAttribute("data-id");
          const sec = currentScenario.sections.find(x => x.id === secId);
          if (sec) {{
            el.setAttribute("fill", getSectionColor(sec));
            el.classList.toggle("selected", secId === selectedSectionId);
          }}
        }});
      }}

      function updateLegend() {{
        mapLegendItems.innerHTML = "";
        if (activeMetric === "category") {{
          mapLegendTitle.textContent = "Категории типовых секций";
          [
            {{ label: "Рядовая секция", color: CATEGORY_COLORS.MIDDLE }},
            {{ label: "Угловая секция", color: CATEGORY_COLORS.CORNER }},
            {{ label: "Торцевая секция", color: CATEGORY_COLORS.END }},
            {{ label: "Точечная башня", color: CATEGORY_COLORS.TOWER }}
          ].forEach(item => {{
            const div = document.createElement("div");
            div.className = "legend-item";
            div.innerHTML = `<span class="legend-chip" style="background:${{item.color}}"></span><span>${{item.label}}</span>`;
            mapLegendItems.appendChild(div);
          }});
        }} else if (activeMetric === "floors") {{
          mapLegendTitle.textContent = "Этажность секций (эт.)";
          [
            {{ label: "8–10 этажей (пониженные крылья)", color: "#b2d0e3" }},
            {{ label: "12–14 этажей (типовой массив)", color: "#6da2bf" }},
            {{ label: "16–22 этажа (высотные акценты)", color: "#19536f" }}
          ].forEach(item => {{
            const div = document.createElement("div");
            div.className = "legend-item";
            div.innerHTML = `<span class="legend-chip" style="background:${{item.color}}"></span><span>${{item.label}}</span>`;
            mapLegendItems.appendChild(div);
          }});
        }} else if (activeMetric === "building") {{
          mapLegendTitle.textContent = "Корпуса застройки";
          currentScenario.buildings.slice(0, 6).forEach((b, i) => {{
            const div = document.createElement("div");
            div.className = "legend-item";
            div.innerHTML = `<span class="legend-chip" style="background:${{BUILDING_PALETTE[i % BUILDING_PALETTE.length]}}"></span><span>${{b.name}} (${{b.floors}} эт.)</span>`;
            mapLegendItems.appendChild(div);
          }});
        }} else {{
          mapLegendTitle.textContent = "Поэтажная площадь GFA";
          const div = document.createElement("div");
          div.className = "legend-item";
          div.innerHTML = `<span>От 3 000 м² (светлый) до 8 000 м² (темный)</span>`;
          mapLegendItems.appendChild(div);
        }}
      }}

      function showTooltip(sec, e) {{
        mapTooltip.style.display = "block";
        mapTooltip.innerHTML = `<strong>${{sec.label}} · ${{sec.category_label}}</strong><span>${{sec.floors}} эт. (${{sec.height_m}} м) · ${{sec.apartments_total}} кв.</span>`;
        moveTooltip(e);
      }}

      function moveTooltip(e) {{
        const rect = viewSvg.getBoundingClientRect();
        mapTooltip.style.left = `${{e.clientX - rect.left}}px`;
        mapTooltip.style.top = `${{e.clientY - rect.top}}px`;
      }}

      function hideTooltip() {{ mapTooltip.style.display = "none"; }}

      function selectSection(secId) {{
        selectedSectionId = (selectedSectionId === secId) ? null : secId;
        updateSectionsColoring();
        updateInspector();
        highlightTableRow(selectedSectionId);
      }}

      btnClearSelection.addEventListener("click", () => selectSection(null));

      function updateInspector() {{
        if (!selectedSectionId) {{
          inspectorEmpty.style.display = "flex";
          inspectorActive.style.display = "none";
          btnClearSelection.style.display = "none";
          return;
        }}

        const sec = currentScenario.sections.find(s => s.id === selectedSectionId);
        if (!sec) return;

        inspectorEmpty.style.display = "none";
        inspectorActive.style.display = "flex";
        btnClearSelection.style.display = "inline-block";

        inspTitle.textContent = `${{sec.building_name}} · Секция ${{sec.section_index}}`;
        inspSubtitle.textContent = `Марка: ${{sec.type_name}} (${{sec.type_id}})`;
        inspCatBadge.textContent = sec.category_label;
        inspCatBadge.style.background = CATEGORY_COLORS[sec.category] || "#538db2";

        inspFloors.textContent = `${{sec.floors}} эт.`;
        inspHeight.textContent = `${{sec.height_m}} м`;
        inspDims.textContent = `${{sec.width}} × ${{sec.depth}} м`;
        inspFootprint.textContent = `${{fmt(sec.footprint_area)}} м²`;
        inspGfa.textContent = `${{fmt(sec.gfa)}} м²`;
        inspAptsCount.textContent = `${{sec.apartments_total}} кв.`;

        inspElevators.textContent = `Лифтов: ${{sec.elevators}} шт. (пассажирский + грузопассажирский)`;
        inspGround.textContent = sec.commercial_ground ? "1-й этаж: Коммерческие помещения и вестибюль" : "1-й этаж: Жилые квартиры с палисадником";

        inspAptBars.innerHTML = "";
        const apts = sec.apartments || {{}};
        const total = sec.apartments_total || 1;
        const types = [
          {{ key: "studio", label: "Студии" }},
          {{ key: "1k", label: "1-комн." }},
          {{ key: "2k", label: "2-комн." }},
          {{ key: "3k", label: "3-комн." }}
        ];

        types.forEach(t => {{
          const count = apts[t.key] || 0;
          const pct = Math.round((count / total) * 100);
          const row = document.createElement("div");
          row.className = "apt-bar-row";
          row.innerHTML = `
            <span class="apt-bar-label">${{t.label}}</span>
            <div class="apt-bar-track"><div class="apt-bar-fill" style="width:${{pct}}%;"></div></div>
            <span class="apt-bar-val">${{count}} (${{pct}}%)</span>
          `;
          inspAptBars.appendChild(row);
        }});
      }}

      // Зум
      function updateSvgTransform() {{
        svgViewport.setAttribute("transform", `translate(${{view.x}}, ${{view.y}}) scale(${{view.zoom}})`);
      }}
      function resetSvgView() {{
        view = {{ zoom: 1, x: 0, y: 0 }};
        updateSvgTransform();
      }}

      svgRoot.addEventListener("pointerdown", e => {{
        if (e.button !== 0) return;
        isDragging = true;
        dragStart = {{ x: e.clientX - view.x, y: e.clientY - view.y }};
        svgRoot.setPointerCapture(e.pointerId);
      }});

      svgRoot.addEventListener("pointermove", e => {{
        if (!isDragging) return;
        view.x = e.clientX - dragStart.x;
        view.y = e.clientY - dragStart.y;
        updateSvgTransform();
      }});

      function endDrag(e) {{
        isDragging = false;
        try {{ svgRoot.releasePointerCapture(e.pointerId); }} catch (_) {{}}
      }}
      svgRoot.addEventListener("pointerup", endDrag);
      svgRoot.addEventListener("pointercancel", endDrag);

      svgRoot.addEventListener("wheel", e => {{
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        view.zoom = Math.max(0.7, Math.min(8, view.zoom * factor));
        updateSvgTransform();
      }}, {{ passive: false }});

      document.getElementById("btn-zoom-in").addEventListener("click", () => {{
        view.zoom = Math.min(8, view.zoom * 1.25); updateSvgTransform();
      }});
      document.getElementById("btn-zoom-out").addEventListener("click", () => {{
        view.zoom = Math.max(0.7, view.zoom / 1.25); updateSvgTransform();
      }});
      document.getElementById("btn-zoom-reset").addEventListener("click", resetSvgView);

      document.getElementById("btn-zoom-focus").addEventListener("click", () => {{
        if (!selectedSectionId) return;
        const sec = currentScenario.sections.find(s => s.id === selectedSectionId);
        if (sec) {{
          view.zoom = 2.4;
          view.x = 500 - sec.cx * 2.4;
          view.y = 350 - sec.cy * 2.4;
          updateSvgTransform();
        }}
      }});

      // Таблица
      function renderTable(filterText = "") {{
        tableBody.innerHTML = "";
        const q = filterText.toLowerCase().trim();
        const filtered = (currentScenario.sections || []).filter(s => {{
          if (!q) return true;
          return s.label.toLowerCase().includes(q) ||
                 s.building_name.toLowerCase().includes(q) ||
                 s.type_name.toLowerCase().includes(q) ||
                 s.category_label.toLowerCase().includes(q);
        }});

        tableCountLabel.textContent = `Показано ${{filtered.length}} из ${{currentScenario.sections.length}} секций`;

        filtered.forEach(sec => {{
          const tr = document.createElement("tr");
          tr.setAttribute("data-id", sec.id);
          if (sec.id === selectedSectionId) tr.classList.add("selected-row");

          tr.innerHTML = `
            <td><strong>${{sec.label}}</strong></td>
            <td>${{sec.building_name}}</td>
            <td><span class="category-badge" style="background:${{CATEGORY_COLORS[sec.category] || '#798392'}}">${{sec.category_label}}</span></td>
            <td>${{sec.type_name}}</td>
            <td>${{sec.floors}} эт.</td>
            <td>${{sec.height_m}} м</td>
            <td>${{fmt(sec.footprint_area)}}</td>
            <td>${{fmt(sec.gfa)}}</td>
            <td><strong>${{sec.apartments_total}}</strong></td>
          `;

          tr.addEventListener("click", () => {{
            selectSection(sec.id);
            document.querySelector(".spatial-split").scrollIntoView({{ behavior: "smooth", block: "start" }});
          }});

          tableBody.appendChild(tr);
        }});
      }}

      function highlightTableRow(secId) {{
        tableBody.querySelectorAll("tr").forEach(tr => {{
          tr.classList.toggle("selected-row", tr.getAttribute("data-id") === secId);
        }});
      }}

      tableSearch.addEventListener("input", e => renderTable(e.target.value));

      // Экспортные ссылки при открытии через file://
      if (API_BASE) {{
        const btnDxf = document.getElementById("btn-export-dxf");
        const btn3d = document.getElementById("btn-export-3d");
        const btnGeo = document.getElementById("btn-export-geojson");
        if (btnDxf) btnDxf.href = API_BASE + "/api/export/dxf";
        if (btn3d) btn3d.href = API_BASE + "/api/export/3d-html";
        if (btnGeo) btnGeo.href = API_BASE + "/api/export/geojson";
      }}

      // Инициализация
      renderPrefSectionChips();
      renderCatalogCards();
      updateStageUI();
      renderScenario();

      checkBackendHealth().then(online => {{
        if (online) {{
          loadSitePreview(false);
        }}
      }});
    }})();
  </script>
</body>
</html>
"""

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Дашборд успешно пересобран: {OUT_HTML} ({len(html)} символов)")


if __name__ == "__main__":
    build()
