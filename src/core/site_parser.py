"""Парсер исходных данных участка.

Функции для создания объектов Site из различных форматов:
GeoJSON, списки координат, прямоугольные участки.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Polygon, shape

from src.models.site import Site


def parse_geojson(source: str | Path | dict) -> Site:
    """Создать участок из GeoJSON Feature.

    Поддерживает:
    - Путь к файлу .geojson
    - Словарь GeoJSON Feature

    Координаты используются как есть (в локальных метрах).

    Args:
        source: Путь к файлу или словарь GeoJSON.

    Returns:
        Объект Site с полигоном границы.

    Raises:
        ValueError: Если формат данных некорректен.
    """
    # Загрузка данных
    if isinstance(source, (str, Path)):
        path = Path(source)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    elif isinstance(source, dict):
        data = source
    else:
        raise ValueError(f"Неподдерживаемый тип источника: {type(source)}")

    # Извлечение геометрии
    geometry = _extract_geometry(data)

    # Создание полигона Shapely
    boundary = shape(geometry)
    if not isinstance(boundary, Polygon):
        raise ValueError(
            f"Ожидался Polygon, получен {boundary.geom_type}. "
            "Проверьте формат геометрии."
        )

    if not boundary.is_valid:
        boundary = boundary.buffer(0)  # Исправление самопересечений

    # Извлечение красных линий (если есть)
    red_lines = _extract_red_lines(data)

    return Site(boundary=boundary, red_lines=red_lines)


def _extract_geometry(data: dict) -> dict:
    """Извлечь геометрию из GeoJSON-структуры.

    Поддерживает Feature, FeatureCollection и просто Geometry.
    """
    if "type" not in data:
        raise ValueError("GeoJSON должен содержать поле 'type'.")

    if data["type"] == "Feature":
        return data["geometry"]
    elif data["type"] == "FeatureCollection":
        features = data.get("features", [])
        if not features:
            raise ValueError("FeatureCollection пуст.")
        return features[0]["geometry"]
    elif data["type"] in ("Polygon", "MultiPolygon"):
        return data
    else:
        raise ValueError(f"Неподдерживаемый тип GeoJSON: {data['type']}")


def _extract_red_lines(data: dict) -> list[LineString]:
    """Извлечь красные линии из свойств GeoJSON (если указаны).

    Ожидает свойство 'red_lines' — список координатных пар.
    """
    red_lines: list[LineString] = []

    props = data.get("properties", {}) or {}
    red_lines_data = props.get("red_lines", [])

    for line_coords in red_lines_data:
        if len(line_coords) >= 2:
            red_lines.append(LineString(line_coords))

    return red_lines


def is_wgs84_coordinate_list(coords: list[tuple[float, float]]) -> bool:
    """Определить, являются ли переданные координаты географическими градусами WGS-84."""
    if not coords or len(coords) < 3:
        return False
    xs = [float(c[0]) for c in coords]
    ys = [float(c[1]) for c in coords]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Все точки должны быть в диапазоне [-180, 180] и [-90, 90]
    in_global_range = (
        -180.0 <= min_x <= 180.0 and -180.0 <= max_x <= 180.0 and
        -90.0 <= min_y <= 90.0 and -90.0 <= max_y <= 90.0
    )
    if not in_global_range:
        return False

    span_x = max_x - min_x
    span_y = max_y - min_y
    # Разброс одного земельного участка в градусах обычно < 0.5 градуса
    if span_x > 0.5 or span_y > 0.5:
        return False

    # В РФ: широта (lat) 35..85, долгота (lon) 15..180
    c1_is_lat = all(35.0 <= x <= 85.0 for x in xs)
    c2_is_lon = all(15.0 <= y <= 180.0 for y in ys)
    c1_is_lon = all(15.0 <= x <= 180.0 for x in xs)
    c2_is_lat = all(35.0 <= y <= 85.0 for y in ys)

    if (c1_is_lat and c2_is_lon) or (c1_is_lon and c2_is_lat):
        return True

    # Для общемировых WGS-84: если разброс маленький (< 0.05), значения дробные и удалены от (0, 0)
    has_precision = any(isinstance(c[0], float) and not float(c[0]).is_integer() for c in coords)
    is_non_zero = abs(min_x) > 1.0 or abs(min_y) > 1.0
    return span_x < 0.05 and span_y < 0.05 and has_precision and is_non_zero


def detect_lat_lon_order(coords: list[tuple[float, float]]) -> tuple[list[float], list[float]]:
    """Вернуть (lats, lons) с автоматическим распознаванием порядка (lat, lon) или (lon, lat)."""
    xs = [float(c[0]) for c in coords]
    ys = [float(c[1]) for c in coords]

    # Если первая колонка в диапазоне широт РФ (35..85), а вторая — долгот (15..180)
    if all(35.0 <= x <= 85.0 for x in xs) and all(15.0 <= y <= 180.0 for y in ys):
        return xs, ys
    # Если первая колонка — долготы, вторая — широты
    elif all(15.0 <= x <= 180.0 for x in xs) and all(35.0 <= y <= 85.0 for y in ys):
        return ys, xs

    # Если какая-то колонка > 90 по модулю — она не может быть широтой
    if any(abs(x) > 90.0 for x in xs):
        return ys, xs
    if any(abs(y) > 90.0 for y in ys):
        return xs, ys

    return ys, xs


def parse_coordinates(
    coords: list[tuple[float, float]],
    geo_center: tuple[float, float] | None = None,
) -> Site:
    """Создать участок из списка координат.

    Поддерживает:
    1. Географические координаты WGS-84 (широта, долгота или наоборот).
       Контур автоматически переводится в метры, а geo_center устанавливается
       в точные координаты участка на карте.
    2. Локальные декартовы координаты (x, y) в метрах.

    Args:
        coords: Список кортежей (x, y) или (lat, lon) / (lon, lat).
        geo_center: Опциональная географическая привязка (lat, lon).

    Returns:
        Объект Site.
    """
    if len(coords) < 3:
        raise ValueError(
            f"Для создания полигона нужно минимум 3 точки, получено {len(coords)}."
        )

    # Замыкаем полигон, если не замкнут
    if coords[0] != coords[-1]:
        coords = list(coords) + [coords[0]]

    if is_wgs84_coordinate_list(coords):
        import shapely.affinity
        from src.core.geo_utils import wgs84_to_metric_coords

        lats, lons = detect_lat_lon_order(coords)
        c_lat = sum(lats[:-1]) / (len(lats) - 1)
        c_lon = sum(lons[:-1]) / (len(lons) - 1)

        # Переводим в локальные метры относительно географического центра
        lon_lat_pairs = list(zip(lons, lats))
        pts_metric = wgs84_to_metric_coords(lon_lat_pairs, c_lat, c_lon, is_lon_lat=True)
        boundary = Polygon(pts_metric)
        if not boundary.is_valid:
            boundary = boundary.buffer(0)

        # Нормализуем контур так, чтобы минимальные координаты начинались с (0, 0)
        minx, miny, _, _ = boundary.bounds
        boundary = shapely.affinity.translate(boundary, -minx, -miny)

        return Site(
            boundary=boundary,
            geo_center=(c_lat, c_lon),
            address=f"Координаты WGS-84: {c_lat:.6f}, {c_lon:.6f}",
        )

    # Локальные метры
    boundary = Polygon(coords)
    if not boundary.is_valid:
        boundary = boundary.buffer(0)

    return Site(boundary=boundary, geo_center=geo_center)


def create_rectangular_site(
    width: float,
    height: float,
    origin: tuple[float, float] = (0.0, 0.0),
    geo_center: tuple[float, float] | None = None,
) -> Site:
    """Создать прямоугольный участок (для тестирования).

    Args:
        width: Ширина участка в метрах.
        height: Высота участка в метрах.
        origin: Координаты левого нижнего угла (x, y).
        geo_center: Опциональная географическая привязка (lat, lon).

    Returns:
        Объект Site с прямоугольной границей.
    """
    x0, y0 = origin
    coords = [
        (x0, y0),
        (x0 + width, y0),
        (x0 + width, y0 + height),
        (x0, y0 + height),
        (x0, y0),
    ]
    boundary = Polygon(coords)
    return Site(boundary=boundary, geo_center=geo_center)
