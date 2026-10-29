"""Модуль загрузки и кэширования окружающей застройки из OpenStreetMap (OSM) для 3D-визуализации."""

from __future__ import annotations

import json
import math
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests
from shapely.geometry import Polygon, shape

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "osm_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        s = str(val).lower().replace("m", "").replace("м", "").replace(",", ".").strip()
        # Если указан диапазон "2-3", берём большее
        if "-" in s:
            s = s.split("-")[-1].strip()
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_levels_and_height(tags: dict[str, str]) -> tuple[int, float]:
    """Извлечь этажность и высоту здания из тегов OSM со вспомогательными эвристиками."""
    raw_levels = tags.get("building:levels") or tags.get("levels")
    raw_height = tags.get("height")

    f_levels = _safe_float(raw_levels)
    f_height = _safe_float(raw_height)

    levels: int | None = max(1, round(f_levels)) if f_levels and f_levels > 0 else None
    height: float | None = f_height if f_height and f_height > 0 else None

    b_type = tags.get("building", "yes").lower()

    if levels is not None and height is None:
        height = round(levels * 3.0, 1)
    elif height is not None and levels is None:
        levels = max(1, round(height / 3.0))
    elif levels is None and height is None:
        # Эвристика по типологии здания в OSM
        if b_type in ("apartments", "residential"):
            levels = 5
            height = 15.0
        elif b_type in ("house", "detached", "semi", "cabin", "bungalow", "shed", "garage", "terrace"):
            levels = 2
            height = 6.0
        elif b_type in ("school", "kindergarten", "hospital", "university", "commercial", "retail", "office", "public"):
            levels = 3
            height = 10.0
        elif b_type in ("industrial", "warehouse", "hangar"):
            levels = 1
            height = 8.0
        elif b_type in ("church", "cathedral", "temple"):
            levels = 2
            height = 16.0
        else:
            levels = 2
            height = 6.0

    return levels, round(height, 1)


def get_surrounding_buildings(
    center_lat: float,
    center_lon: float,
    radius_m: float = 400.0,
    exclude_geom: Any | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Получить GeoJSON FeatureCollection окружающей застройки вокруг координат участка.

    Args:
        center_lat: Широта центра участка (WGS84).
        center_lon: Долгота центра участка (WGS84).
        radius_m: Радиус охвата в метрах от центра (по умолчанию 400м).
        exclude_geom: Геометрия участка в WGS84 (Shapely Polygon), здания внутри которого исключаются.
        use_cache: Использовать ли локальный кэш на диске.

    Returns:
        GeoJSON FeatureCollection со зданиями (полигоны с properties: name, levels, height, building_type).
    """
    if abs(center_lat) < 1.0 and abs(center_lon) < 1.0:
        return {"type": "FeatureCollection", "features": []}

    cache_file = CACHE_DIR / f"osm_surroundings_{center_lat:.4f}_{center_lon:.4f}_{int(radius_m)}.geojson"

    # 1. Чтение из кэша
    if use_cache and cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("type") == "FeatureCollection":
                    # Если передан exclude_geom, дополнительно отфильтруем кэш при необходимости
                    if exclude_geom is not None and not exclude_geom.is_empty:
                        filtered = []
                        for feat in data.get("features", []):
                            try:
                                poly = shape(feat["geometry"])
                                if not poly.intersects(exclude_geom):
                                    filtered.append(feat)
                            except Exception:
                                filtered.append(feat)
                        return {"type": "FeatureCollection", "features": filtered}
                    return data
        except Exception:
            pass

    # 2. Вычисление BBox
    dlat = radius_m / 111139.0
    dlon = radius_m / (111139.0 * math.cos(math.radians(center_lat)))
    min_lon = center_lon - dlon
    min_lat = center_lat - dlat
    max_lon = center_lon + dlon
    max_lat = center_lat + dlat

    url = f"https://api.openstreetmap.org/api/0.6/map?bbox={min_lon:.5f},{min_lat:.5f},{max_lon:.5f},{max_lat:.5f}"
    headers = {"User-Agent": "Antigravity3DViewer/1.0 (urban_planning_ai)"}

    try:
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"[OSM Surroundings] Предупреждение: Не удалось загрузить OSM для [{center_lat:.4f}, {center_lon:.4f}]: {e}")
        return {"type": "FeatureCollection", "features": []}

    # 3. Индексация узлов
    nodes: dict[str, tuple[float, float]] = {}
    for node in root.findall("node"):
        nid = node.attrib.get("id")
        lat = node.attrib.get("lat")
        lon = node.attrib.get("lon")
        if nid and lat and lon:
            nodes[nid] = (float(lon), float(lat))

    # 4. Парсинг полигонов зданий
    features: list[dict[str, Any]] = []

    for way in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag") if "k" in tag.attrib and "v" in tag.attrib}
        if "building" not in tags:
            continue

        nd_refs = [nd.attrib.get("ref") for nd in way.findall("nd") if "ref" in nd.attrib]
        if len(nd_refs) < 4 or nd_refs[0] != nd_refs[-1]:
            continue

        coords = [nodes[ref] for ref in nd_refs if ref in nodes]
        if len(coords) < 4 or coords[0] != coords[-1]:
            continue

        # Фильтрация по пересечению с границей проектируемого участка
        if exclude_geom is not None and not exclude_geom.is_empty:
            try:
                b_poly = Polygon(coords)
                if b_poly.intersects(exclude_geom):
                    continue
            except Exception:
                pass

        levels, height = _parse_levels_and_height(tags)
        b_type = tags.get("building", "yes").lower()

        name = tags.get("name") or tags.get("addr:housenumber") or ""
        street = tags.get("addr:street") or ""
        if street and name:
            full_name = f"{street}, {name}"
        elif name:
            full_name = f"д. {name}"
        else:
            full_name = tags.get("description") or f"Здание ({b_type})"

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [coords]
            },
            "properties": {
                "id": f"osm_{way.attrib.get('id', '')}",
                "name": full_name,
                "building_type": b_type,
                "levels": levels,
                "floors": levels,
                "height": height,
                "height_m": height,
                "min_height": 0.0,
                "is_surrounding": True,
            }
        })

    fc = {
        "type": "FeatureCollection",
        "features": features
    }

    # 5. Сохранение в кэш
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)
    except Exception:
        pass

    return fc
