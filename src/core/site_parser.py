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


def parse_coordinates(coords: list[tuple[float, float]]) -> Site:
    """Создать участок из списка координат (x, y) в метрах.

    Args:
        coords: Список кортежей (x, y). Полигон замыкается автоматически.

    Returns:
        Объект Site.

    Raises:
        ValueError: Если менее 3 точек.
    """
    if len(coords) < 3:
        raise ValueError(
            f"Для создания полигона нужно минимум 3 точки, получено {len(coords)}."
        )

    # Замыкаем полигон, если не замкнут
    if coords[0] != coords[-1]:
        coords = list(coords) + [coords[0]]

    boundary = Polygon(coords)

    if not boundary.is_valid:
        boundary = boundary.buffer(0)

    return Site(boundary=boundary)


def create_rectangular_site(
    width: float,
    height: float,
    origin: tuple[float, float] = (0.0, 0.0),
) -> Site:
    """Создать прямоугольный участок (для тестирования).

    Args:
        width: Ширина участка в метрах.
        height: Высота участка в метрах.
        origin: Координаты левого нижнего угла (x, y).

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
    return Site(boundary=boundary)
