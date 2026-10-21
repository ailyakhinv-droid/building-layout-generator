"""Модуль интерактивной картографической визуализации на подложке OpenStreetMap.

Использует библиотеку Leaflet для отображения:
- Векторной карты OpenStreetMap (и светлой схемы CartoDB).
- Кадастровой границы земельного участка.
- Красных линий и зоны допустимой застройки.
- Сгенерированных жилых корпусов с дифференциацией по типам и всплывающими карточками ТЭП.
"""

from __future__ import annotations

import json
from typing import Any

from shapely.geometry import mapping

from src.core.geo_utils import (
    geometry_to_geojson_dict,
    transform_geometry_to_wgs84,
)
from src.models.building import Building
from src.models.site import Site
from src.models.tep import TEP


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


def generate_leaflet_map_html(
    site: Site,
    buildings: list[Building] | None = None,
    tep: TEP | None = None,
    height: int = 580,
) -> str:
    """Сгенерировать HTML-код интерактивной карты Leaflet с подложкой OpenStreetMap.

    Args:
        site: Земельный участок (должен содержать geo_center).
        buildings: Список размещенных зданий (опционально).
        tep: Сводные ТЭП участка (опционально).
        height: Высота блока карты в пикселях.

    Returns:
        HTML строка для рендеринга через st.components.v1.html.
    """
    if not site.geo_center:
        center_lat, center_lon = 55.751244, 37.618423
    else:
        center_lat, center_lon = site.geo_center

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

    # 4. Формируем GeoJSON корпусов зданий
    building_features = []
    if buildings:
        for idx, b in enumerate(buildings):
            b_footprint = b.footprint
            b_wgs = transform_geometry_to_wgs84(b_footprint, center_lat, center_lon)
            color = BUILDING_MAP_COLORS[idx % len(BUILDING_MAP_COLORS)]

            # Оценка квартир и площадей
            apts_dict = b.total_apartments
            apts_count = sum(apts_dict.values())
            footprint_area = b.total_building_area
            total_gfa = b.total_gfa
            living_area = total_gfa * 0.72  # Коэффициент выхода жилой площади ~72%

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

    # Упаковываем все в JSON строки (с сохранением кириллицы)
    boundary_json = json.dumps(boundary_feature, ensure_ascii=False)
    buildable_json = json.dumps(buildable_feature, ensure_ascii=False) if buildable_feature else "null"
    red_lines_json = json.dumps(red_line_features, ensure_ascii=False)
    buildings_json = json.dumps(building_features, ensure_ascii=False)

    html_code = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <style>
        html, body {{
            height: 100%;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }}
        #map {{
            width: 100%;
            height: {height}px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
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
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .legend-swatch {{
            width: 14px;
            height: 14px;
            border-radius: 2px;
            display: inline-block;
        }}
    </style>
