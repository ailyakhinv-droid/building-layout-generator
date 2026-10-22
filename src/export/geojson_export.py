"""Экспорт результатов в GeoJSON.

Формирует GeoJSON FeatureCollection с размещёнными зданиями
и технико-экономическими показателями.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shapely.geometry import mapping

from src.models.building import Building
from src.models.site import Site
from src.models.tep import TEP


def export_geojson(
    site: Site,
    buildings: list[Building],
    tep: TEP,
    filepath: str | Path,
    as_wgs84: bool = True,
) -> None:
    """Экспортировать план застройки в GeoJSON.

    Args:
        site: Участок.
        buildings: Размещённые здания.
        tep: Рассчитанные ТЭП.
        filepath: Путь для сохранения файла.
        as_wgs84: Перевести ли координаты в географические WGS-84 (lon, lat)
                 для совместимости с QGIS / Kepler.gl / картографическими сервисами.
    """
    from src.core.geo_utils import transform_geometry_to_wgs84

    use_wgs = as_wgs84 and (site.geo_center is not None)
    c_lat, c_lon = site.geo_center if use_wgs else (0.0, 0.0)

    def _geom_to_map(geom):
        if use_wgs:
            return mapping(transform_geometry_to_wgs84(geom, c_lat, c_lon))
        return mapping(geom)

    features = []

    # Участок
    features.append({
        "type": "Feature",
        "geometry": _geom_to_map(site.boundary),
        "properties": {
            "type": "site_boundary",
            "cadastral_number": site.cadastral_number or "Не указан",
            "address": site.address or "—",
            "area": round(site.area, 1),
            "area_ha": round(site.area / 10000.0, 2),
        },
    })

    # Зона застройки
    if site.buildable_area is not None and not site.buildable_area.is_empty:
        features.append({
            "type": "Feature",
            "geometry": _geom_to_map(site.buildable_area),
            "properties": {
                "type": "buildable_area",
                "area": round(site.buildable_area.area, 1),
            },
        })

    # Красные линии
    for idx, rl in enumerate(site.red_lines):
        if not rl.is_empty:
            features.append({
                "type": "Feature",
                "geometry": _geom_to_map(rl),
                "properties": {
                    "type": "red_line",
                    "id": idx + 1,
                },
            })

    # Здания
    for i, building in enumerate(buildings):
        # Целое здание
        features.append({
            "type": "Feature",
            "geometry": _geom_to_map(building.footprint),
            "properties": {
                "type": "building",
                "building_id": i + 1,
                "floors": building.floors,
                "height": building.height,
                "gfa": round(building.total_gfa, 1),
                "building_area": round(building.total_building_area, 1),
                "apartments": building.total_apartments,
                "sections_count": len(building.sections),
            },
        })

        # Секции
        for j, section in enumerate(building.sections):
            features.append({
                "type": "Feature",
                "geometry": _geom_to_map(section.footprint),
                "properties": {
                    "type": "section",
                    "building_id": i + 1,
                    "section_index": j + 1,
                    "section_type": section.section_type.id,
                    "section_name": section.section_type.name,
                    "category": section.section_type.category,
                    "floors": section.floors,
                },
            })

    # ТЭП как отдельный Feature (точка в центре участка)
    centroid = site.boundary.centroid
    features.append({
        "type": "Feature",
        "geometry": _geom_to_map(centroid),
        "properties": {
            "type": "tep_summary",
            **tep.to_dict(),
        },
    })

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)
