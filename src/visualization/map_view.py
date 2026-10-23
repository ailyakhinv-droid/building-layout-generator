"""Модуль интерактивной картографической визуализации на подложке OpenStreetMap / Esri Satellite.

Использует библиотеку Leaflet и плагин Leaflet.Path.Transform для прямого манипулирования контуром:
- Прямое перетаскивание контура участка мышью (как в Figma/AutoCAD).
- Прямой поворот контура за верхний оранжевый маркер с автоповоротом всех корпусов застройки.
- Индивидуальные секции зданий (рядовые, угловые, торцевые) с возможностью включения/выключения видимости.
- Подложки: OpenStreetMap, Esri World Imagery (высокодетальный спутник), CartoDB Positron.
- Автоматический пересчёт ТЭП и генерации при сохранении положения контура.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shapely.geometry import mapping

from src.core.geo_utils import (
    geometry_to_geojson_dict,
    transform_geometry_to_wgs84,
)
from src.models.building import Building
from src.models.site import Site
from src.models.tep import TEP
import streamlit.components.v1 as components

# Палитра цветов для корпусов на карте
BUILDING_MAP_COLORS = [
    "#2E86AB",  # Глубокий синий
    "#F18F01",  # Теплый оранжевый
    "#2ECC71",  # Изумрудный
    "#9B59B6",  # Аметистовый
    "#E74C3C",  # Коралловый
    "#F39C12",  # Янтарный
    "#1ABC9C",  # Бирюзовый
    "#34495E",  # Графитовый
]

# Кэш JS-кода Leaflet.Path.Transform (загружается локально)
_LPT_PATH = Path(__file__).parent / "leaflet-path-transform.js"
if _LPT_PATH.exists():
    _LPT_JS_CODE = _LPT_PATH.read_text(encoding="utf-8")
else:
    _LPT_JS_CODE = ""

# Streamlit Custom Component для бесконфликтной передачи трансформации без перезагрузки страницы
_MAP_COMP_DIR = Path(__file__).parent / "map_component"
try:
    _osm_map_comp = components.declare_component("osm_map_component", path=str(_MAP_COMP_DIR.resolve()))
except Exception:
    _osm_map_comp = None


def render_interactive_map(
    site: Site,
    buildings: list[Building] | None = None,
    tep: TEP | None = None,
    height: int = 580,
    fallback_center: tuple[float, float] | None = None,
    show_sections: bool = True,
    interactive_transform: bool = False,
    key: str | None = None,
) -> dict | None:
    """Отрендерить интерактивную карту с двусторонней передачей координат и поворота в Streamlit без перезагрузки страницы."""
    html_code = generate_leaflet_map_html(
        site,
        buildings,
        tep,
        height=height,
        fallback_center=fallback_center,
        show_sections=show_sections,
        interactive_transform=interactive_transform,
    )
    if _osm_map_comp is not None:
        return _osm_map_comp(html=html_code, height=height + 20, key=key)
    else:
        components.html(html_code, height=height + 20)
        return None


def generate_leaflet_map_html(
    site: Site,
    buildings: list[Building] | None = None,
    tep: TEP | None = None,
    height: int = 580,
    fallback_center: tuple[float, float] | None = None,
    show_sections: bool = True,
    interactive_transform: bool = False,
) -> str:
    """Сгенерировать HTML-код интерактивной карты Leaflet с возможностью прямого перетаскивания и поворота контура мышью.

    Args:
        site: Земельный участок (содержит boundary, geo_center, rotation_deg).
        buildings: Список размещенных зданий (опционально).
        tep: Сводные ТЭП участка (опционально).
        height: Высота блока карты в пикселях.
        fallback_center: Резервный центр (lat, lon), если geo_center не задан.
        show_sections: Показывать ли слой отдельных секций на карте по умолчанию.
        interactive_transform: Включить ли интерактивное перетаскивание и маркер поворота (Этап 1: Посадка участка).
                               Если False (Этап 2: Застройка), участок фиксируется, ручки скрыты.

    Returns:
        HTML строка для рендеринга через st.components.v1.html.
    """
    if site.geo_center:
        center_lat, center_lon = site.geo_center
    elif fallback_center:
        center_lat, center_lon = fallback_center
    else:
        center_lat, center_lon = 55.751244, 37.618423

    current_rot_deg = float(getattr(site, "rotation_deg", 0.0) or 0.0)

    # 1. Формируем GeoJSON границы участка
    boundary_wgs = transform_geometry_to_wgs84(site.boundary, center_lat, center_lon)
    boundary_feature = {
        "type": "Feature",
        "geometry": mapping(boundary_wgs),
        "properties": {
            "type": "boundary",
            "cadastral_number": site.cadastral_number or "Не указан",
            "address": site.address or "—",
            "area": round(site.area, 1),
            "area_ha": round(site.area / 10000.0, 2),
        },
    }

    # 2. Формируем GeoJSON зоны допустимой застройки (если есть)
    buildable_feature = None
    if site.buildable_area and not site.buildable_area.is_empty:
        buildable_wgs = transform_geometry_to_wgs84(site.buildable_area, center_lat, center_lon)
        buildable_feature = {
            "type": "Feature",
            "geometry": mapping(buildable_wgs),
            "properties": {
                "type": "buildable",
                "area": round(site.buildable_area.area, 1),
            },
        }

    # 3. Формируем GeoJSON красных линий
    red_line_features = []
    for idx, rl in enumerate(site.red_lines):
        rl_wgs = transform_geometry_to_wgs84(rl, center_lat, center_lon)
        red_line_features.append({
            "type": "Feature",
            "geometry": mapping(rl_wgs),
            "properties": {"type": "red_line", "id": idx + 1},
        })

    # 4. Формируем GeoJSON общих контуров корпусов зданий
    building_features = []
    # 5. Формируем GeoJSON индивидуальных секций (для детального отображения планировки)
    section_features = []

    # На этапе 1 (интерактивная посадка) корпуса и секции не отображаются
    if buildings and not interactive_transform:
        for idx, b in enumerate(buildings):
            b_footprint = b.footprint
            b_wgs = transform_geometry_to_wgs84(b_footprint, center_lat, center_lon)
            color = BUILDING_MAP_COLORS[idx % len(BUILDING_MAP_COLORS)]

            apts_dict = b.total_apartments
            apts_count = sum(apts_dict.values())
            footprint_area = b.total_building_area
            total_gfa = b.total_gfa
            living_area = total_gfa * 0.72

            building_features.append({
                "type": "Feature",
                "geometry": mapping(b_wgs),
                "properties": {
                    "id": idx + 1,
                    "name": f"Корпус {idx + 1}",
                    "floors": b.floors,
                    "min_floors": b.min_floors,
                    "sections_count": len(b.sections),
                    "typology": b.typology,
                    "footprint_area": round(footprint_area, 1),
                    "gfa": round(total_gfa, 1),
                    "living_area": round(living_area, 1),
                    "apartments": apts_count,
                    "color": color,
                },
            })

            # Разбивка по секциям
            for s_idx, sec in enumerate(b.sections):
                sec_wgs = transform_geometry_to_wgs84(sec.footprint, center_lat, center_lon)
                cat_val = (
                    sec.section_type.category.value
                    if hasattr(sec.section_type.category, "value")
                    else str(sec.section_type.category)
                )

                cat_name_ru = "Рядовая"
                cat_color = "#3498DB"  # синий
                if "CORNER" in cat_val:
                    cat_name_ru = "Угловая"
                    cat_color = "#E67E22"  # оранжевый
                elif "END" in cat_val:
                    cat_name_ru = "Торцевая"
                    cat_color = "#9B59B6"  # фиолетовый

                s_code = getattr(sec.section_type, "section_code", "") or sec.section_type.name.split()[0]
                apts_floor = getattr(sec.section_type, "total_apts_per_floor", 0)

                section_features.append({
                    "type": "Feature",
                    "geometry": mapping(sec_wgs),
                    "properties": {
                        "building_id": idx + 1,
                        "section_idx": s_idx + 1,
                        "section_id": sec.section_type.id,
                        "name": sec.section_type.name,
                        "category": cat_val,
                        "category_ru": cat_name_ru,
                        "code": s_code,
                        "floors": sec.floors,
                        "width": sec.section_type.width,
                        "depth": sec.section_type.depth,
                        "floor_area": sec.section_type.floor_area,
                        "apts_per_floor": apts_floor,
                        "color": cat_color,
                        "building_color": color,
                    },
                })

    boundary_json = json.dumps(boundary_feature, ensure_ascii=False)
    buildable_json = json.dumps(buildable_feature, ensure_ascii=False) if buildable_feature else "null"
    red_lines_json = json.dumps(red_line_features, ensure_ascii=False)
    buildings_json = json.dumps(building_features, ensure_ascii=False)
    sections_json = json.dumps(section_features, ensure_ascii=False)

    add_sections_to_map = "sectionsLayer.addTo(map);" if show_sections else "// sectionsLayer доступен в переключателе слоев"

    hud_block = """
    <!-- Плавающий HUD прямого управления контуром (Этап 1: Посадка участка) -->
    <div id="transformHud" class="transform-hud">
        <div class="hud-inner">
            <div class="hud-info" id="hudInfo">
                <span>✋ Перемещайте контур мышью &bull; 🔄 Крутите за оранжевый маркер сверху</span>
            </div>
            <div class="hud-actions" id="hudActions" style="display:flex;">
                <button type="button" class="hud-btn hud-btn-save" onclick="applySiteTransform()">🔒 Закрепить участок</button>
                <button type="button" class="hud-btn hud-btn-reset" onclick="resetSiteTransform()">↺ Сброс</button>
            </div>
        </div>
    </div>
