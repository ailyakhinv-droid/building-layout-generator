"""Модуль интерактивной 3D-визуализации застройки на базе MapLibre GL JS.

Создает автономную 3D-сцену в формате HTML с возможностью:
- 3D-экструзии жилых корпусов и секций с учетом реальной этажности и высоты этажа;
- Отображения границ участка, зоны допустимой застройки и красных линий;
- Динамического переключения подложек (нейтральный архитектурный холст, светлая Positron, тёмная Dark);
- Тематической раскраски зданий (по этажности, по корпусам, по типам секций, нейтральная архитектурная);
- Интерактивной фильтрации по этажности;
- Информационных всплывающих карточек ТЭП при клике на здания;
- Полноценного 3D-управления камерой (наклон, вращение, зум).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import shapely
from shapely.geometry import mapping

from src.core.geo_utils import transform_geometry_to_wgs84
from src.models.building import Building
from src.models.site import Site
from src.models.tep import TEP


# Палитра для дифференциации корпусов
BUILDING_PALETTE = [
    "#2E86AB",  # Глубокий синий
    "#F18F01",  # Теплый янтарный
    "#2ECC71",  # Изумрудный
    "#9B59B6",  # Аметистовый
    "#E74C3C",  # Коралловый
    "#1ABC9C",  # Бирюзовый
    "#E67E22",  # Оранжевый
    "#34495E",  # Графитовый
]

# Цвета для категорий типовых секций
CATEGORY_COLORS = {
    "MIDDLE": "#2E86AB",  # Рядовая секция (синий)
    "CORNER": "#E67E22",  # Угловая секция (терракотовый)
    "END": "#8E44AD",     # Торцевая секция (фиолетовый)
    "TOWER": "#9B59B6",   # Точечная башня (аметистовый/пурпурный)
}

CATEGORY_NAMES = {
    "MIDDLE": "Рядовая",
    "CORNER": "Угловая",
    "END": "Торцевая",
    "TOWER": "Точечная (башня)",
}


def _is_wgs84_geometry(geom: shapely.Geometry) -> bool:
    """Проверить, являются ли координаты геометрии реальными градусами WGS-84."""
    minx, miny, maxx, maxy = geom.bounds
    # Геометрия в WGS-84 градусах имеет характерную маленькую площадь в градусах (< 0.05 кв. град. для участка)
    # и координаты, соответствующие географическим широтам/долготам РФ и Евразии (долгота 15..180, широта 35..85).
    # Локальные метры участка (0..500 м) НЕ должны ошибочно определяться как градусы!
    is_deg_range = -180.0 <= minx <= 180.0 and -180.0 <= maxx <= 180.0 and -90.0 <= miny <= 90.0 and -90.0 <= maxy <= 90.0
    is_small_degree_area = geom.area < 0.05
    is_far_from_origin = (abs(minx) > 15.0 and abs(miny) > 30.0)
    return is_deg_range and is_small_degree_area and is_far_from_origin


def _to_wgs84(geom: shapely.Geometry, center_lat: float, center_lon: float) -> shapely.Geometry:
    """Перевести геометрию в WGS-84 только если она в локальных метрах."""
    if _is_wgs84_geometry(geom):
        return geom
    return transform_geometry_to_wgs84(geom, center_lat, center_lon)


def _get_site_geo_center(site: Site, fallback_center: tuple[float, float] | None = None) -> tuple[float, float]:
    """Получить географический центр для привязки координат (lat, lon)."""
    if site.geo_center:
        return site.geo_center
    if _is_wgs84_geometry(site.boundary):
        c = site.boundary.centroid
        return (c.y, c.x)
    if fallback_center:
        return fallback_center
    # Резервная точка отсчета (Москва) вместо Санкт-Петербурга
    return (55.751244, 37.618423)


def build_3d_geojson_data(
    site: Site,
    buildings: list[Building] | None = None,
    tep: TEP | None = None,
) -> dict[str, Any]:
    """Сформировать словарь GeoJSON-слоев для 3D-визуализации."""
    center_lat, center_lon = _get_site_geo_center(site)

    # 1. Граница участка
    boundary_wgs = _to_wgs84(site.boundary, center_lat, center_lon)
    boundary_feature = {
        "type": "Feature",
        "geometry": mapping(boundary_wgs),
        "properties": {
            "type": "boundary",
            "name": "Граница земельного участка",
            "cadastral_number": site.cadastral_number or "Не указан",
            "address": site.address or "Локальный участок",
            "area": round(site.area, 1),
            "area_ha": round(site.area / 10000.0, 2),
        },
    }

    # 2. Зона допустимой застройки
    buildable_feature = None
    if site.buildable_area and not site.buildable_area.is_empty:
        buildable_wgs = _to_wgs84(site.buildable_area, center_lat, center_lon)
        buildable_feature = {
            "type": "Feature",
            "geometry": mapping(buildable_wgs),
            "properties": {
                "type": "buildable",
                "name": "Зона допустимой застройки",
                "area": round(site.buildable_area.area, 1),
            },
        }

    # 3. Красные линии
    red_line_features = []
    for idx, rl in enumerate(site.red_lines):
        rl_wgs = _to_wgs84(rl, center_lat, center_lon)
        red_line_features.append({
            "type": "Feature",
            "geometry": mapping(rl_wgs),
            "properties": {
                "type": "red_line",
                "name": f"Красная линия {idx + 1}",
                "id": idx + 1,
            },
        })

    # 4. Секции зданий (3D экструзия)
    building_features = []
    if buildings:
        for b_idx, b in enumerate(buildings):
            b_color = BUILDING_PALETTE[b_idx % len(BUILDING_PALETTE)]
            b_apts = sum(b.total_apartments.values())
            b_gfa = b.total_gfa
            b_max_h = b.height

            for s_idx, sec in enumerate(b.sections):
                sec_wgs = _to_wgs84(sec.footprint, center_lat, center_lon)
                sec_type = sec.section_type
                cat = sec_type.category
                cat_color = CATEGORY_COLORS.get(cat, "#2E86AB")
                cat_name = CATEGORY_NAMES.get(cat, cat)

                sec_floors = sec.floors
                sec_height = round(sec.height, 2)
                floor_h = round(sec.effective_floor_height, 2)
                sec_footprint = round(sec.footprint.area, 1)
                sec_gfa = round(sec.gfa, 1)
                sec_living = round(sec_gfa * 0.72, 1)
                sec_apts = sum(sec_type.apartments_per_floor.values()) * sec_floors

                building_features.append({
                    "type": "Feature",
                    "geometry": mapping(sec_wgs),
                    "properties": {
                        "id": f"{b_idx + 1}_{s_idx + 1}",
                        "building_id": b_idx + 1,
                        "section_index": s_idx + 1,
                        "building_name": f"Корпус {b_idx + 1}",
                        "section_name": sec_type.name,
                        "full_name": f"Корпус {b_idx + 1}, Секция {s_idx + 1} ({sec_type.name})",
                        "category": cat,
                        "category_name": cat_name,
                        "floors": sec_floors,
                        "levels": sec_floors,
                        "height": sec_height,
                        "height_m": sec_height,
                        "floor_height": floor_h,
                        "min_height": 0.0,
                        "footprint_area": sec_footprint,
                        "gfa": sec_gfa,
                        "living_area": sec_living,
                        "apartments": sec_apts,
                        "has_commercial": sec_type.has_commercial_ground,
                        "building_floors": b.floors,
                        "building_height": round(b_max_h, 2),
                        "building_gfa": round(b_gfa, 1),
                        "building_apartments": b_apts,
                        "building_sections": len(b.sections),
                        "building_typology": b.typology,
                        "color_building": b_color,
                        "color_category": cat_color,
                    },
                })

    # 5. Внутриквартальные дороги (Улично-дорожная сеть)
    road_features = []
    roads_result = getattr(site, "roads_result", None)
    if roads_result and getattr(roads_result, "roads_polygon", None):
        r_poly = roads_result.roads_polygon
        if not r_poly.is_empty:
            r_wgs = _to_wgs84(r_poly, center_lat, center_lon)
            road_features.append({
                "type": "Feature",
                "geometry": mapping(r_wgs),
                "properties": {
                    "type": "road_corridor",
                    "name": "Проезжая часть / Внутриквартальная улица",
                    "area": round(r_poly.area, 1),
                },
            })
        if getattr(roads_result, "buffer_polygon", None) and not roads_result.buffer_polygon.is_empty:
            buf_poly = roads_result.buffer_polygon
            buf_wgs = _to_wgs84(buf_poly, center_lat, center_lon)
            road_features.append({
                "type": "Feature",
                "geometry": mapping(buf_wgs),
                "properties": {
                    "type": "road_buffer",
                    "name": f"Техническая зона / отступ {getattr(roads_result, 'road_setback', 4)} м",
                    "area": round(buf_poly.area, 1),
                },
            })
        for idx, cl in enumerate(getattr(roads_result, "centerlines", [])):
            if not cl.is_empty:
                cl_wgs = _to_wgs84(cl, center_lat, center_lon)
                road_features.append({
                    "type": "Feature",
                    "geometry": mapping(cl_wgs),
                    "properties": {
                        "type": "road_centerline",
                        "name": f"Ось улицы {idx + 1}",
                    },
                })

    return {
        "boundary": {"type": "FeatureCollection", "features": [boundary_feature]},
        "buildable": {"type": "FeatureCollection", "features": [buildable_feature] if buildable_feature else []},
        "red_lines": {"type": "FeatureCollection", "features": red_line_features},
        "roads": {"type": "FeatureCollection", "features": road_features},
        "buildings": {"type": "FeatureCollection", "features": building_features},
    }


def generate_3d_viewer_html(
    site: Site,
    buildings: list[Building] | None = None,
    tep: TEP | None = None,
    title: str = "3D-визуализация застройки участка",
    height: int | str = 600,
    default_basemap: str = "osm",
    standalone: bool = False,
) -> str:
    """Сгенерировать HTML-код интерактивного 3D-вьюера на MapLibre GL JS.

    Args:
        site: Земельный участок (Site).
        buildings: Список размещенных зданий (Building).
        tep: Рассчитанные ТЭП участка (TEP).
        title: Название проекта или страницы.
        height: Высота карты в пикселях или строкой (например, '100%').
        default_basemap: Начальная подложка ('osm', 'light', 'satellite', 'dark', 'none').
        standalone: Если True — готовый полноэкранный HTML-документ для сохранения в файл.

    Returns:
        Строка с полным HTML кодом страницы.
    """
    layers_data = build_3d_geojson_data(site, buildings, tep)
    data_json_str = json.dumps(layers_data, ensure_ascii=False)

    site_area = round(site.area, 1)
    site_area_ha = round(site.area / 10000.0, 2)
    cadastral_no = site.cadastral_number or "Не указан"

    b_count = len(buildings) if buildings else 0
    s_count = sum(len(b.sections) for b in buildings) if buildings else 0

    if tep:
        footprint_sum = round(getattr(tep, "building_area", getattr(tep, "footprint_area", 0.0)), 1)
        bcr_pct = f"{tep.bcr:.1%}"
        gfa_sum = round(getattr(tep, "total_gfa", getattr(tep, "gfa_total", 0.0)), 1)
        living_sum = round(getattr(tep, "residential_area", getattr(tep, "living_area_total", 0.0)), 1)
        far_val = f"{tep.far:.2f}"
        pop_num = getattr(tep, "population", getattr(tep, "population_total", 0))
        population_val = f"{pop_num:,}".replace(",", " ")
        apts_val = str(tep.apartments_total)
        parking_num = getattr(tep, "parking_spaces", getattr(tep, "parking_places_total", 0))
        parking_val = str(parking_num)
        gr_val = getattr(tep, "green_ratio", getattr(tep, "greenery_ratio", 0.0))
        green_pct = f"{gr_val:.1%}"
        af_val = getattr(tep, "avg_floors", getattr(tep, "average_floors", 0.0))
        avg_floors = f"{af_val:.1f}"
    else:
        footprint_sum = 0
        bcr_pct = "—"
        gfa_sum = 0
        living_sum = 0
        far_val = "—"
        population_val = "—"
        apts_val = "—"
        parking_val = "—"
        green_pct = "—"
        avg_floors = "—"

    if isinstance(height, str) and (height.endswith("px") or height.endswith("vh") or height.endswith("%")):
        height_style = height
    elif standalone or height == "100%":
        height_style = "100vh"
    else:
        height_style = f"{height}px"

    html = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/maplibre-gl@5.6.0/dist/maplibre-gl.css">
  <script src="https://cdn.jsdelivr.net/npm/maplibre-gl@5.6.0/dist/maplibre-gl.js"></script>
  <style>
    :root {{
      --ink: #1e293b;
      --muted: #64748b;
      --border: #e2e8f0;
      --panel-bg: rgba(255, 255, 255, 0.96);
      --accent: #2563eb;
      --accent-hover: #1d4ed8;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{
      height: 100%;
      margin: 0;
      padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      color: var(--ink);
      background: #f4f2ed;
      overflow: hidden;
    }}
    #map-container {{
      position: relative;
      width: 100%;
      height: {height_style};
      min-height: 480px;
      background: #f4f2ed;
    }}
    #map {{
      position: absolute;
      top: 0;
      bottom: 0;
      left: 0;
      right: 0;
      background: #f4f2ed;
    }}
    .panel-toggle-btn {{
      position: absolute;
      top: 14px;
      left: 14px;
      z-index: 30;
      background: #ffffff;
      border: 1px solid #cbd5e1;
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 12.5px;
      font-weight: 600;
      color: var(--ink);
      box-shadow: 0 2px 8px rgba(0,0,0,0.12);
      cursor: pointer;
      display: none;
    }}
    .ui-panel {{
      position: absolute;
      top: 14px;
      left: 14px;
      z-index: 20;
      width: 320px;
      max-height: calc(100% - 28px);
      overflow-y: auto;
      background: var(--panel-bg);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(226, 232, 240, 0.9);
      border-radius: 12px;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
      font-size: 13px;
      transition: transform 0.25s ease, opacity 0.25s ease;
    }}
    .ui-panel.collapsed {{
      transform: translateX(-340px);
      opacity: 0;
      pointer-events: none;
    }}
    .panel-header {{
      padding: 14px 16px 10px;
      border-bottom: 1px solid var(--border);
    }}
    .panel-header-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 4px;
    }}
    .panel-title {{
      font-size: 15.5px;
      font-weight: 700;
      letter-spacing: -0.2px;
      margin: 0;
      color: var(--ink);
    }}
    .close-panel-btn {{
      background: transparent;
      border: none;
      font-size: 16px;
      color: var(--muted);
      cursor: pointer;
      padding: 0 4px;
      line-height: 1;
    }}
    .panel-subtitle {{
      font-size: 11.5px;
      color: var(--muted);
      line-height: 1.4;
    }}
    .reset-btn {{
      margin-top: 8px;
      width: 100%;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 600;
      color: var(--accent);
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.15s ease;
    }}
    .reset-btn:hover {{
      background: #dbeafe;
      color: var(--accent-hover);
    }}
    .group {{
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
    }}
    .group:last-child {{
      border-bottom: none;
    }}
    .group-title {{
      font-size: 10.5px;
      font-weight: 700;
      letter-spacing: 0.8px;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 8px;
    }}
    select {{
      width: 100%;
      padding: 7px 10px;
      border-radius: 6px;
      border: 1px solid #cbd5e1;
      background: #fff;
      font-size: 12.5px;
      font-weight: 500;
      color: var(--ink);
      outline: none;
      cursor: pointer;
    }}
    .toggle-row {{
      display: flex;
      align-items: center;
      gap: 9px;
      min-height: 28px;
      cursor: pointer;
      user-select: none;
    }}
    .toggle-row input[type="checkbox"] {{
      width: 16px;
      height: 16px;
      accent-color: var(--accent);
      cursor: pointer;
    }}
    .toggle-row .count-badge {{
      margin-left: auto;
      font-size: 11px;
      color: #64748b;
      background: #f1f5f9;
      padding: 2px 6px;
      border-radius: 4px;
      font-variant-numeric: tabular-nums;
    }}
    .slider-wrap {{
      margin-top: 8px;
    }}
    .slider-label {{
      display: flex;
      justify-content: space-between;
      font-size: 12px;
      color: #475569;
      margin-bottom: 4px;
    }}
    input[type="range"] {{
      width: 100%;
      accent-color: var(--accent);
      cursor: pointer;
    }}
    .tep-table {{
      width: 100%;
      font-size: 12px;
      border-collapse: collapse;
      margin-top: 4px;
    }}
    .tep-table td {{
      padding: 4px 0;
      border-bottom: 1px dashed #f1f5f9;
    }}
    .tep-table td.label {{
      color: var(--muted);
    }}
    .tep-table td.val {{
      text-align: right;
      font-weight: 600;
      color: var(--ink);
      font-variant-numeric: tabular-nums;
    }}
    .legend-box {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-top: 6px;
      font-size: 11.5px;
      color: #475569;
    }}
    .legend-row {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .legend-chip {{
      width: 14px;
      height: 14px;
      border-radius: 3px;
      flex-shrink: 0;
    }}
    .maplibregl-popup-content {{
      border-radius: 10px;
      padding: 12px 14px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.18);
      border: 1px solid #e2e8f0;
      font-size: 12.5px;
      line-height: 1.45;
      min-width: 230px;
    }}
    .popup-title {{
      font-weight: 700;
      font-size: 13.5px;
      color: #0f172a;
      margin-bottom: 6px;
      padding-bottom: 4px;
      border-bottom: 2px solid var(--accent);
    }}
    .popup-row {{
      display: flex;
      justify-content: space-between;
      margin: 3px 0;
    }}
    .popup-label {{ color: #64748b; }}
    .popup-val {{ font-weight: 600; color: #1e293b; }}
    .compass-hint {{
      position: absolute;
      bottom: 14px;
      right: 14px;
      z-index: 10;
      background: rgba(255, 255, 255, 0.92);
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 11.5px;
      color: #475569;
      box-shadow: 0 2px 8px rgba(0,0,0,0.1);
      pointer-events: none;
    }}
    .loading-notice {{
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      z-index: 5;
      background: rgba(255, 255, 255, 0.94);
      padding: 14px 22px;
      border-radius: 10px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.1);
      font-size: 13.5px;
      font-weight: 600;
      color: #334155;
      display: none;
    }}
  </style>
</head>
<body>
<div id="map-container">
  <div id="map"></div>
  <div id="loading-msg" class="loading-notice">Загрузка 3D-сцены...</div>

  <button id="btn-show-panel" class="panel-toggle-btn" type="button">☰ Меню и ТЭП</button>

  <div class="compass-hint">
    🖱️ ПКМ / Ctrl + ЛКМ — вращение и наклон | Колесико — зум
  </div>

  <aside id="ui-panel" class="ui-panel">
    <header class="panel-header">
      <div class="panel-header-top">
        <h1 class="panel-title">{title}</h1>
        <button id="btn-hide-panel" class="close-panel-btn" title="Свернуть панель" type="button">✕</button>
      </div>
      <div class="panel-subtitle">Кадастр: <b>{cadastral_no}</b></div>
      <button id="btn-reset-view" class="reset-btn" type="button">Вернуться к участку ↗</button>
    </header>

    <div class="group">
      <div class="group-title">Картографическая подложка</div>
      <select id="select-basemap">
        <option value="osm" selected>OpenStreetMap (Схема)</option>
        <option value="light">Светлая архитектурная (OSM Light)</option>
        <option value="satellite">Спутник (Esri World Imagery)</option>
        <option value="dark">Тёмная подложка (Esri Dark)</option>
        <option value="none">Без подложки (Холст)</option>
      </select>
    </div>

    <div class="group">
      <div class="group-title">Раскраска 3D-зданий</div>
      <select id="select-color-mode">
        <option value="floors">По этажности (Градиент)</option>
        <option value="buildings">По корпусам</option>
        <option value="categories">По типам секций</option>
        <option value="neutral">Нейтральный архитектурный</option>
      </select>

      <div id="legend-wrap" class="legend-box"></div>
    </div>

    <div class="group">
      <div class="group-title">Слои генплана</div>
      <label class="toggle-row">
        <input type="checkbox" id="toggle-buildings" checked>
        <span>3D Корпуса</span>
        <span class="count-badge">{s_count} секц.</span>
      </label>
      <label class="toggle-row">
        <input type="checkbox" id="toggle-buildable" checked>
        <span>Зона допустимой застройки</span>
      </label>
      <label class="toggle-row">
        <input type="checkbox" id="toggle-boundary" checked>
        <span>Граница участка</span>
      </label>
      <label class="toggle-row">
        <input type="checkbox" id="toggle-redlines" checked>
        <span>Красные линии</span>
      </label>
    </div>

    <div class="group">
      <div class="group-title">Фильтр по этажности</div>
      <div class="slider-wrap">
        <div class="slider-label">
          <span>Мин. этажей:</span>
          <b id="val-floor-min">1</b>
        </div>
        <input type="range" id="slider-floor-min" min="1" max="35" value="1" step="1">
      </div>
    </div>

    <div class="group">
      <div class="group-title">ТЭП земельного участка</div>
      <table class="tep-table">
        <tr><td class="label">Площадь участка:</td><td class="val">{site_area:,.1f} м² ({site_area_ha} га)</td></tr>
        <tr><td class="label">Количество корпусов:</td><td class="val">{b_count} шт.</td></tr>
        <tr><td class="label">Секций всего:</td><td class="val">{s_count} шт.</td></tr>
        <tr><td class="label">Площадь застройки:</td><td class="val">{footprint_sum:,.1f} м²</td></tr>
        <tr><td class="label">Плотность (FAR):</td><td class="val">{far_val}</td></tr>
        <tr><td class="label">Процент застройки (BCR):</td><td class="val">{bcr_pct}</td></tr>
        <tr><td class="label">Общая площадь (GFA):</td><td class="val">{gfa_sum:,.1f} м²</td></tr>
        <tr><td class="label">Жилая площадь:</td><td class="val">{living_sum:,.1f} м²</td></tr>
        <tr><td class="label">Квартир всего:</td><td class="val">{apts_val}</td></tr>
        <tr><td class="label">Расчетное население:</td><td class="val">{population_val} чел.</td></tr>
        <tr><td class="label">Машиномест:</td><td class="val">{parking_val} м/м</td></tr>
        <tr><td class="label">Доля озеленения:</td><td class="val">{green_pct}</td></tr>
      </table>
    </div>
  </aside>
</div>

<script type="application/json" id="city-data">
{data_json_str}
</script>
<script>
  let DATA = JSON.parse(document.getElementById('city-data').textContent);
  window.DATA = DATA;

  const BASEMAP_CONFIGS = {{
    light: {{
      sourceId: 'osm-light-tiles',
      sourceDef: {{
        type: 'raster',
        tiles: [
          'https://a.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
          'https://b.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
          'https://c.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png'
        ],
        tileSize: 256,
        attribution: '&copy; OpenStreetMap contributors'
      }},
      paint: {{
        'raster-saturation': -0.65,
        'raster-contrast': -0.05,
        'raster-brightness-min': 0.15
      }}
    }},
    osm: {{
      sourceId: 'osm-tiles',
      sourceDef: {{
        type: 'raster',
        tiles: [
          'https://a.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
          'https://b.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
          'https://c.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png'
        ],
        tileSize: 256,
        maxzoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
      }},
      paint: {{}}
    }},
    satellite: {{
      sourceId: 'esri-sat',
      sourceDef: {{
        type: 'raster',
        tiles: [
          'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}'
        ],
        tileSize: 256,
        attribution: '&copy; Esri &mdash; World Imagery'
      }},
      paint: {{}}
    }},
    dark: {{
      sourceId: 'esri-dark',
      sourceDef: {{
        type: 'raster',
        tiles: [
          'https://services.arcgisonline.com/arcgis/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}'
        ],
        tileSize: 256,
        maxzoom: 16,
        attribution: '&copy; Esri &mdash; Dark Gray Canvas'
      }},
      paint: {{}}
    }},
    none: null
  }};

  // Вычисление точного Bounding Box и геометрического центра
  function computeBounds(fcList) {{
    let minLon = 180, minLat = 90, maxLon = -180, maxLat = -90;
    let count = 0;

    function walk(coords) {{
      if (Array.isArray(coords) && coords.length >= 2 && typeof coords[0] === 'number' && typeof coords[1] === 'number') {{
        const lon = coords[0];
        const lat = coords[1];
        if (lon < minLon) minLon = lon;
        if (lon > maxLon) maxLon = lon;
        if (lat < minLat) minLat = lat;
        if (lat > maxLat) maxLat = lat;
        count++;
      }} else if (Array.isArray(coords)) {{
        coords.forEach(walk);
      }}
    }}

    fcList.forEach(fc => {{
      if (fc && fc.features) {{
        fc.features.forEach(f => {{
          if (f.geometry && f.geometry.coordinates) {{
            walk(f.geometry.coordinates);
          }}
        }});
      }}
    }});

    if (count === 0) return null;
    return [[minLon, minLat], [maxLon, maxLat]];
  }}

  let siteBounds = computeBounds([DATA.boundary, DATA.buildings]) || [[30.33, 59.93], [30.34, 59.94]];
  let centerLon = (siteBounds[0][0] + siteBounds[1][0]) / 2;
  let centerLat = (siteBounds[0][1] + siteBounds[1][1]) / 2;

  // Оценка начального зума по размеру участка
  const dLon = siteBounds[1][0] - siteBounds[0][0];
  const dLat = siteBounds[1][1] - siteBounds[0][1];
  const maxSpan = Math.max(dLon, dLat);
  let initZoom = 16.5;
  if (maxSpan > 0.05) initZoom = 12.5;
  else if (maxSpan > 0.02) initZoom = 14.0;
  else if (maxSpan > 0.008) initZoom = 15.2;
  else if (maxSpan > 0.003) initZoom = 16.2;
  else initZoom = 16.8;

  const initBasemapKey = '{default_basemap}';

  if (!window.maplibregl) {{
    document.getElementById('loading-msg').style.display = 'block';
    document.getElementById('loading-msg').innerText = 'Не удалось загрузить библиотеку 3D-карты MapLibre GL.';
  }}

  let map = null;
  let mapInitialized = false;

  function initMapIfReady() {{
    if (mapInitialized) return true;
    const container = document.getElementById('map');
    if (!container) return false;
    const cWidth = container.clientWidth;
    const cHeight = container.clientHeight;
    // Если контейнер скрыт (display: none или размер 0) — откладываем создание карты
    if (cWidth < 50 || cHeight < 50) {{
      return false;
    }}

    mapInitialized = true;

    map = new maplibregl.Map({{
      container: 'map',
      style: {{
        version: 8,
        sources: {{}},
        layers: [
          {{
            id: 'blank-bg',
            type: 'background',
            paint: {{ 'background-color': '#f4f2ed' }}
          }}
        ]
      }},
      center: [centerLon, centerLat],
      zoom: initZoom,
      pitch: 45,
      bearing: 0,
      antialias: true
    }});
    window.map = map;

    map.addControl(new maplibregl.NavigationControl({{ visualizePitch: true }}), 'top-right');
    map.addControl(new maplibregl.ScaleControl({{ maxWidth: 100, unit: 'metric' }}), 'bottom-right');

    map.on('style.load', () => {{
      initLayers();
    }});

    if (map.isStyleLoaded()) {{
      initLayers();
    }}

    setupControls();

    setTimeout(() => fitToData(false), 80);
    return true;
  }}

  const COLOR_EXPRESSIONS = {{
    floors: [
      'interpolate', ['linear'], ['to-number', ['get', 'floors'], 1],
      1, '#38bdf8',
      5, '#3b82f6',
      9, '#10b981',
      12, '#f59e0b',
      16, '#f97316',
      24, '#ef4444'
    ],
    buildings: ['coalesce', ['get', 'color_building'], '#3b82f6'],
    categories: ['coalesce', ['get', 'color_category'], '#2E86AB'],
    neutral: '#cbd5e1'
  }};

  function updateLegend(mode) {{
    const el = document.getElementById('legend-wrap');
    if (!el) return;
    if (mode === 'floors') {{
      el.innerHTML = `
        <div class="legend-row"><span class="legend-chip" style="background:#38bdf8"></span> 1–4 этажа</div>
        <div class="legend-row"><span class="legend-chip" style="background:#3b82f6"></span> 5–8 этажей</div>
        <div class="legend-row"><span class="legend-chip" style="background:#10b981"></span> 9–11 этажей</div>
        <div class="legend-row"><span class="legend-chip" style="background:#f59e0b"></span> 12–15 этажей</div>
        <div class="legend-row"><span class="legend-chip" style="background:#f97316"></span> 16–23 этажа</div>
        <div class="legend-row"><span class="legend-chip" style="background:#ef4444"></span> 24+ этажей</div>
      `;
    }} else if (mode === 'categories') {{
      el.innerHTML = `
        <div class="legend-row"><span class="legend-chip" style="background:#2E86AB"></span> Рядовая секция</div>
        <div class="legend-row"><span class="legend-chip" style="background:#E67E22"></span> Угловая секция</div>
        <div class="legend-row"><span class="legend-chip" style="background:#8E44AD"></span> Торцевая секция</div>
        <div class="legend-row"><span class="legend-chip" style="background:#9B59B6"></span> Точечная башня</div>
      `;
    }} else if (mode === 'buildings') {{
      el.innerHTML = '<div style="color:#64748b;font-size:11px;">Каждый корпус окрашен индивидуальным цветом</div>';
    }} else {{
      el.innerHTML = '<div style="color:#64748b;font-size:11px;">Монохромный архитектурный стиль</div>';
    }}
  }}

  function installLayers() {{
    // 1. Граница участка
    if (!map.getSource('boundary')) {{
      map.addSource('boundary', {{ type: 'geojson', data: DATA.boundary }});
    }} else {{
      map.getSource('boundary').setData(DATA.boundary);
    }}
    if (!map.getLayer('boundary-fill')) {{
      map.addLayer({{
        id: 'boundary-fill',
        type: 'fill',
        source: 'boundary',
        paint: {{
          'fill-color': '#cbd5e1',
          'fill-opacity': 0.25
        }}
      }});
    }}
    if (!map.getLayer('boundary-line')) {{
      map.addLayer({{
        id: 'boundary-line',
        type: 'line',
        source: 'boundary',
        paint: {{
          'line-color': '#0f172a',
          'line-width': 2.8,
          'line-dasharray': [3, 1.5]
        }}
      }});
    }}

    // 2. Зона допустимой застройки
    if (DATA.buildable.features && DATA.buildable.features.length) {{
      if (!map.getSource('buildable')) {{
        map.addSource('buildable', {{ type: 'geojson', data: DATA.buildable }});
      }} else {{
        map.getSource('buildable').setData(DATA.buildable);
      }}
      if (!map.getLayer('buildable-fill')) {{
        map.addLayer({{
          id: 'buildable-fill',
          type: 'fill',
          source: 'buildable',
          paint: {{
            'fill-color': '#22c55e',
            'fill-opacity': 0.10
          }}
        }});
      }}
      if (!map.getLayer('buildable-line')) {{
        map.addLayer({{
          id: 'buildable-line',
          type: 'line',
          source: 'buildable',
          paint: {{
            'line-color': '#16a34a',
            'line-width': 1.8,
            'line-dasharray': [2, 1]
          }}
        }});
      }}
    }}

    // 3. Красные линии
    if (DATA.red_lines.features && DATA.red_lines.features.length) {{
      if (!map.getSource('red_lines')) {{
        map.addSource('red_lines', {{ type: 'geojson', data: DATA.red_lines }});
      }} else {{
        map.getSource('red_lines').setData(DATA.red_lines);
      }}
      if (!map.getLayer('redlines-line')) {{
        map.addLayer({{
          id: 'redlines-line',
          type: 'line',
          source: 'red_lines',
          paint: {{
            'line-color': '#ef4444',
            'line-width': 2.5
          }}
        }});
      }}
    }}

    // 3.1. Улично-дорожная сеть (Проезжая часть и разметка)
    if (DATA.roads && DATA.roads.features && DATA.roads.features.length) {{
      if (!map.getSource('roads')) {{
        map.addSource('roads', {{ type: 'geojson', data: DATA.roads }});
      }} else {{
        map.getSource('roads').setData(DATA.roads);
      }}
      if (!map.getLayer('roads-buffer-fill')) {{
        map.addLayer({{
          id: 'roads-buffer-fill',
          type: 'fill',
          source: 'roads',
          filter: ['==', ['get', 'type'], 'road_buffer'],
          paint: {{
            'fill-color': '#94a3b8',
            'fill-opacity': 0.35
          }}
        }});
      }}
      if (!map.getLayer('roads-fill')) {{
        map.addLayer({{
          id: 'roads-fill',
          type: 'fill',
          source: 'roads',
          filter: ['==', ['get', 'type'], 'road_corridor'],
          paint: {{
            'fill-color': '#334155',
            'fill-opacity': 0.95
          }}
        }});
      }}
      if (!map.getLayer('roads-line')) {{
        map.addLayer({{
          id: 'roads-line',
          type: 'line',
          source: 'roads',
          filter: ['==', ['get', 'type'], 'road_centerline'],
          paint: {{
            'line-color': '#ffffff',
            'line-width': 2.0,
            'line-dasharray': [3, 3]
          }}
        }});
      }}
    }}

    // 4. 3D-здания (экструзия)
    if (!map.getSource('buildings')) {{
      map.addSource('buildings', {{ type: 'geojson', data: DATA.buildings }});
    }} else {{
      map.getSource('buildings').setData(DATA.buildings);
    }}
    if (!map.getLayer('buildings-3d')) {{
      const colorSelect = document.getElementById('select-color-mode');
      const colorMode = (colorSelect && colorSelect.value) || 'floors';
      map.addLayer({{
        id: 'buildings-3d',
        type: 'fill-extrusion',
        source: 'buildings',
        paint: {{
          'fill-extrusion-height': ['to-number', ['coalesce', ['get', 'height'], ['get', 'height_m'], 9], 9],
          'fill-extrusion-base': ['to-number', ['coalesce', ['get', 'min_height'], 0], 0],
          'fill-extrusion-color': COLOR_EXPRESSIONS[colorMode] || COLOR_EXPRESSIONS.floors,
          'fill-extrusion-opacity': 0.95
        }}
      }});
    }}
  }}

  function switchBasemap(key) {{
    const beforeId = (map.getLayer('boundary-fill') && 'boundary-fill') ||
                     (map.getLayer('buildings-3d') && 'buildings-3d') ||
                     undefined;

    if (map.getLayer('basemap-raster')) {{
      map.removeLayer('basemap-raster');
    }}

    const cfg = BASEMAP_CONFIGS[key];
    if (!cfg) return;

    if (!map.getSource(cfg.sourceId)) {{
      map.addSource(cfg.sourceId, cfg.sourceDef);
    }}

    map.addLayer({{
      id: 'basemap-raster',
      type: 'raster',
      source: cfg.sourceId,
      paint: cfg.paint || {{}}
    }}, beforeId);

    const sel = document.getElementById('select-basemap');
    if (sel && sel.value !== key) {{
      sel.value = key;
    }}
  }}

  function initLayers() {{
    switchBasemap(initBasemapKey);
    installLayers();
    updateLegend(document.getElementById('select-color-mode')?.value || 'floors');
  }}

  function fitToData(animated = true) {{
    if (!map) return;
    map.resize();
    const container = map.getContainer();
    const cWidth = container ? container.clientWidth : window.innerWidth;
    const cHeight = container ? container.clientHeight : window.innerHeight;
    if (cWidth < 50 || cHeight < 50) return;

    const panel = document.getElementById('ui-panel');
    const isPanelVisible = panel && !panel.classList.contains('collapsed');
    const leftPad = isPanelVisible && cWidth > 680 ? Math.min(340, Math.floor(cWidth * 0.35)) : 30;
    const rightPad = Math.min(40, Math.floor(cWidth * 0.08));
    const vPad = Math.min(50, Math.floor(cHeight * 0.12));

    try {{
      map.fitBounds(siteBounds, {{
        padding: {{ top: vPad, bottom: vPad, left: leftPad, right: rightPad }},
        pitch: 45,
        bearing: 0,
        duration: animated ? 800 : 0,
        maxZoom: 18.0
      }});
    }} catch (err) {{
      console.warn("fitBounds warning:", err);
    }}
  }}

  let controlsConfigured = false;
  function setupControls() {{
    if (controlsConfigured) return;
    controlsConfigured = true;

    // Панель: скрыть/показать
    const uiPanel = document.getElementById('ui-panel');
    const btnHide = document.getElementById('btn-hide-panel');
    const btnShow = document.getElementById('btn-show-panel');

    const isEmbedded = !{str(standalone).lower()};
    if (isEmbedded || window.innerWidth < 720) {{
      if (uiPanel) {{
        uiPanel.classList.add('collapsed');
        if (btnShow) btnShow.style.display = 'block';
      }}
    }}

    if (btnHide && btnShow && uiPanel) {{
      btnHide.addEventListener('click', () => {{
        uiPanel.classList.add('collapsed');
        btnShow.style.display = 'block';
        setTimeout(() => fitToData(true), 250);
      }});
      btnShow.addEventListener('click', () => {{
        uiPanel.classList.remove('collapsed');
        btnShow.style.display = 'none';
        setTimeout(() => fitToData(true), 250);
      }});
    }}

    // Сброс ракурса
    const btnReset = document.getElementById('btn-reset-view');
    if (btnReset) {{
      btnReset.addEventListener('click', () => fitToData(true));
    }}

    // Смена подложки
    const selBasemap = document.getElementById('select-basemap');
    if (selBasemap) {{
      selBasemap.addEventListener('change', (e) => {{
        switchBasemap(e.target.value);
      }});
    }}

    // Смена палитры
    const selColor = document.getElementById('select-color-mode');
    if (selColor) {{
      selColor.addEventListener('change', (e) => {{
        const mode = e.target.value;
        updateLegend(mode);
        if (map && map.getLayer('buildings-3d')) {{
          map.setPaintProperty('buildings-3d', 'fill-extrusion-color', COLOR_EXPRESSIONS[mode]);
        }}
      }});
    }}

    // Фильтр этажности
    const floorSlider = document.getElementById('slider-floor-min');
    const floorVal = document.getElementById('val-floor-min');
    if (floorSlider && floorVal) {{
      floorSlider.addEventListener('input', (e) => {{
        const minF = parseInt(e.target.value, 10);
        floorVal.textContent = minF;
        if (map && map.getLayer('buildings-3d')) {{
          map.setFilter('buildings-3d', ['>=', ['to-number', ['get', 'floors'], 1], minF]);
        }}
      }});
    }}

    // Чекбоксы слоев
    function setupToggle(checkboxId, layerIds) {{
      const cb = document.getElementById(checkboxId);
      if (!cb) return;
      cb.addEventListener('change', (e) => {{
        const vis = e.target.checked ? 'visible' : 'none';
        layerIds.forEach(id => {{
          if (map && map.getLayer(id)) {{
            map.setLayoutProperty(id, 'visibility', vis);
          }}
        }});
      }});
    }}
    setupToggle('toggle-buildings', ['buildings-3d']);
    setupToggle('toggle-boundary', ['boundary-line', 'boundary-fill']);
    setupToggle('toggle-buildable', ['buildable-line', 'buildable-fill']);
    setupToggle('toggle-redlines', ['redlines-line']);

    // Popup карточки при клике
    const popup = new maplibregl.Popup({{
      closeButton: true,
      closeOnClick: true,
      maxWidth: '310px'
    }});

    if (map) {{
      map.on('click', 'buildings-3d', (e) => {{
        if (!e.features.length) return;
        const p = e.features[0].properties;

        const content = `
          <div class="popup-title">${{p.full_name}}</div>
          <div class="popup-row"><span class="popup-label">Тип секции:</span><span class="popup-val">${{p.category_name}}</span></div>
          <div class="popup-row"><span class="popup-label">Этажность:</span><span class="popup-val">${{p.floors}} эт. (h = ${{p.height}} м)</span></div>
          <div class="popup-row"><span class="popup-label">Высота типового этажа:</span><span class="popup-val">${{p.floor_height}} м</span></div>
          <div class="popup-row"><span class="popup-label">Площадь пятна:</span><span class="popup-val">${{p.footprint_area}} м²</span></div>
          <div class="popup-row"><span class="popup-label">Общая площадь (GFA):</span><span class="popup-val">${{p.gfa}} м²</span></div>
          <div class="popup-row"><span class="popup-label">Жилая площадь:</span><span class="popup-val">${{p.living_area}} м²</span></div>
          <div class="popup-row"><span class="popup-label">Квартир в секции:</span><span class="popup-val">${{p.apartments}} шт.</span></div>
          <div class="popup-row"><span class="popup-label">1-й этаж коммерция:</span><span class="popup-val">${{p.has_commercial ? 'Да' : 'Нет'}}</span></div>
          <div style="margin-top:6px;padding-top:4px;border-top:1px dashed #cbd5e1;font-size:11px;color:#64748b;">
            <b>${{p.building_name}}</b>: этажность ${{p.building_floors}} эт. (${{p.building_height}} м), ${{p.building_sections}} секц.
          </div>
        `;

        popup.setLngLat(e.lngLat).setHTML(content).addTo(map);

        if (window.parent && window.parent !== window) {{
          try {{
            window.parent.postMessage({{ type: 'section_click', section_id: p.id || p.section_id }}, '*');
          }} catch (_) {{}}
        }}
      }});

      map.on('mouseenter', 'buildings-3d', () => {{
        map.getCanvas().style.cursor = 'pointer';
      }});
      map.on('mouseleave', 'buildings-3d', () => {{
        map.getCanvas().style.cursor = '';
      }});
    }}
  }}

  function updateViewerData(newData) {{
    if (!newData) return;
    DATA = newData;
    window.DATA = newData;
    const newBounds = computeBounds([DATA.boundary, DATA.buildings]);
    if (newBounds) {{
      siteBounds = newBounds;
      centerLon = (siteBounds[0][0] + siteBounds[1][0]) / 2;
      centerLat = (siteBounds[0][1] + siteBounds[1][1]) / 2;
    }}

    if (!map) {{
      initMapIfReady();
    }} else {{
      if (map.getSource('boundary') && DATA.boundary) {{
        map.getSource('boundary').setData(DATA.boundary);
      }}
      if (map.getSource('buildable') && DATA.buildable) {{
        map.getSource('buildable').setData(DATA.buildable);
      }}
      if (map.getSource('red_lines') && DATA.red_lines) {{
        map.getSource('red_lines').setData(DATA.red_lines);
      }}
      if (map.getSource('roads') && DATA.roads) {{
        map.getSource('roads').setData(DATA.roads);
      }}
      if (map.getSource('buildings') && DATA.buildings) {{
        map.getSource('buildings').setData(DATA.buildings);
      }}
      setTimeout(() => fitToData(true), 60);
    }}
  }}

  // Единый слушатель сообщений от родительского окна
  window.addEventListener('message', function(e) {{
    if (!e.data) return;
    if (e.data.type === 'loadData' && e.data.data) {{
      updateViewerData(e.data.data);
      if (e.data.basemap && map) {{
        switchBasemap(e.data.basemap);
      }}
    }} else if (e.data.type === 'activate' || e.data.type === 'resize') {{
      if (!map) {{
        initMapIfReady();
      }} else {{
        map.resize();
        setTimeout(function() {{ map.resize(); fitToData(false); }}, 50);
        setTimeout(function() {{ map.resize(); fitToData(false); }}, 250);
      }}
    }}
  }});

  // 1. Попытка немедленной инициализации карты (если контейнер уже имеет размер)
  if (!initMapIfReady()) {{
    // 2. ResizeObserver отслеживает появление контейнера (снятие display: none)
    if (window.ResizeObserver) {{
      let roTimer = null;
      const ro = new ResizeObserver((entries) => {{
        for (const entry of entries) {{
          if (entry.contentRect.width > 50 && entry.contentRect.height > 50) {{
            if (!map) {{
              initMapIfReady();
            }} else {{
              map.resize();
              clearTimeout(roTimer);
              roTimer = setTimeout(() => fitToData(false), 80);
            }}
          }}
        }}
      }});
      const mapEl = document.getElementById('map');
      if (mapEl) ro.observe(mapEl);
    }}

    // 3. Ожидание через requestAnimationFrame (страховка)
    function waitForContainer() {{
      if (!initMapIfReady()) {{
        requestAnimationFrame(waitForContainer);
      }}
    }}
    requestAnimationFrame(waitForContainer);
  }} else {{
    window.addEventListener('resize', () => {{
      if (map) map.resize();
    }});
  }}

  // Оповещаем родительский дашборд о готовности фрейма к приёму данных
  try {{
    if (window.parent && window.parent !== window) {{
      window.parent.postMessage({{ type: 'viewer3dReady' }}, '*');
    }}
  }} catch(_) {{}}
</script>
</body>
</html>"""
    return html
