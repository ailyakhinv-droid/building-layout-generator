"""Вычисление зоны допустимой застройки.

Модуль для определения зоны допустимой застройки с учётом
нормативных отступов, а также определения ориентации участка.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from shapely.geometry import LineString, Polygon
from shapely import minimum_rotated_rectangle

from src.models.site import Site


def compute_buildable_area(site: Site, config: dict[str, Any]) -> Polygon:
    """Вычислить зону допустимой застройки.

    Применяет нормативные отступы от границы участка и красных линий.

    Args:
        site: Земельный участок.
        config: Конфигурация с параметрами отступов.

    Returns:
        Полигон зоны допустимой застройки.
    """
    boundary_setback = config.get("boundary_setback", 6.0)
    red_line_setback = config.get("red_line_setback", 5.0)

    return site.compute_buildable_area(boundary_setback, red_line_setback)


def get_oriented_bbox(polygon: Polygon) -> tuple[Polygon, float]:
    """Получить ориентированный ограничивающий прямоугольник.

    Args:
        polygon: Исходный полигон.

    Returns:
        Кортеж (прямоугольник, угол_поворота_в_градусах).
        Угол — направление длинной стороны относительно оси X.
    """
    obb = minimum_rotated_rectangle(polygon)

    # Определяем угол длинной стороны
    coords = list(obb.exterior.coords)
    edges = []
    for i in range(len(coords) - 1):
        dx = coords[i + 1][0] - coords[i][0]
        dy = coords[i + 1][1] - coords[i][1]
        length = math.sqrt(dx * dx + dy * dy)
        angle = math.degrees(math.atan2(dy, dx))
        edges.append((length, angle))

    # Длинная сторона — определяет основное направление
    edges.sort(key=lambda e: e[0], reverse=True)
    primary_angle = edges[0][1]

    # Нормализуем угол в диапазон [0, 180)
    primary_angle = primary_angle % 180

    return obb, primary_angle


def get_primary_axes(polygon: Polygon) -> tuple[float, float]:
    """Получить два перпендикулярных направления участка.

    Args:
        polygon: Полигон участка.

    Returns:
        Кортеж (угол_основной_оси, угол_перпендикулярной_оси) в градусах.
    """
    _, primary_angle = get_oriented_bbox(polygon)
    perpendicular_angle = (primary_angle + 90) % 180
    return primary_angle, perpendicular_angle


def get_obb_dimensions(polygon: Polygon) -> tuple[float, float, float]:
    """Получить размеры ориентированного ограничивающего прямоугольника.

    Args:
        polygon: Полигон участка.

    Returns:
        Кортеж (длина, ширина, угол_длинной_стороны).
    """
    obb = minimum_rotated_rectangle(polygon)
    coords = list(obb.exterior.coords)

    # Вычисляем длины сторон
    side1 = math.sqrt(
        (coords[1][0] - coords[0][0]) ** 2 + (coords[1][1] - coords[0][1]) ** 2
    )
    side2 = math.sqrt(
        (coords[2][0] - coords[1][0]) ** 2 + (coords[2][1] - coords[1][1]) ** 2
    )

    if side1 >= side2:
        length, width = side1, side2
        dx = coords[1][0] - coords[0][0]
        dy = coords[1][1] - coords[0][1]
    else:
        length, width = side2, side1
        dx = coords[2][0] - coords[1][0]
        dy = coords[2][1] - coords[1][1]

    angle = math.degrees(math.atan2(dy, dx)) % 180

    return length, width, angle