</head>
<body>
    <div id="map"></div>
    <script>
        // Инициализация базовых слоёв карт
        var osmStandard = L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        }});

        var cartoPositron = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
        }});

        var osmHot = L.tileLayer('https://{{s}}.tile.openstreetmap.fr/hot/{{z}}/{{x}}/{{y}}.png', {{
            maxZoom: 19,
            attribution: '&copy; OpenStreetMap contributors, Tiles style by HOT'
        }});

        var map = L.map('map', {{
            center: [{center_lat}, {center_lon}],
            zoom: 16,
            layers: [osmStandard]
        }});

        // Контрол масштаба
        L.control.scale({{ metric: true, imperial: false, position: 'bottomleft' }}).addTo(map);

        // Стрелка севера (North Arrow)
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

        // 1. Слой границы участка (четкий темно-синий контур)
        var boundaryLayer = L.geoJSON(boundaryData, {{
            style: {{
                color: '#1B4F72',
                weight: 3.5,
                opacity: 0.95,
                fillColor: '#3498DB',
                fillOpacity: 0.12
            }},
            onEachFeature: function(feature, layer) {{
                var p = feature.properties;
                var html = '<div class="popup-card">' +
                    '<h4 style="border-color:#1B4F72; color:#1B4F72;">📐 Граница участка</h4>' +
                    '<div class="popup-row"><span class="popup-label">Кадастр. №:</span><span class="popup-val">' + p.cadastral_number + '</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Площадь:</span><span class="popup-val">' + Number(p.area).toLocaleString() + ' м² (' + p.area_ha + ' га)</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Адрес:</span><span class="popup-val">' + p.address + '</span></div>' +
                    '</div>';
                layer.bindPopup(html, {{ className: 'custom-popup' }});
            }}
        }}).addTo(map);

        // 2. Слой допустимой зоны застройки (изумрудно-бирюзовый пунктир)
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
                        '<div><i>С учётом нормативных отступов от границ</i></div>' +
                        '</div>';
                    layer.bindPopup(html, {{ className: 'custom-popup' }});
                }}
            }}).addTo(map);
        }}

        // 3. Слой красных линий (только если они явно заданы)
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

        // 4. Слой жилых корпусов
        var buildingsLayer = L.geoJSON(buildingsData, {{
            style: function(feature) {{
                return {{
                    color: '#1A5276',
                    weight: 1.5,
                    fillColor: feature.properties.color || '#2E86AB',
                    fillOpacity: 0.8
                }};
            }},
            onEachFeature: function(feature, layer) {{
                var p = feature.properties;
                var html = '<div class="popup-card">' +
                    '<h4 style="border-color:' + p.color + '; color:#2C3E50;">🏢 ' + p.name + '</h4>' +
                    '<div class="popup-row"><span class="popup-label">Этажность:</span><span class="popup-val">' + p.floors + ' эт.</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Типология:</span><span class="popup-val">' + p.typology + '</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Число секций:</span><span class="popup-val">' + p.sections_count + ' шт.</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Пятно застройки:</span><span class="popup-val">' + Number(p.footprint_area).toLocaleString() + ' м²</span></div>' +
                    '<div class="popup-row"><span class="popup-label">GFA (общая):</span><span class="popup-val">' + Number(p.gfa).toLocaleString() + ' м²</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Жилая площадь:</span><span class="popup-val">' + Number(p.living_area).toLocaleString() + ' м²</span></div>' +
                    '<div class="popup-row"><span class="popup-label">Квартир:</span><span class="popup-val">~' + p.apartments + ' шт.</span></div>' +
                    '</div>';
                layer.bindPopup(html, {{ className: 'custom-popup' }});

                // Подсветка при наведении
                layer.on('mouseover', function(e) {{
                    this.setStyle({{ fillOpacity: 0.95, weight: 2.5, color: '#000' }});
                }});
                layer.on('mouseout', function(e) {{
                    buildingsLayer.resetStyle(this);
                }});
            }}
        }}).addTo(map);

        // Переключатель слоёв
        var baseMaps = {{
            "🗺️ OpenStreetMap (Векторная схема)": osmStandard,
            "🏢 CartoDB Positron (Светлая)": cartoPositron,
            "🚑 OSM Humanitarian": osmHot
        }};

        var overlayMaps = {{
            "📐 Граница участка (Кадастр)": boundaryLayer,
            "🏢 Корпуса застройки": buildingsLayer
        }};
        if (buildableLayer) overlayMaps["🟩 Зона застройки"] = buildableLayer;
        if (redLinesLayer) overlayMaps["⛔ Красная линия (УДС)"] = redLinesLayer;

        L.control.layers(baseMaps, overlayMaps, {{ collapsed: false, position: 'topright' }}).addTo(map);

        // Автоматическое масштабирование под границы участка
        try {{
            var bounds = boundaryLayer.getBounds();
            if (bounds.isValid()) {{
                map.fitBounds(bounds, {{ padding: [50, 50], maxZoom: 17 }});
            }}
        }} catch(e) {{
            console.error(e);
        }}
    </script>
</body>
</html>"""
    return html_code
