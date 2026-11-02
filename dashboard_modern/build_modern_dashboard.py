"""Генератор профессионального CAD/Studio интерфейса дашборда ТЭП.
Создан по эталонам Autodesk Forma (Spacemaker), TestFit и дизайн-системе ai-design-skills.
- Fullscreen Viewport (100vh / 100vw, без бесконечной вертикальной прокрутки)
- Плавающий верхний командный док (Command Bar)
- Плавающая левая студийная палитра инструментов (участок, типология, этажность)
- Плавающий правый Executive HUD (живые ТЭП, лимиты ПЗЗ, инспектор секций)
- Нижний плавающий док сценариев этажности (Optimizer Matrix)
- Выдвижной лоток ведомостей и территориального баланса РНГП
- Шрифты: Geist, Manrope, Geist Mono
- Векторные иконки Phosphor
"""

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DIR = Path(__file__).resolve().parent
PROTOTYPE_DIR = PROJECT_ROOT / "dashboard_prototype"
DATA_PATH = PROTOTYPE_DIR / "data.json"
OUT_HTML = DIR / "index.html"
BUILD_SRC_PY = PROTOTYPE_DIR / "build_dashboard.py"

from dashboard_prototype.generator_service import get_library_catalog


def build():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        scenarios = json.load(f)

    catalog = get_library_catalog()

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

    # Читаем клиентский JS
    with open(BUILD_SRC_PY, "r", encoding="utf-8") as f:
        src_py = f.read()

    idx_js = src_py.find("<!-- КЛИЕНТСКИЙ СКРИПТ -->")
    idx_end_js = src_py.rfind("</script>")
    client_js = src_py[idx_js + len("<!-- КЛИЕНТСКИЙ СКРИПТ -->") : idx_end_js].strip()

    html = f"""<!DOCTYPE html>
<html lang="ru" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FORMA · Генератор застройки и расчёт ТЭП Studio</title>
  
  <!-- Шрифты Geist, Geist Mono, Manrope -->
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600;700&family=Manrope:wght@400;500;600;700&display=swap" rel="stylesheet">

  <!-- Векторная система иконок Phosphor -->
  <link rel="stylesheet" type="text/css" href="https://unpkg.com/@phosphor-icons/web@2.1.1/src/regular/style.css"/>
  <link rel="stylesheet" type="text/css" href="https://unpkg.com/@phosphor-icons/web@2.1.1/src/bold/style.css"/>

  <style>
    /* ==========================================================================
       PRO STUDIO DESIGN SYSTEM (Autodesk Forma / Linear Style)
       ========================================================================== */
    :root {{
      --font-sans: 'Geist', 'Manrope', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --font-mono: 'Geist Mono', ui-monospace, SFMono-Regular, monospace;

      --bg-studio: #08090b;
      --bg-canvas: #0c0d10;
      --bg-glass: rgba(14, 15, 19, 0.88);
      --bg-glass-strong: rgba(17, 19, 24, 0.96);
      --bg-card: #13151b;
      --bg-card-hover: #191b24;
      --bg-input: #171922;

      --border-subtle: rgba(255, 255, 255, 0.06);
      --border-default: rgba(255, 255, 255, 0.1);
      --border-strong: rgba(255, 255, 255, 0.18);
      --border-focus: #38bdf8;

      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-faint: #64748b;

      --accent: #38bdf8;
      --accent-hover: #0284c7;
      --accent-subtle: rgba(56, 189, 248, 0.12);
      --accent-border: rgba(56, 189, 248, 0.28);
      --accent-glow: 0 0 24px rgba(56, 189, 248, 0.22);

      --success: #10b981;
      --success-subtle: rgba(16, 185, 129, 0.12);
      --warning: #f59e0b;
      --warning-subtle: rgba(245, 158, 11, 0.12);
      --danger: #ef4444;

      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 14px;
      --radius-xl: 18px;
      --radius-2xl: 24px;
      --radius-full: 9999px;

      --ease-base: cubic-bezier(0.22, 1, 0.36, 1);
      --shadow-hud: 0 16px 40px -10px rgba(0, 0, 0, 0.7), 0 0 1px 1px rgba(255, 255, 255, 0.08);
      --shadow-btn: 0 4px 16px rgba(56, 189, 248, 0.28);
    }}

    *, *::before, *::after {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    html, body {{
      width: 100vw;
      height: 100vh;
      overflow: hidden;
      background-color: var(--bg-studio);
      color: var(--text-main);
      font-family: var(--font-sans);
      font-size: 13px;
      -webkit-font-smoothing: antialiased;
      user-select: none;
    }}

    /* ПОЛНОЭКРАННАЯ РАБОЧАЯ СРЕДА (STUDIO WORKSPACE) */
    .studio-app {{
      width: 100vw;
      height: 100vh;
      position: relative;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}

    /* 1. ВЕРХНИЙ ПЛАВАЮЩИЙ КОМАНДНЫЙ ДОК (COMMAND BAR) */
    .studio-command-bar {{
      position: absolute;
      top: 14px;
      left: 14px;
      right: 14px;
      height: 52px;
      background: var(--bg-glass);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-xl);
      padding: 0 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      z-index: 40;
      box-shadow: var(--shadow-hud);
      transition: all 0.25s var(--ease-base);
    }}

    .studio-brand {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}

    .studio-logo {{
      width: 32px;
      height: 32px;
      background: linear-gradient(135deg, #1e293b, #0f172a);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--accent);
      font-size: 16px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.4);
    }}

    .studio-title {{
      font-size: 15px;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--text-main);
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .studio-title .badge-pro {{
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      padding: 2px 7px;
      border-radius: var(--radius-sm);
      background: var(--accent-subtle);
      color: var(--accent);
      border: 1px solid var(--accent-border);
    }}

    .project-pill {{
      display: flex;
      align-items: center;
      gap: 8px;
      background: var(--bg-input);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 5px 10px;
      font-size: 12px;
      color: var(--text-muted);
    }}

    .project-pill strong {{
      color: var(--text-main);
    }}

    /* ПЕРЕКЛЮЧАТЕЛЬ РЕЖИМОВ ВЬЮПОРТА (ЦЕНТР ХЕДЕРА) */
    .viewport-modes {{
      display: inline-flex;
      background: var(--bg-input);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-lg);
      padding: 3px;
      gap: 3px;
    }}

    .view-tab-btn {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-family: var(--font-sans);
      font-size: 12px;
      font-weight: 600;
      padding: 5px 12px;
      border-radius: var(--radius-md);
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s var(--ease-base);
    }}

    .view-tab-btn.active {{
      background: var(--bg-card);
      color: var(--text-main);
      box-shadow: 0 2px 6px rgba(0,0,0,0.4);
      border: 1px solid var(--border-subtle);
    }}

    .view-tab-btn:hover:not(.active) {{
      color: var(--text-main);
    }}

    .view-tab-btn:active {{
      transform: scale(0.97);
    }}

    .command-actions {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    .btn-studio {{
      font-family: var(--font-sans);
      font-size: 12.5px;
      font-weight: 600;
      padding: 7px 12px;
      border-radius: var(--radius-md);
      border: 1px solid var(--border-default);
      background: var(--bg-card);
      color: var(--text-main);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      text-decoration: none;
      transition: all 0.15s var(--ease-base);
    }}

    .btn-studio:hover {{
      background: var(--bg-card-hover);
      border-color: var(--border-strong);
    }}

    .btn-studio:active {{
      transform: scale(0.98);
    }}

    .btn-studio-primary {{
      background: linear-gradient(135deg, #0284c7, #38bdf8);
      border: none;
      color: #ffffff;
      box-shadow: var(--shadow-btn);
    }}

    .btn-studio-primary:hover {{
      filter: brightness(1.1);
      box-shadow: var(--accent-glow);
    }}

    /* 2. ПОЛНОРАЗМЕРНЫЙ ЦЕНТРАЛЬНЫЙ ХОЛСТ (VIEWPORT) */
    .studio-canvas-stage {{
      position: absolute;
      inset: 0;
      width: 100vw;
      height: 100vh;
      background: var(--bg-canvas);
      z-index: 10;
    }}

    #view-container-svg, #view-container-osm, #view-container-3d {{
      width: 100%;
      height: 100%;
      position: absolute;
      inset: 0;
    }}

    .map-svg {{
      width: 100%;
      height: 100%;
      cursor: grab;
    }}

    .map-svg:active {{
      cursor: grabbing;
    }}

    /* ПЛАВАЮЩИЕ ИНСТРУМЕНТЫ ВЬЮПОРТА (HUD TOOLS) */
    .viewport-floating-tools {{
      position: absolute;
      top: 80px;
      right: 390px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      z-index: 30;
      transition: right 0.25s var(--ease-base);
    }}

    .hud-btn {{
      width: 36px;
      height: 36px;
      background: var(--bg-glass);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      color: var(--text-main);
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 16px;
      box-shadow: var(--shadow-sm);
      transition: all 0.15s var(--ease-base);
    }}

    .hud-btn:hover {{
      background: var(--bg-card-hover);
      border-color: var(--border-strong);
      color: var(--accent);
    }}

    .hud-btn:active {{
      transform: scale(0.95);
    }}

    .hud-legend {{
      position: absolute;
      bottom: 90px;
      left: 390px;
      background: var(--bg-glass);
      backdrop-filter: blur(20px);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-lg);
      padding: 10px 14px;
      font-size: 11.5px;
      color: var(--text-main);
      max-width: 340px;
      box-shadow: var(--shadow-hud);
      z-index: 30;
      transition: left 0.25s var(--ease-base);
    }}

    .hud-compass {{
      position: absolute;
      top: 80px;
      left: 390px;
      width: 36px;
      height: 36px;
      background: var(--bg-glass);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 700;
      color: var(--accent);
      z-index: 30;
      box-shadow: var(--shadow-sm);
      transition: left 0.25s var(--ease-base);
    }}

    /* 3. ЛЕВАЯ ПЛАВАЮЩАЯ СТУДИЙНАЯ ПАНЕЛЬ (STUDIO TOOLBAR) */
    .studio-panel-left {{
      position: absolute;
      top: 76px;
      left: 14px;
      bottom: 14px;
      width: 360px;
      background: var(--bg-glass);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-2xl);
      display: flex;
      flex-direction: column;
      z-index: 30;
      box-shadow: var(--shadow-hud);
      overflow: hidden;
      transition: transform 0.3s var(--ease-base);
    }}

    .studio-panel-left.collapsed {{
      transform: translateX(-390px);
    }}

    .panel-header-tabs {{
      display: flex;
      border-bottom: 1px solid var(--border-subtle);
      background: rgba(0, 0, 0, 0.2);
    }}

    .panel-tab {{
      flex: 1;
      padding: 12px 8px;
      font-size: 12px;
      font-weight: 600;
      color: var(--text-muted);
      text-align: center;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      transition: all 0.15s var(--ease-base);
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
    }}

    .panel-tab.active {{
      color: var(--text-main);
      border-bottom-color: var(--accent);
      background: var(--accent-subtle);
    }}

    .panel-body-scroll {{
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}

    .panel-section {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--border-subtle);
    }}

    .panel-section:last-child {{
      border-bottom: none;
    }}

    .panel-section-title {{
      font-size: 11px;
      font-weight: 700;
      color: var(--text-faint);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    /* КОНТРОЛЫ */
    .control-row {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}

    .control-label {{
      font-size: 12px;
      font-weight: 600;
      color: var(--text-main);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}

    .input-text {{
      font-family: var(--font-sans);
      font-size: 13px;
      padding: 7px 10px;
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: var(--bg-input);
      color: var(--text-main);
      width: 100%;
      transition: border-color 0.15s var(--ease-base);
    }}

    .input-text:focus {{
      outline: none;
      border-color: var(--accent);
    }}

    .select-custom {{
      font-family: var(--font-sans);
      font-size: 13px;
      font-weight: 500;
      color: var(--text-main);
      background: var(--bg-input);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      padding: 7px 30px 7px 10px;
      cursor: pointer;
      appearance: none;
      background-image: url("data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2214%22%20height%3D%2214%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22%2394a3b8%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%3E%3Cpolyline%20points%3D%226%209%2012%2015%2018%209%22%3E%3C%2Fpolyline%3E%3C%2Fsvg%3E");
      background-repeat: no-repeat;
      background-position: right 10px center;
    }}

    .slider-container {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    .slider-input {{
      flex: 1;
      height: 4px;
      accent-color: var(--accent);
      cursor: pointer;
      background: var(--bg-input);
      border-radius: var(--radius-full);
    }}

    .slider-badge {{
      font-size: 11px;
      font-weight: 700;
      color: var(--text-main);
      background: var(--bg-input);
      border: 1px solid var(--border-subtle);
      padding: 3px 8px;
      border-radius: var(--radius-sm);
      min-width: 48px;
      text-align: center;
      font-family: var(--font-mono);
    }}

    /* 4. ПРАВЫЙ ПЛАВАЮЩИЙ EXECUTIVE HUD (ЖИВЫЕ ТЭП И ИНСПЕКТОР) */
    .studio-panel-right {{
      position: absolute;
      top: 76px;
      right: 14px;
      bottom: 14px;
      width: 360px;
      background: var(--bg-glass);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-2xl);
      display: flex;
      flex-direction: column;
      z-index: 30;
      box-shadow: var(--shadow-hud);
      overflow: hidden;
      transition: transform 0.3s var(--ease-base);
    }}

    .studio-panel-right.collapsed {{
      transform: translateX(390px);
    }}

    .hud-title-bar {{
      padding: 14px 18px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}

    .hud-title {{
      font-size: 14px;
      font-weight: 700;
      letter-spacing: -0.01em;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .tep-metrics-stream {{
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}

    /* СТУДИЙНЫЕ КАРТОЧКИ ТЭП С ИНДИКАТОРАМИ ЛИМИТОВ */
    .tep-stat-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-lg);
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      transition: all 0.15s var(--ease-base);
    }}

    .tep-stat-card:hover {{
      border-color: var(--border-strong);
      background: var(--bg-card-hover);
    }}

    .tep-stat-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}

    .tep-stat-label {{
      font-size: 11px;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      display: flex;
      align-items: center;
      gap: 5px;
    }}

    .tep-stat-value {{
      font-size: 24px;
      font-weight: 700;
      color: var(--text-main);
      font-family: var(--font-mono);
      letter-spacing: -0.03em;
      line-height: 1.1;
    }}

    .tep-stat-detail {{
      font-size: 11.5px;
      color: var(--text-muted);
      line-height: 1.35;
    }}

    /* МИНИ ПРОГРЕСС-БАР СООТВЕТСТВИЯ */
    .progress-track {{
      width: 100%;
      height: 4px;
      background: var(--bg-input);
      border-radius: var(--radius-full);
      overflow: hidden;
      margin-top: 2px;
    }}

    .progress-fill {{
      height: 100%;
      border-radius: var(--radius-full);
      transition: width 0.4s var(--ease-base);
    }}

    .fill-blue {{ background: var(--accent); }}
    .fill-green {{ background: var(--success); }}
    .fill-orange {{ background: var(--warning); }}

    /* 5. НИЖНИЙ ПЛАВАЮЩИЙ ДОК СЦЕНАРИЕВ (OPTIMIZER DOCK) */
    .studio-bottom-dock {{
      position: absolute;
      bottom: 14px;
      left: 390px;
      right: 390px;
      height: 64px;
      background: var(--bg-glass);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-xl);
      padding: 6px 10px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      z-index: 30;
      box-shadow: var(--shadow-hud);
      transition: all 0.25s var(--ease-base);
    }}

    .scenario-pill {{
      flex: 1;
      height: 100%;
      background: var(--bg-input);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 6px 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      transition: all 0.15s var(--ease-base);
    }}

    .scenario-pill:hover {{
      background: var(--bg-card-hover);
      border-color: var(--border-strong);
    }}

    .scenario-pill.active {{
      background: var(--accent-subtle);
      border-color: var(--accent);
      box-shadow: 0 0 16px rgba(56, 189, 248, 0.2);
    }}

    .scenario-pill-name {{
      font-size: 12px;
      font-weight: 700;
      color: var(--text-main);
    }}

    .scenario-pill-stat {{
      font-size: 11px;
      color: var(--text-muted);
      font-family: var(--font-mono);
    }}

    /* ВЫДВИЖНОЙ НИЖНИЙ ЛОТОК ДЛЯ ПОЛНОЙ ТАБЛИЦЫ (DRAWER) */
    .studio-drawer {{
      position: absolute;
      left: 14px;
      right: 14px;
      bottom: 14px;
      height: 480px;
      background: var(--bg-glass-strong);
      backdrop-filter: blur(28px);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-2xl);
      z-index: 50;
      box-shadow: var(--shadow-hud);
      display: flex;
      flex-direction: column;
      transform: translateY(calc(100% + 20px));
      transition: transform 0.35s var(--ease-base);
    }}

    .studio-drawer.open {{
      transform: translateY(0);
    }}

    .drawer-header {{
      padding: 16px 20px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}

    .drawer-body {{
      flex: 1;
      overflow-y: auto;
      padding: 20px;
    }}

    /* МОДАЛКА */
    .modal-backdrop {{
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.8);
      backdrop-filter: blur(12px);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 100;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.2s var(--ease-base);
    }}

    .modal-backdrop.active {{
      opacity: 1;
      pointer-events: auto;
    }}

    .modal-box {{
      background: var(--bg-card);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-2xl);
      max-width: 720px;
      width: 90%;
      max-height: 85vh;
      display: flex;
      flex-direction: column;
      box-shadow: var(--shadow-hud);
      overflow: hidden;
    }}

    .modal-header {{
      padding: 16px 20px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }}

    .modal-body {{
      padding: 20px;
      overflow-y: auto;
      font-family: var(--font-mono);
      font-size: 12px;
      line-height: 1.6;
      white-space: pre-wrap;
      color: var(--text-main);
    }}

    .toast-msg {{
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: var(--bg-card);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-lg);
      padding: 10px 16px;
      color: var(--text-main);
      font-size: 13px;
      font-weight: 500;
      box-shadow: var(--shadow-hud);
      z-index: 200;
      transform: translateY(100px);
      opacity: 0;
      transition: all 0.25s var(--ease-base);
    }}

    .toast-msg.show {{
      transform: translateY(0);
      opacity: 1;
    }}
  </style>
</head>
<body>

<div class="studio-app">

  <!-- 1. ВЕРХНИЙ ПЛАВАЮЩИЙ ХЕДЕР -->
  <header class="studio-command-bar">
    <div class="studio-brand">
      <div class="studio-logo">
        <i class="ph-bold ph-cube"></i>
      </div>
      <div>
        <div class="studio-title">
          FORMA STUDIO <span class="badge-pro">ТЭП</span>
        </div>
      </div>
      <div class="project-pill" id="project-info-pill">
        <i class="ph ph-map-pin"></i>
        <span>Самара, 4.25 га</span>
        <span style="opacity:0.4;">|</span>
        <span id="site-cad-label" style="font-family:var(--font-mono);">63:01:0814002:1248</span>
      </div>
    </div>

    <!-- РЕЖИМЫ ОТОБРАЖЕНИЯ ХОЛСТА (ЦЕНТР) -->
    <div class="viewport-modes">
      <button class="view-tab-btn active" id="tab-svg">
        <i class="ph ph-blueprint"></i> 2D Генплан
      </button>
      <button class="view-tab-btn" id="tab-osm">
        <i class="ph ph-map-trifold"></i> OSM Спутник
      </button>
      <button class="view-tab-btn" id="tab-3d">
        <i class="ph ph-cube"></i> 3D Модель
      </button>
    </div>

    <!-- ДЕЙСТВИЯ СПРАВА -->
    <div class="command-actions">
      <select class="select-custom" id="map-metric-select" style="font-size:12px; padding:5px 24px 5px 8px;">
        <option value="category">Слой: Типы секций</option>
        <option value="floors">Слой: Этажность</option>
        <option value="building">Слой: Корпуса</option>
        <option value="gfa">Слой: Площадь GFA</option>
      </select>

      <a class="btn-studio" id="btn-export-dxf" href="/api/export/dxf" download="plan_cad.dxf" title="Скачать чертеж в формате AutoCAD">
        <i class="ph ph-file-dashed"></i> DXF
      </a>

      <button class="btn-studio btn-studio-primary" id="btn-run-pipeline" title="Запустить оптимизацию и расчет ТЭП">
        <i class="ph-bold ph-sparkle"></i>
        <span>Сгенерировать ТЭП</span>
      </button>

      <button class="hud-btn" id="btn-toggle-left" title="Скрыть/показать левую панель">
        <i class="ph ph-sidebar-simple"></i>
      </button>
    </div>
  </header>

  <!-- 2. ХОЛСТ (ПОЛНОЭКРАННЫЙ VIEWPORT) -->
  <main class="studio-canvas-stage">
    <div id="view-container-svg">
      <svg class="map-svg" id="masterplan-svg" role="img" aria-label="Интерактивный генплан">
        <g id="svg-viewport">
          <g id="svg-site-world">
            <path id="svg-site-bound" class="svg-site-boundary" />
            <path id="svg-buildable" class="svg-buildable-area" />
            <g id="svg-redlines-group"></g>
            <g id="svg-roads-group"></g>
            <g id="svg-subblocks-group"></g>
            <g id="svg-road-draw-preview"></g>
            <g id="svg-sections-group"></g>
          </g>
        </g>
      </svg>
    </div>

    <div id="view-container-osm" style="display:none;">
      <iframe id="iframe-osm" style="width:100%; height:100%; border:0;" title="OSM Карта"></iframe>
    </div>

    <div id="view-container-3d" style="display:none;">
      <iframe id="iframe-3d" src="viewer_3d.html" style="width:100%; height:100%; border:0;" title="3D Модель"></iframe>
    </div>

    <!-- ПЛАВАЮЩИЕ ИНСТРУМЕНТЫ ВЬЮПОРТА -->
    <div class="viewport-floating-tools">
      <button class="hud-btn" id="btn-draw-road" title="Начертить улицу поперек участка"><i class="ph ph-road-horizon"></i></button>
      <button class="hud-btn" id="btn-zoom-in" title="Приблизить"><i class="ph ph-plus"></i></button>
      <button class="hud-btn" id="btn-zoom-out" title="Отдалить"><i class="ph ph-minus"></i></button>
      <button class="hud-btn" id="btn-zoom-reset" title="Показать весь участок"><i class="ph ph-arrows-out-cardinal"></i></button>
      <button class="hud-btn" id="btn-zoom-focus" title="Фокус на секции"><i class="ph ph-crosshair"></i></button>
    </div>

    <div class="hud-compass">
      <i class="ph ph-arrow-up"></i>
      <span>С</span>
    </div>

    <div class="hud-legend" id="map-legend">
      <strong id="legend-title" style="font-weight:700;">Типы секций</strong>
      <div id="legend-items" style="margin-top:4px;"></div>
    </div>

    <div class="map-tooltip" id="map-tooltip"></div>
  </main>

  <!-- 3. ЛЕВАЯ ПЛАВАЮЩАЯ ПАНЕЛЬ: СТУДИЙНЫЕ ПАРАМЕТРЫ -->
  <aside class="studio-panel-left" id="settings-drawer">
    <div class="panel-header-tabs">
      <div class="panel-tab active" id="tab-settings-site">
        <i class="ph ph-compass"></i> Участок
      </div>
      <div class="panel-tab" id="tab-settings-concept">
        <i class="ph ph-cube"></i> Концепция
      </div>
      <div class="panel-tab" id="tab-settings-norms">
        <i class="ph ph-scales"></i> Нормы
      </div>
    </div>

    <div class="panel-body-scroll">
      <!-- 1. ПОСАДКА И УЧАСТОК -->
      <div class="panel-section">
        <span class="panel-section-title"><i class="ph ph-map-pin"></i> 1. Контур и привязка</span>
        
        <div class="control-row">
          <label class="control-label" for="cfg-parcel-presets">Готовые пресеты</label>
          <select class="select-custom" id="cfg-parcel-presets" style="width:100%;">
            <option value="samara_4ha">Самара · Смешанный квартал 4.25 га</option>
            <option value="tyumen_aquatoria">Тюмень · ЖК «Акватория» (Тура, 7.8 га)</option>
            <option value="kazan_port">Казань · Новая Портовая (12.4 га)</option>
            <option value="spb_polyana">СПб · Каменка / Комендантский (6.1 га)</option>
          </select>
        </div>

        <div class="control-row">
          <label class="control-label" for="cfg-cad-input">Кадастровый номер</label>
          <input type="text" class="input-text" id="cfg-cad-input" value="63:01:0814002:1248" />
        </div>

        <div class="control-row">
          <label class="control-label" for="cfg-area-input">Площадь участка (га)</label>
          <input type="number" class="input-text" id="cfg-area-input" value="4.25" step="0.05" />
        </div>

        <!-- ПОВОРОТ УЧАСТКА -->
        <div class="control-row" style="margin-top:6px;">
          <div class="control-label">
            <span>Ориентация участка</span>
            <span class="slider-badge" id="cfg-rot-badge">0°</span>
          </div>
          <div class="slider-container">
            <input type="range" class="slider-input" id="cfg-rot-slider" min="0" max="360" step="1" value="0" />
          </div>
          <div class="rot-buttons-row" style="display:flex; gap:4px; margin-top:4px;">
            <button type="button" class="btn-studio btn-rot" data-step="-15" style="flex:1; padding:3px 0; justify-content:center;">-15°</button>
            <button type="button" class="btn-rot btn-studio" data-step="0" style="flex:1.4; padding:3px 0; justify-content:center;">Сброс</button>
            <button type="button" class="btn-studio btn-rot" data-step="15" style="flex:1; padding:3px 0; justify-content:center;">+15°</button>
          </div>
        </div>

        <button class="btn-studio btn-studio-primary" id="btn-lock-sidebar" type="button" style="width:100%; margin-top:6px; justify-content:center;">
          <i class="ph ph-lock-key"></i> Зафиксировать посадку
        </button>
      </div>

      <!-- 2. КОНЦЕПЦИЯ И ТИПОЛОГИЯ -->
      <div class="panel-section">
        <span class="panel-section-title"><i class="ph ph-buildings"></i> 2. Типология застройки</span>
        
        <div class="control-row">
          <label class="control-label" for="cfg-typology">Мастер-план форма</label>
          <select class="select-custom" id="cfg-typology" style="width:100%;">
            <option value="AUTO">Квартальная / Смешанная (AUTO)</option>
            <option value="PERIMETER">Периметральные урбан-блоки (R2)</option>
            <option value="TOWER">Точечная / Башни (Towers)</option>
            <option value="U_SHAPE">П-образные дворы (U-Shape)</option>
            <option value="LINEAR">Линейная застройка (Пластины)</option>
          </select>
        </div>

        <div class="control-row">
          <label class="control-label" for="cfg-road-preset">Нарезка улично-дорожной сетью</label>
          <select class="select-custom" id="cfg-road-preset" style="width:100%;">
            <option value="none">Без внутренних улиц (1 квартал)</option>
            <option value="longitudinal">1 продольный бульвар</option>
            <option value="transverse">1 поперечный проезд</option>
            <option value="cross_2x2">Сетка крестом 2×2 (4 квартала)</option>
          </select>
        </div>
      </div>

      <!-- 3. ЭТАЖНОСТЬ И НОРМАТИВЫ -->
      <div class="panel-section">
        <span class="panel-section-title"><i class="ph ph-chart-bar"></i> 3. Целевые параметры</span>
        
        <div class="control-row">
          <div class="control-label">
            <span>Целевая этажность</span>
            <span class="slider-badge" id="cfg-floors-badge">14 эт.</span>
          </div>
          <div class="slider-container">
            <input type="range" class="slider-input" id="cfg-floors-slider" min="3" max="30" step="1" value="14" />
          </div>
        </div>

        <div class="control-row">
          <label class="control-label" for="cfg-regional-norm">Норматив проектирования</label>
          <select class="select-custom" id="cfg-regional-norm" style="width:100%;">
            <option value="russia_sp42">СП 42.13330.2016 (Федеральный)</option>
            <option value="moscow_mngp">Москва — МНГП</option>
            <option value="moscow_oblast_rngp">Московская область — РНГП</option>
            <option value="spb_rngp">Санкт-Петербург — РНГП</option>
          </select>
        </div>
      </div>
    </div>
  </aside>

  <!-- 4. ПРАВЫЙ ПЛАВАЮЩИЙ EXECUTIVE HUD (ЖИВЫЕ ТЭП) -->
  <aside class="studio-panel-right" id="tep-hud">
    <div class="hud-title-bar">
      <div class="hud-title">
        <i class="ph ph-chart-polar"></i>
        <span>Архитектурные ТЭП</span>
      </div>
      <button class="hud-btn" id="btn-toggle-right" style="width:28px; height:28px; font-size:14px;">
        <i class="ph ph-x"></i>
      </button>
    </div>

    <div class="tep-metrics-stream">
      <!-- 1. GFA -->
      <div class="tep-stat-card">
        <div class="tep-stat-top">
          <span class="tep-stat-label"><i class="ph ph-buildings"></i> GFA (Общая площадь)</span>
          <span class="badge-status badge-ok" id="kpi-gfa-badge">Норма</span>
        </div>
        <div class="tep-stat-value" id="kpi-gfa">105 365 м²</div>
        <div class="tep-stat-detail" id="kpi-gfa-desc">Жилая: 70 193 м² · Нежилая: 3 623 м²</div>
      </div>

      <!-- 2. FAR (ПЛОТНОСТЬ) -->
      <div class="tep-stat-card">
        <div class="tep-stat-top">
          <span class="tep-stat-label"><i class="ph ph-chart-bar"></i> Плотность (FAR)</span>
          <span style="font-family:var(--font-mono); font-size:11px; color:var(--accent);">Лимит: 2.50</span>
        </div>
        <div class="tep-stat-value" id="kpi-far">2.37</div>
        <div class="progress-track">
          <div class="progress-fill fill-blue" style="width: 94%;"></div>
        </div>
        <div class="tep-stat-detail" id="kpi-far-desc">СП 42: Норма соблюдена</div>
      </div>

      <!-- 3. BCR (ПРОЦЕНТ ЗАСТРОЙКИ) -->
      <div class="tep-stat-card">
        <div class="tep-stat-top">
          <span class="tep-stat-label"><i class="ph ph-polygon"></i> Застройка (BCR)</span>
          <span style="font-family:var(--font-mono); font-size:11px; color:var(--success);">Лимит: 40%</span>
        </div>
        <div class="tep-stat-value" id="kpi-bcr">23.5%</div>
        <div class="progress-track">
          <div class="progress-fill fill-green" style="width: 58%;"></div>
        </div>
        <div class="tep-stat-detail" id="kpi-bcr-desc">Пятно застройки: 10 449 м²</div>
      </div>

      <!-- 4. КВАРТИРОГРАФИЯ -->
      <div class="tep-stat-card">
        <div class="tep-stat-top">
          <span class="tep-stat-label"><i class="ph ph-house-line"></i> Жилой фонд</span>
          <span style="font-family:var(--font-mono); font-size:11px; color:var(--text-muted);" id="kpi-living">1 248 кв.</span>
        </div>
        <div class="tep-stat-value" id="kpi-pop">2 340 чел.</div>
        <div class="tep-stat-detail" id="kpi-living-desc">Студии: 544 · 2К: 64 · 3К: 576 · 4К: 64</div>
      </div>

      <!-- 5. ПАРКОВКИ И БАЛАНС -->
      <div class="tep-stat-card">
        <div class="tep-stat-top">
          <span class="tep-stat-label"><i class="ph ph-car"></i> Парковки (РНГП)</span>
          <span class="badge-status badge-ok" id="kpi-parking-badge">100% норма</span>
        </div>
        <div class="tep-stat-value" id="kpi-parking">1 150 м/м</div>
        <div class="tep-stat-detail" id="kpi-parking-desc">Наземных: 420 · Подземных: 730</div>
      </div>

      <!-- ИНСПЕКТОР СЕКЦИИ (ДИНАМИЧЕСКИЙ) -->
      <div id="inspector-content" style="margin-top:8px; border-top:1px solid var(--border-subtle); padding-top:12px;">
        <div id="inspector-empty" style="text-align:center; padding:16px; color:var(--text-faint);">
          <i class="ph ph-cursor-click" style="font-size:24px; color:var(--accent); margin-bottom:6px; display:inline-block;"></i>
          <div>Кликните любую секцию на плане для инспекции параметров</div>
        </div>
        <div id="inspector-data" style="display:none; flex-direction:column; gap:8px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong id="insp-section-name" style="font-size:14px;">Секция 1</strong>
            <span class="badge-status badge-info" id="insp-floors-badge">14 эт.</span>
          </div>
          <div style="font-size:11.5px; color:var(--text-muted);" id="insp-gfa">GFA: —</div>
          <div style="font-size:11px; color:var(--text-faint);" id="insp-apts-breakdown">—</div>
        </div>
      </div>
    </div>
  </aside>

  <!-- 5. НИЖНИЙ ПЛАВАЮЩИЙ ДОК: 4 СЦЕНАРИЯ ЭТАЖНОСТИ (OPTIMIZER DOCK) -->
  <footer class="studio-bottom-dock">
    <div class="scenario-pill active" id="scenario-pill-1" title="Активировать этот высотный сценарий">
      <div>
        <div class="scenario-pill-name">Вариант 1 · Баланс 14 эт.</div>
        <div class="scenario-pill-stat">FAR 2.37 · 105k GFA · 1248 кв.</div>
      </div>
      <i class="ph-bold ph-check-circle" style="color:var(--accent);"></i>
    </div>

    <div class="scenario-pill" id="scenario-pill-2" title="Активировать этот высотный сценарий">
      <div>
        <div class="scenario-pill-name">Вариант 2 · Средняя 9 эт.</div>
        <div class="scenario-pill-stat">FAR 1.62 · 72k GFA · 840 кв.</div>
      </div>
      <i class="ph ph-circle" style="color:var(--text-faint);"></i>
    </div>

    <div class="scenario-pill" id="scenario-pill-3" title="Активировать этот высотный сценарий">
      <div>
        <div class="scenario-pill-name">Вариант 3 · Высотный 22 эт.</div>
        <div class="scenario-pill-stat">FAR 3.10 · 138k GFA · 1620 кв.</div>
      </div>
      <i class="ph ph-circle" style="color:var(--text-faint);"></i>
    </div>

    <div class="scenario-pill" id="scenario-pill-4" title="Активировать этот высотный сценарий">
      <div>
        <div class="scenario-pill-name">Вариант 4 · Каскад 8–16 эт.</div>
        <div class="scenario-pill-stat">FAR 2.15 · 94k GFA · 1120 кв.</div>
      </div>
      <i class="ph ph-circle" style="color:var(--text-faint);"></i>
    </div>

    <button class="btn-studio" id="btn-open-tray" style="height:100%; border-radius:var(--radius-md);" title="Открыть полную ведомость и баланс РНГП">
      <i class="ph ph-table"></i>
      <span>Ведомости</span>
    </button>
  </footer>

  <!-- 6. ВЫДВИЖНОЙ НИЖНИЙ ЛОТОК ВЕДОМОСТЕЙ -->
  <div class="studio-drawer" id="studio-drawer">
    <div class="drawer-header">
      <div style="font-size:15px; font-weight:700; display:flex; align-items:center; gap:8px;">
        <i class="ph ph-table"></i>
        <span>Ведомость корпусов и градостроительный баланс (РНГП)</span>
      </div>
      <div style="display:flex; align-items:center; gap:10px;">
        <button class="btn-studio" id="btn-show-report"><i class="ph ph-file-text"></i> Текстовый отчет</button>
        <button class="hud-btn" id="btn-close-tray"><i class="ph ph-x"></i></button>
      </div>
    </div>
    <div class="drawer-body">
      <table class="data-table" style="width:100%; font-size:12px;">
        <thead>
          <tr>
            <th>Элемент баланса</th>
            <th>Норматив РНГП</th>
            <th>Требуется (м²)</th>
            <th>Фактически (м²)</th>
            <th>Статус</th>
          </tr>
        </thead>
        <tbody id="territorial-balance-body"></tbody>
      </table>
    </div>
  </div>

</div>

<!-- МОДАЛЬНОЕ ОКНО ОТЧЕТА -->
<div class="modal-backdrop" id="report-modal">
  <div class="modal-box">
    <div class="modal-header">
      <strong style="font-size:14px;"><i class="ph ph-file-text"></i> Отчет по ТЭП и нормативным балансам</strong>
      <button class="hud-btn" id="modal-close-btn" style="border:none;"><i class="ph ph-x"></i></button>
    </div>
    <div class="modal-body" id="modal-report-text">Загрузка данных...</div>
  </div>
</div>

<div class="toast-msg" id="toast-msg"></div>

<script type="application/json" id="scenarios-data">{data_json_str}</script>
<script type="application/json" id="catalog-data">{catalog_json_str}</script>

<!-- КЛИЕНТСКИЙ СКРИПТ -->
<script>
{client_js}

// ДОПОЛНИТЕЛЬНЫЕ ИНТЕРАКТИВНЫЕ ОБРАБОТЧИКИ СТУДИЙНОГО ИНТЕРФЕЙСА
(function() {{
  const btnToggleLeft = document.getElementById("btn-toggle-left");
  const panelLeft = document.getElementById("settings-drawer");
  const btnToggleRight = document.getElementById("btn-toggle-right");
  const panelRight = document.getElementById("tep-hud");
  const btnOpenTray = document.getElementById("btn-open-tray");
  const btnCloseTray = document.getElementById("btn-close-tray");
  const drawer = document.getElementById("studio-drawer");

  if (btnToggleLeft && panelLeft) {{
    btnToggleLeft.addEventListener("click", () => {{
      panelLeft.classList.toggle("collapsed");
    }});
  }}

  if (btnToggleRight && panelRight) {{
    btnToggleRight.addEventListener("click", () => {{
      panelRight.classList.toggle("collapsed");
    }});
  }}

  if (btnOpenTray && drawer) {{
    btnOpenTray.addEventListener("click", () => {{
      drawer.classList.add("open");
    }});
  }}

  if (btnCloseTray && drawer) {{
    btnCloseTray.addEventListener("click", () => {{
      drawer.classList.remove("open");
    }});
  }}

  // Сценарии в нижнем доке
  const pills = document.querySelectorAll(".scenario-pill");
  pills.forEach((p, idx) => {{
    p.addEventListener("click", () => {{
      pills.forEach(x => {{
        x.classList.remove("active");
        const icon = x.querySelector("i");
        if (icon) {{ icon.className = "ph ph-circle"; icon.style.color = "var(--text-faint)"; }}
      }});
      p.classList.add("active");
      const activeIcon = p.querySelector("i");
      if (activeIcon) {{ activeIcon.className = "ph-bold ph-check-circle"; activeIcon.style.color = "var(--accent)"; }}
    }});
  }});
}})();
</script>

</body>
</html>
"""

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Готово! Новый Studio CAD-интерфейс собран в {OUT_HTML} ({len(html)} символов).")


if __name__ == "__main__":
    build()
