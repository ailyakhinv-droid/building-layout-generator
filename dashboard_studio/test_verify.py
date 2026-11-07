"""Проверка наличия всех 100% элементов управления и слоев в Studio HTML."""
from pathlib import Path
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
STUDIO_HTML = ROOT / "dashboard_studio" / "index.html"

with open(STUDIO_HTML, "r", encoding="utf-8") as f:
    html = f.read()

required_ids = [
    # Слои и кнопки генплана
    'btn-toggle-fire-roads', 'btn-toggle-tko', 'btn-toggle-parking-slots', 'btn-toggle-parking-san',
    'btn-draw-road', 'map-metric-select', 'btn-zoom-in', 'btn-zoom-out', 'btn-zoom-reset', 'btn-zoom-focus', 'btn-fullscreen-map',
    # SVG-группы слоев
    'svg-site-bound', 'svg-buildable', 'svg-zouit-group', 'svg-redlines-group', 'svg-roads-group', 'svg-subblocks-group',
    'svg-parking-group', 'svg-fire-roads-group', 'svg-parking-san-group', 'svg-tko-group', 'svg-road-draw-preview', 'svg-sections-group',
    # Инспектор
    'inspector-card-container', 'inspector-content', 'insp-title', 'insp-floors', 'insp-gfa', 'insp-apt-bars', 'insp-elevators',
    # Верхние KPI и HUD
    'kpi-hud-bar', 'full-kpi-grid', 'kpi-gfa', 'kpi-far', 'kpi-bcr', 'kpi-parking', 'kpi-green', 'kpi-pop',
    # Нижний док и его вкладки
    'studio-bottom-dock', 'btn-dock-toggle', 'btn-dock-expand',
    'pane-kpi-balance', 'pane-apts', 'pane-variants', 'pane-catalog', 'pane-sections-table',
    # Баланс РНГП
    'balance-region-label', 'bal-parking-req', 'bal-fire-val', 'balance-progress-list',
    # Квартирография
    'apts-progress-list', 'buildings-apt-table',
    # Варианты высотности
    'btn-calc-variants', 'variants-data-table', 'variants-table-body',
    # Каталог и ведомость
    'catalog-grid', 'table-search', 'table-sections-body',
    # Экспорт
    'btn-export-dxf', 'btn-export-3d', 'btn-export-geojson', 'btn-show-report',
    # Параметры слева
    'cfg-cad-input', 'cfg-parcel-presets', 'btn-fetch-pkk', 'btn-digitize-map', 'dropzone-gpzu',
    'cfg-floors-slider', 'cfg-typology', 'cfg-cascade-floors', 'cfg-court-orient'
]

missing = [i for i in required_ids if f'id="{i}"' not in html and f"id='{i}'" not in html and f'data-pane="{i}"' not in html]

print(f"Всего проверено ключевых элементов: {len(required_ids)}")
if missing:
    print("ВНИМАНИЕ! Пропущены элементы:", missing)
else:
    print("УСПЕХ! Все 100% элементов управления, слоев, инспекторов, таблиц и экспортов присутствуют в DOM!")
