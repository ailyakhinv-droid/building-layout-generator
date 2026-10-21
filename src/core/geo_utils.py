"""Модуль геодезических преобразований и работы с географическими координатами.

Обеспечивает точный перевод между локальными декартовыми координатами (метры),
используемыми алгоритмом расстановки зданий, и географическими координатами WGS-84
(широта, долгота) для отображения на картографической подложке (OpenStreetMap).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping

# Параметры эллипсоида WGS-84 (GRS 80)
WGS84_A: float = 6378137.0  # Большая полуось, м
WGS84_F: float = 1.0 / 298.257223563  # Сжатие
WGS84_E2: float = 2 * WGS84_F - WGS84_F * WGS84_F  # Квадрат первого эксцентриситета


def _get_radii_of_curvature(lat_deg: float) -> tuple[float, float, float]:
    """Вычислить радиусы кривизны эллипсоида WGS-84 для заданной широты.

    Args:
        lat_deg: Широта в градусах.

    Returns:
        Кортеж (M, N, cos_lat):
            M — радиус кривизны меридиана (для изменения широты dlat).
            N — радиус кривизны первого вертикала (для изменения долготы dlon).
            cos_lat — косинус широты.
    """
    lat_rad = math.radians(lat_deg)
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    denom = math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)

    M = WGS84_A * (1.0 - WGS84_E2) / (denom * denom * denom)
    N = WGS84_A / denom
    return M, N, cos_lat


def metric_to_wgs84_coords(
    coords: np.ndarray | list[tuple[float, float]],
    center_lat: float,
    center_lon: float,
) -> np.ndarray:
    """Перевести координаты из локальных метров (X, Y) в географические (lon, lat) WGS-84.

    Args:
        coords: Массив или список координат [(x, y), ...] в метрах.
        center_lat: Географическая широта точки отсчёта (0, 0).
        center_lon: Географическая долгота точки отсчёта (0, 0).

    Returns:
        Массив numpy формы (N, 2) с координатами [lon, lat] (формат GeoJSON).
    """
    arr = np.asarray(coords, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)

    M, N, cos_lat = _get_radii_of_curvature(center_lat)

    x = arr[:, 0]
    y = arr[:, 1]

    dlat = (y / M) * (180.0 / math.pi)
    dlon = (x / (N * cos_lat)) * (180.0 / math.pi)

    lon = center_lon + dlon
    lat = center_lat + dlat

    return np.column_stack((lon, lat))


def wgs84_to_metric_coords(
    coords: np.ndarray | list[tuple[float, float]],
    center_lat: float,
    center_lon: float,
    is_lon_lat: bool = True,
) -> np.ndarray:
    """Перевести координаты из WGS-84 в локальные метры (X, Y).

    Args:
        coords: Список или массив координат.
        center_lat: Географическая широта точки отсчёта (0, 0).
        center_lon: Географическая долгота точки отсчёта (0, 0).
        is_lon_lat: Если True — порядок входных координат [lon, lat] (GeoJSON),
                    если False — [lat, lon].

    Returns:
        Массив numpy формы (N, 2) с метрическими координатами [x, y].
    """
    arr = np.asarray(coords, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)

    M, N, cos_lat = _get_radii_of_curvature(center_lat)

    if is_lon_lat:
        lon = arr[:, 0]
        lat = arr[:, 1]
    else:
        lat = arr[:, 0]
        lon = arr[:, 1]

    dlat_rad = np.radians(lat - center_lat)
    dlon_rad = np.radians(lon - center_lon)

    y = dlat_rad * M
    x = dlon_rad * N * cos_lat

    return np.column_stack((x, y))


def transform_geometry_to_wgs84(
    geom: shapely.Geometry,
    center_lat: float,
    center_lon: float,
) -> shapely.Geometry:
    """Трансформировать геометрию Shapely из локальных метров в WGS-84 (lon, lat).

    Args:
        geom: Геометрия Shapely в метрах.
        center_lat: Широта точки привязки.
        center_lon: Долгота точки привязки.

    Returns:
        Геометрия Shapely в градусах WGS-84 (lon, lat).
    """
    def _transformer(coords: np.ndarray) -> np.ndarray:
        return metric_to_wgs84_coords(coords, center_lat, center_lon)

    return shapely.transform(geom, _transformer)


def transform_geometry_to_metric(
    geom: shapely.Geometry,
    center_lat: float,
    center_lon: float,
) -> shapely.Geometry:
    """Трансформировать геометрию Shapely из WGS-84 (lon, lat) в локальные метры.

    Args:
        geom: Геометрия Shapely в градусах WGS-84.
        center_lat: Широта точки привязки.
        center_lon: Долгота точки привязки.

    Returns:
        Геометрия Shapely в метрах (X, Y).
    """
    def _transformer(coords: np.ndarray) -> np.ndarray:
        return wgs84_to_metric_coords(coords, center_lat, center_lon, is_lon_lat=True)

    return shapely.transform(geom, _transformer)


def geometry_to_geojson_dict(
    geom: shapely.Geometry,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Сконвертировать геометрию Shapely в GeoJSON Feature словарь."""
    return {
        "type": "Feature",
        "geometry": mapping(geom),
        "properties": properties or {},
    }
