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
) -> None:
    """Экспортировать план застройки в GeoJSON.

    Args:
        site: Участок.
        buildings: Размещённые здания.
        tep: Рассчитанные ТЭП.
        filepath: Путь для сохранения файла.
    """
    features = []

    # Участок
    features.append({
        "type": "Feature",
        "geometry": mapping(site.boundary),
        "properties": {
            "type": "site_boundary",
            "area": round(site.area, 1),
        },
    })

    # Зона застройки
    if site.buildable_area is not None:
        features.append({
            "type": "Feature",
            "geometry": mapping(site.buildable_area),
            "properties": {
                "type": "buildable_area",
                "area": round(site.buildable_area.area, 1),
            },
        })

    # Здания
    for i, building in enumerate(buildings):
        # Целое здание
        features.append({
            "type": "Feature",
            "geometry": mapping(building.footprint),
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
                "geometry": mapping(section.footprint),
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
        "geometry": mapping(centroid),
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