""" if interactive_transform else ""

    is_interactive_str = "true" if interactive_transform else "false"

    html_code = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <script>
    {_LPT_JS_CODE}
    </script>
    <style>
        html, body {{
            height: 100%;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            overflow: hidden;
        }}
        #map {{
            width: 100%;
            height: {height}px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }}
        .interactive-boundary-polygon,
        .leaflet-interactive {{
            cursor: grab !important;
        }}
        .interactive-boundary-polygon:active,
        .leaflet-interactive:active {{
            cursor: grabbing !important;
        }}
        .leaflet-grab {{
            cursor: default !important;
        }}
        /* Яркий, крупный и заметный маркер поворота (Rotate Handle) */
        .transform-handler--rotate {{
            r: 12px !important;
            fill: #FF5722 !important;
            stroke: #FFFFFF !important;
            stroke-width: 3.5px !important;
            filter: drop-shadow(0 2px 8px rgba(0,0,0,0.65)) !important;
            cursor: grab !important;
            transition: transform 0.15s ease;
        }}
        .transform-handler--rotate:hover {{
            r: 14px !important;
            fill: #E64A19 !important;
        }}
        .transform-handler--rotate:active {{
            cursor: grabbing !important;
            fill: #D84315 !important;
        }}
        .custom-popup .leaflet-popup-content-wrapper {{
            border-radius: 8px;
            box-shadow: 0 3px 14px rgba(0,0,0,0.25);
            padding: 2px;
        }}
        .popup-card {{
            padding: 6px 10px;
            line-height: 1.45;
            font-size: 13px;
            color: #2c3e50;
        }}
        .popup-card h4 {{
            margin: 0 0 6px 0;
            font-size: 15px;
            border-bottom: 2px solid #3498db;
            padding-bottom: 4px;
        }}
        .popup-row {{
            display: flex;
            justify-content: space-between;
            margin: 3px 0;
            border-bottom: 1px dashed #ecf0f1;
            padding-bottom: 2px;
        }}
        .popup-label {{
            color: #7f8c8d;
        }}
        .popup-val {{
            font-weight: 600;
        }}
        .map-legend {{
            background: white;
            padding: 8px 12px;
            border-radius: 6px;
            box-shadow: 0 1px 5px rgba(0,0,0,0.3);
            font-size: 12px;
            line-height: 1.6;
        }}
        /* Плавающий HUD управления положением участка (Figma / AutoCAD стиль, нижний док) */
        .transform-hud {{
            position: absolute;
            bottom: 22px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 1000;
            background: rgba(24, 32, 47, 0.94);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 30px;
            padding: 7px 18px;
            box-shadow: 0 4px 22px rgba(0, 0, 0, 0.38);
            color: #FFFFFF;
            font-size: 13px;
            font-weight: 500;
            pointer-events: auto;
            transition: all 0.25s ease;
        }}
        .hud-inner {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .hud-info {{
            display: flex;
            align-items: center;
            gap: 8px;
            white-space: nowrap;
        }}
        .hud-actions {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .hud-btn {{
            border: none;
            border-radius: 20px;
            padding: 5px 14px;
            font-size: 12px;
            font-weight: 700;
            cursor: pointer;
            transition: background 0.15s ease, transform 0.1s ease;
        }}
        .hud-btn:active {{
            transform: scale(0.96);
        }}
        .hud-btn-save {{
            background: #27AE60;
            color: #FFFFFF;
        }}
        .hud-btn-save:hover {{
            background: #2ECC71;
        }}
        .hud-btn-reset {{
            background: rgba(255, 255, 255, 0.15);
            color: #ECEFF1;
            border: 1px solid rgba(255, 255, 255, 0.25);
        }}
        .hud-btn-reset:hover {{
            background: rgba(255, 255, 255, 0.25);
            color: #FFFFFF;
        }}
    </style>
</head>
<body>
    <div id="map"></div>

    {hud_block}

    <script>
        // Базовые картографические подложки
        var osmStandard = L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap contributors'
        }});

        var cartoPositron = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap &copy; CARTO'
        }});

        var osmHot = L.tileLayer('https://{{s}}.tile.openstreetmap.fr/hot/{{z}}/{{x}}/{{y}}.png', {{
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap, HOT'
        }});

        var esriSat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
            maxZoom: 19,
            attribution: 'Tiles &copy; Esri &mdash; World Imagery'
        }});

        var map = L.map('map', {{
            center: [{center_lat}, {center_lon}],
            zoom: 16,
            layers: [osmStandard]
        }});

        L.control.scale({{ metric: true, imperial: false, position: 'bottomleft' }}).addTo(map);

        // Стрелка истинного севера
        var northArrow = L.control({{ position: 'topleft' }});
        northArrow.onAdd = function(map) {{
            var div = L.DomUtil.create('div', 'map-legend');
            div.style.padding = '4px 8px';
            div.style.textAlign = 'center';
            div.style.borderRadius = '4px';
            div.style.boxShadow = '0 1px 5px rgba(0,0,0,0.2)';
            div.innerHTML = '<div style="font-weight: bold; font-size: 13px; line-height: 1.1; color: #2C3E50;">' +
                '<span style="color: #E74C3C; font-size: 16px;">▲</span><br>' +
                '<span style="font-size: 11px; font-weight: 700; color: #E74C3C;">N</span><br>' +
                '<span style="font-size: 9px; color: #7f8c8d;">СЕВЕР</span>' +
                '</div>';
            return div;
        }};
        northArrow.addTo(map);

        // Данные геометрии
        var boundaryData = {boundary_json};
        var buildableData = {buildable_json};
        var redLinesData = {red_lines_json};
        var buildingsData = {buildings_json};
        var sectionsData = {sections_json};

        // Извлечение колец координат участка
        var rawCoords = boundaryData.geometry.coordinates;
        var boundaryLatLngs;
        if (boundaryData.geometry.type === 'Polygon') {{
            boundaryLatLngs = rawCoords.map(function(ring) {{
                return ring.map(function(pt) {{ return [pt[1], pt[0]]; }});
            }});
            if (boundaryLatLngs.length === 1) {{
                boundaryLatLngs = boundaryLatLngs[0];
            }}
        }} else {{
            boundaryLatLngs = rawCoords[0][0].map(function(pt) {{ return [pt[1], pt[0]]; }});
        }}

        // 1. Контур участка (интерактивный на Этапе 1, статичный на Этапе 2)
        var isInteractiveTransform = {is_interactive_str};
        var boundaryPolygon = L.polygon(boundaryLatLngs, {{
            color: '#1B4F72',
            weight: 3.5,
            opacity: 0.95,
            fillColor: '#3498DB',
            fillOpacity: 0.15,
            className: isInteractiveTransform ? 'interactive-boundary-polygon' : 'static-boundary-polygon',
            transform: isInteractiveTransform,
            draggable: isInteractiveTransform
        }}).addTo(map);

        // 2. Слой допустимой зоны застройки
        var buildableLayer = null;
        if (buildableData) {{
            buildableLayer = L.geoJSON(buildableData, {{
                style: {{
                    color: '#16A085',
                    weight: 2,
                    dashArray: '5, 5',
                    fillColor: '#2ECC71',
                    fillOpacity: 0.05
                }},
                onEachFeature: function(feature, layer) {{
                    var html = '<div class="popup-card">' +
                        '<h4 style="border-color:#16A085; color:#16A085;">🟩 Зона застройки</h4>' +
                        '<div class="popup-row"><span class="popup-label">Площадь зоны:</span><span class="popup-val">' + Number(feature.properties.area).toLocaleString() + ' м²</span></div>' +
                        '<div><i>С учётом нормативных отступов</i></div>' +
                        '</div>';
                    layer.bindPopup(html, {{ className: 'custom-popup' }});
                }}
            }}).addTo(map);
        }}

        // 3. Слой красных линий
        var redLinesLayer = null;
        if (redLinesData && redLinesData.length > 0) {{
            redLinesLayer = L.geoJSON(redLinesData, {{
                style: {{
                    color: '#E74C3C',
                    weight: 3.5,
                    dashArray: '8, 6'
                }},
                onEachFeature: function(feature, layer) {{
                    layer.bindPopup('<b>⛔ Красная линия</b><br>Граница территорий общего пользования / отступ УДС');
                }}
            }}).addTo(map);
        }}

        // 4. Слой общих контуров корпусов
        var buildingsLayer = L.geoJSON(buildingsData, {{
            style: function(feature) {{
                return {{
                    color: '#1A5276',
                    weight: 2.0,
                    fillColor: feature.properties.color || '#2E86AB',
                    fillOpacity: 0.75
                }};
            }},
            onEachFeature: function(feature, layer) {{
                var p = feature.properties;
                var html = '<div class="popup-card">' +
                    '<h4 style="border-color:' + p.color + '; color:#2C3E50;">🏢 ' + p.name + '</h4>' +
                    '<div class="popup-row"><span class="popup-label">Этажность:</span><span class="popup-val">' + p.floors + ' эт.</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Секций:</span><span class="popup-val">' + p.sections_count + '</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Типология:</span><span class="popup-val">' + p.typology + '</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Пятно застройки:</span><span class="popup-val">' + Number(p.footprint_area).toLocaleString() + ' м²</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Общая площадь:</span><span class="popup-val">' + Number(p.gfa).toLocaleString() + ' м²</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Жилая площадь:</span><span class="popup-val">~' + Number(p.living_area).toLocaleString() + ' м²</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Квартир:</span><span class="popup-val">' + p.apartments + '</span></div>' +
                    '</div>';
                layer.bindPopup(html, {{ className: 'custom-popup' }});
                layer.on('mouseover', function() {{ this.setStyle({{ fillOpacity: 0.95, weight: 2.5, color: '#000' }}); }});
                layer.on('mouseout', function() {{ buildingsLayer.resetStyle(this); }});
            }}
        }}).addTo(map);

        // 5. Слой индивидуальных секций (детальная планировка)
        var sectionsLayer = L.geoJSON(sectionsData, {{
            style: function(feature) {{
                var p = feature.properties;
                return {{
                    color: '#FFFFFF',
                    weight: 1.5,
                    fillColor: p.color || '#3498DB',
                    fillOpacity: 0.88
                }};
            }},
            onEachFeature: function(feature, layer) {{
                var p = feature.properties;
                var html = '<div class="popup-card">' +
                    '<h4 style="border-color:' + p.color + '; color:#2C3E50;">🧱 ' + p.name + '</h4>' +
                    '<div class="popup-row"><span class="popup-label">Тип секции:</span><span class="popup-val"><b>' + p.category_ru + '</b> (' + p.code + ')</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Корпус:</span><span class="popup-val">Корпус ' + p.building_id + ', секция ' + p.section_idx + '</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Этажность:</span><span class="popup-val">' + p.floors + ' эт.</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Габариты:</span><span class="popup-val">' + p.width + ' × ' + p.depth + ' м</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Квартир/эт:</span><span class="popup-val">' + p.apts_per_floor + '</span></div>' +
                    '</div>';
                layer.bindPopup(html, {{ className: 'custom-popup' }});
                layer.on('mouseover', function() {{ this.setStyle({{ fillOpacity: 1.0, weight: 2.5, color: '#000' }}); }});
                layer.on('mouseout', function() {{ sectionsLayer.resetStyle(this); }});
            }}
        }});

        {add_sections_to_map}

        // Включаем вращение и перетаскивание контура (только на Этапе 1)
        if (isInteractiveTransform && boundaryPolygon.transform) {{
            boundaryPolygon.transform.enable({{
                rotation: true,
                scaling: false,
                uniformScaling: false,
                handleLength: 40,
                handlerOptions: {{
                    radius: 12,
                    fillColor: '#FF5722',
                    color: '#FFFFFF',
                    weight: 3.5,
                    fillOpacity: 1
                }},
                rotateHandleOptions: {{
                    color: '#FF5722',
                    weight: 3,
                    dashArray: '5, 5'
                }},
                boundsOptions: {{
                    color: '#FF5722',
                    weight: 1.5,
                    dashArray: '5, 5',
                    fill: false
                }}
            }});
        }}

        // Информационный попап по клику на контур (только если не было перетаскивания)
        boundaryPolygon.on('click', function(e) {{
            if (boundaryPolygon.dragging && boundaryPolygon.dragging.moved()) return;
            var p = boundaryData.properties;
            var html = '<div class="popup-card">' +
                '<h4 style="border-color:#1B4F72; color:#1B4F72;">📐 Граница участка</h4>' +
                '<div class="popup-row"><span class="popup-label">Кадастр. №:</span><span class="popup-val">' + p.cadastral_number + '</span></div>' +
                '<div class="popup-row"><span class="popup-label">Площадь:</span><span class="popup-val">' + Number(p.area).toLocaleString() + ' м² (' + p.area_ha + ' га)</span></div>' +
                '<div class="popup-row"><span class="popup-label">Адрес:</span><span class="popup-val">' + p.address + '</span></div>' +
                '</div>';
            boundaryPolygon.bindPopup(html, {{ className: 'custom-popup' }}).openPopup(e.latlng);
        }});

        // ─── Связанная трансформация всех слоёв (AutoCAD / Figma блок) ──────
        var attachedLayers = [];

        function registerAttached(layerGroup) {{
            if (!layerGroup) return;
            layerGroup.eachLayer(function(l) {{
                if (l.getLatLngs) {{
                    attachedLayers.push({{ layer: l, origLatLngs: JSON.parse(JSON.stringify(l.getLatLngs())) }});
                    // Делегируем mousedown для бесшовного перемещения всей застройки целиком при клике на любой корпус/секция
                    l.on('mousedown', function(e) {{
                        if (boundaryPolygon.dragging) {{
                            boundaryPolygon.dragging._onDragStart(e);
                        }}
                    }});
                }}
            }});
        }}
        registerAttached(buildableLayer);
        registerAttached(redLinesLayer);
        registerAttached(buildingsLayer);
        registerAttached(sectionsLayer);

        var initGeoCenterLat = {center_lat};
        var initGeoCenterLon = {center_lon};
        var origLatLngs = JSON.parse(JSON.stringify(boundaryLatLngs));
        var origCenter = boundaryPolygon.getBounds().getCenter();
        var origLat = origCenter.lat;
        var origLng = origCenter.lng;
        var initialSiteRotation = {current_rot_deg};
        var totalRotationDeg = {current_rot_deg};
        var activeRotationDeltaDeg = 0.0;
        var wasDragged = false;

        function extractFirstLatLng(val) {{
            if (!val) return null;
            if (val.lat !== undefined && !isNaN(val.lat)) {{
                return {{ lat: Number(val.lat), lng: Number(val.lng) }};
            }}
            if (Array.isArray(val)) {{
                if (val.length >= 2 && typeof val[0] === 'number') {{
                    return {{ lat: Number(val[0]), lng: Number(val[1]) }};
                }}
                for (var i = 0; i < val.length; i++) {{
                    var res = extractFirstLatLng(val[i]);
                    if (res) return res;
                }}
            }}
            return null;
        }}

        function calculateTransformState() {{
            var newCenter = boundaryPolygon.getBounds().getCenter();
            var dLat = 0.0;
            var dLon = 0.0;
            var distM = 0.0;

            if (wasDragged) {{
                dLat = newCenter.lat - origLat;
                dLon = newCenter.lng - origLng;
                var shiftNorthM = dLat * 111320.0;
                var shiftEastM = dLon * (111320.0 * Math.cos(origLat * Math.PI / 180.0));
                distM = Math.sqrt(shiftNorthM * shiftNorthM + shiftEastM * shiftEastM);
            }}

            var rotDeg = (totalRotationDeg + activeRotationDeltaDeg) % 360.0;
            while (rotDeg > 180.0) rotDeg -= 360.0;
            while (rotDeg < -180.0) rotDeg += 360.0;

            var newGeoLat = initGeoCenterLat + dLat;
            var newGeoLon = initGeoCenterLon + dLon;

            return {{
                newGeoLat: Number(newGeoLat.toFixed(6)),
                newGeoLon: Number(newGeoLon.toFixed(6)),
                newCenter: newCenter,
                dLat: dLat,
                dLon: dLon,
                distM: distM,
                deltaAngleDeg: activeRotationDeltaDeg,
                finalRotationDeg: Number(rotDeg.toFixed(1))
            }};
        }}

        function updateAttachedLayers(state) {{
            // Вращение по часовой стрелке на угол state.deltaAngleDeg (в градусах)
            var rad = (state.deltaAngleDeg || 0.0) * Math.PI / 180.0;
            var cosA = Math.cos(rad);
            var sinA = Math.sin(rad);
            var mLat = 111320.0;
            var mLonOrig = 111320.0 * Math.cos(origLat * Math.PI / 180.0);
            var mLonNew = 111320.0 * Math.cos(state.newCenter.lat * Math.PI / 180.0);

            function transformPt(pt) {{
                var plat = pt.lat !== undefined ? Number(pt.lat) : Number(pt[0]);
                var plng = pt.lng !== undefined ? Number(pt.lng) : Number(pt[1]);
                if (isNaN(plat) || isNaN(plng)) return state.newCenter;
                var x = (plng - origLng) * mLonOrig;
                var y = (plat - origLat) * mLat;
                // Поворот по часовой стрелке на угол rad:
                var xr = x * cosA + y * sinA;
                var yr = -x * sinA + y * cosA;
                return L.latLng(state.newCenter.lat + yr / mLat, state.newCenter.lng + xr / mLonNew);
            }}

            function recurseCoords(coords) {{
                if (!Array.isArray(coords)) return transformPt(coords);
                if (coords.length === 0) return coords;
                if (coords[0].lat !== undefined || (Array.isArray(coords[0]) && typeof coords[0][0] === 'number')) {{
                    return coords.map(transformPt);
                }}
                return coords.map(recurseCoords);
            }}

            for (var i = 0; i < attachedLayers.length; i++) {{
                var item = attachedLayers[i];
                item.layer.setLatLngs(recurseCoords(item.origLatLngs));
            }}
        }}

        window.sendTransformUpdate = function(isLock) {{
            var state = calculateTransformState();
            var payload = {{
                map_lat: state.newGeoLat,
                map_lon: state.newGeoLon,
                map_rot: state.finalRotationDeg,
                dist_m: Number(state.distM.toFixed(1)),
                lock: !!isLock,
                ts: Date.now()
            }};
            try {{
                window.parent.postMessage({{
                    isMapTransform: true,
                    transform: payload
                }}, "*");
            }} catch(e) {{
                console.warn("postMessage to parent failed:", e);
            }}
        }};

        // Синхронное перемещение и вращение всех слоёв в реальном времени (60 FPS)
        boundaryPolygon.on('dragstart', function(e) {{
            wasDragged = true;
        }});

        boundaryPolygon.on('drag', function(e) {{
            wasDragged = true;
            if (boundaryPolygon.dragging && boundaryPolygon.dragging._matrix) {{
                var mat = boundaryPolygon.dragging._matrix;
                for (var i = 0; i < attachedLayers.length; i++) {{
                    attachedLayers[i].layer._transform(mat);
                }}
            }}
            var hudActions = document.getElementById('hudActions');
            var hudInfo = document.getElementById('hudInfo');
            if (hudActions) hudActions.style.display = 'flex';
            var dM = 0;
            if (boundaryPolygon.dragging && boundaryPolygon.dragging._matrix) {{
                var dx = boundaryPolygon.dragging._matrix[4] || 0;
                var dy = boundaryPolygon.dragging._matrix[5] || 0;
                dM = Math.sqrt(dx * dx + dy * dy) * (156543.03392 * Math.cos(origLat * Math.PI / 180.0) / Math.pow(2, map.getZoom()));
            }}
            if (hudInfo) {{
                hudInfo.innerHTML = '📍 Сдвиг: <b>~' + Math.round(dM) + ' м</b> &bull; 🧭 Поворот: <b>' + (totalRotationDeg >= 0 ? '+' : '') + totalRotationDeg.toFixed(1) + '&deg;</b>';
            }}
        }});

        boundaryPolygon.on('rotate', function(e) {{
            if (e && e.rotation !== undefined) {{
                activeRotationDeltaDeg = e.rotation * 180.0 / Math.PI;
            }} else if (boundaryPolygon.transform && boundaryPolygon.transform._angle) {{
                activeRotationDeltaDeg = boundaryPolygon.transform._angle * 180.0 / Math.PI;
            }}
            if (boundaryPolygon.transform && boundaryPolygon.transform._matrix) {{
                var mat = boundaryPolygon.transform._matrix;
                var mArr = mat._matrix || mat;
                for (var i = 0; i < attachedLayers.length; i++) {{
                    attachedLayers[i].layer._transform(mArr);
                }}
            }}
            var rotDeg = (totalRotationDeg + activeRotationDeltaDeg) % 360.0;
            while (rotDeg > 180.0) rotDeg -= 360.0;
            while (rotDeg < -180.0) rotDeg += 360.0;

            var hudActions = document.getElementById('hudActions');
            var hudInfo = document.getElementById('hudInfo');
            if (hudActions) hudActions.style.display = 'flex';
            if (hudInfo) {{
                hudInfo.innerHTML = '📍 Поворот: <b>' + (rotDeg >= 0 ? '+' : '') + rotDeg.toFixed(1) + '&deg;</b> &bull; Зафиксировать положение:';
            }}
        }});

        boundaryPolygon.on('dragend', function(e) {{
            wasDragged = true;
            for (var i = 0; i < attachedLayers.length; i++) {{
                attachedLayers[i].layer._transform(null);
            }}
            var state = calculateTransformState();
            updateAttachedLayers(state);
            var hudActions = document.getElementById('hudActions');
            var hudInfo = document.getElementById('hudInfo');
            if (hudActions) hudActions.style.display = 'flex';
            if (hudInfo) {{
                var distStr = state.distM < 1000 ? Math.round(state.distM) + ' м' : (state.distM / 1000).toFixed(2) + ' км';
                var rotSign = state.finalRotationDeg >= 0 ? '+' : '';
                hudInfo.innerHTML = '📍 Сдвиг: <b>' + distStr + '</b> &bull; 🧭 Поворот: <b>' + rotSign + state.finalRotationDeg.toFixed(1) + '&deg;</b>';
            }}
            window.sendTransformUpdate(false);
        }});

        boundaryPolygon.on('rotateend', function(e) {{
            if (e && e.rotation !== undefined) {{
                activeRotationDeltaDeg = e.rotation * 180.0 / Math.PI;
            }}
            totalRotationDeg = (totalRotationDeg + activeRotationDeltaDeg) % 360.0;
            while (totalRotationDeg > 180.0) totalRotationDeg -= 360.0;
            while (totalRotationDeg < -180.0) totalRotationDeg += 360.0;
            activeRotationDeltaDeg = 0.0;

            for (var i = 0; i < attachedLayers.length; i++) {{
                attachedLayers[i].layer._transform(null);
            }}
            var state = calculateTransformState();
            updateAttachedLayers(state);
            var hudActions = document.getElementById('hudActions');
            var hudInfo = document.getElementById('hudInfo');
            if (hudActions) hudActions.style.display = 'flex';
            if (hudInfo) {{
                var distStr = state.distM < 1000 ? Math.round(state.distM) + ' м' : (state.distM / 1000).toFixed(2) + ' км';
                var rotSign = state.finalRotationDeg >= 0 ? '+' : '';
                hudInfo.innerHTML = '📍 Сдвиг: <b>' + distStr + '</b> &bull; 🧭 Поворот: <b>' + rotSign + state.finalRotationDeg.toFixed(1) + '&deg;</b>';
            }}
            window.sendTransformUpdate(false);
        }});

        // Применить новое положение контура и перейти к застройке
        window.applySiteTransform = function() {{
            var hudInfo = document.getElementById('hudInfo');
            if (hudInfo) hudInfo.innerHTML = '✅ <b>Участок зафиксирован!</b> Переход к застройке...';
            window.sendTransformUpdate(true);
        }};

        // Сбросить контур к исходному положению
        window.resetSiteTransform = function() {{
            for (var i = 0; i < attachedLayers.length; i++) {{
                attachedLayers[i].layer._transform(null);
            }}
            activeRotationDeltaDeg = 0.0;
            wasDragged = false;
            boundaryPolygon.setLatLngs(origLatLngs);
            if (boundaryPolygon.transform) {{
                boundaryPolygon.transform.reset();
                if (boundaryPolygon.transform._handlersGroup) {{
                    boundaryPolygon.transform._handlersGroup.eachLayer(function(l) {{
                        if (l.bringToFront) l.bringToFront();
                    }});
                }}
            }}
            updateAttachedLayers({{ deltaAngleDeg: 0, newCenter: origCenter, finalRotationDeg: initialSiteRotation, distM: 0 }});
            document.getElementById('hudActions').style.display = 'none';
            document.getElementById('hudInfo').innerHTML = '<span>✋ Тяните контур или корпуса &bull; 🔄 Крутите за оранжевый маркер сверху</span>';
        }};

        // Переключатель слоёв
        var baseMaps = {{
            "🗺️ OpenStreetMap (Схема)": osmStandard,
            "🛰️ Спутник Esri World Imagery": esriSat,
            "🏢 CartoDB Positron (Светлая)": cartoPositron,
            "🚑 OSM Humanitarian": osmHot
        }};

        var overlayMaps = {{
            "📐 Граница участка (перемещение/поворот)": boundaryPolygon,
            "🏢 Корпуса застройки (контуры)": buildingsLayer,
            "🧱 Секции корпусов (планировка)": sectionsLayer
        }};
        if (buildableLayer) overlayMaps["🟩 Зона застройки"] = buildableLayer;
        if (redLinesLayer) overlayMaps["⛔ Красная линия (УДС)"] = redLinesLayer;

        L.control.layers(baseMaps, overlayMaps, {{ collapsed: false, position: 'topright' }}).addTo(map);

        // Автоматический зум по границе участка и правильная инициализация маркера поворота
        try {{
            var bounds = boundaryPolygon.getBounds();
            if (bounds.isValid()) {{
                map.fitBounds(bounds, {{ padding: [65, 45], maxZoom: 17 }});
            }}
        }} catch(e) {{
            console.error(e);
        }}

        // Обновление хэндлеров после зума fitBounds
        if (boundaryPolygon.transform) {{
            boundaryPolygon.transform.reset();
            if (boundaryPolygon.transform._handlersGroup) {{
                boundaryPolygon.transform._handlersGroup.eachLayer(function(l) {{
                    if (l.bringToFront) l.bringToFront();
                }});
            }}
        }}

        map.on('zoomend viewreset', function() {{
            if (boundaryPolygon.transform && boundaryPolygon.transform._enabled) {{
                boundaryPolygon.transform.reset();
                if (boundaryPolygon.transform._handlersGroup) {{
                    boundaryPolygon.transform._handlersGroup.eachLayer(function(l) {{
                        if (l.bringToFront) l.bringToFront();
                    }});
                }}
            }}
        }});
    </script>
</body>
</html>"""
    return html_code
