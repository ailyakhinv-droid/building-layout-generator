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


def geocode_address(query: str, timeout: float = 3.5) -> tuple[float, float, str] | None:
    """Геокодировать текстовый адрес в координаты WGS-84 (lat, lon) через ArcGIS API.

    Использует открытый сервис ArcGIS World Geocoding Service (как в блокноте geocode.ipynb),
    не требующий платных ключей и корректно распознающий российские адреса.

    Args:
        query: Текстовый адрес (например, "Самара, Зубчаниновка", "Тюмень, ул. Ленина").
        timeout: Таймаут запроса в секундах.

    Returns:
        Кортеж (latitude, longitude, match_address) или None в случае неудачи.
    """
    import json
    import urllib.parse
    import urllib.request

    url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
    params = {
        "f": "json",
        "singleLine": query.strip(),
        "maxLocations": 1,
        "outFields": "Match_addr,City,Region,Subregion",
    }
    try:
        full_url = url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(full_url, headers={"User-Agent": "BuildingGenerator/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidates = data.get("candidates", [])
            if candidates:
                loc = candidates[0]["location"]
                addr = candidates[0].get("address", query)
                lat = float(loc["y"])
                lon = float(loc["x"])
                if 40.0 <= lat <= 75.0 and 19.0 <= lon <= 180.0:
                    return lat, lon, addr
    except Exception:
        pass
    return None


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


# ─── Пресеты городов РФ для геопривязки ─────────────────────────────────────
CITY_PRESETS: dict[str, dict[str, Any]] = {
    "Самара": {
        "region_code": "63",
        "region_name": "Самарская область",
        "norm_id": "russia_sp42",
        "center_lat": 53.1959,
        "center_lon": 50.1002,
        "msk_preset": "МСК-63 Зона 1 (Самара)",
    },
    "Москва": {
        "region_code": "77",
        "region_name": "г. Москва",
        "norm_id": "moscow_mngp",
        "center_lat": 55.7512,
        "center_lon": 37.6184,
        "msk_preset": "МСК-77 (Москва)",
    },
    "Санкт-Петербург": {
        "region_code": "78",
        "region_name": "г. Санкт-Петербург",
        "norm_id": "spb_rngp",
        "center_lat": 59.9386,
        "center_lon": 30.3141,
        "msk_preset": "МСК-78 (Санкт-Петербург)",
    },
    "Московская область (Подольск)": {
        "region_code": "50",
        "region_name": "Московская область",
        "norm_id": "moscow_oblast_rngp",
        "center_lat": 55.4312,
        "center_lon": 37.5458,
        "msk_preset": "МСК-50 Зона 1 (МО Запад)",
    },
    "Казань": {
        "region_code": "16",
        "region_name": "Республика Татарстан",
        "norm_id": "russia_sp42",
        "center_lat": 55.7887,
        "center_lon": 49.1221,
        "msk_preset": "МСК-16 Зона 1 (Татарстан)",
    },
    "Екатеринбург": {
        "region_code": "66",
        "region_name": "Свердловская область",
        "norm_id": "russia_sp42",
        "center_lat": 56.8389,
        "center_lon": 60.6057,
        "msk_preset": "МСК-66 Зона 1 (Свердловская обл.)",
    },
    "Краснодар": {
        "region_code": "23",
        "region_name": "Краснодарский край",
        "norm_id": "krasnodar_rngp",
        "center_lat": 45.0355,
        "center_lon": 38.9753,
        "msk_preset": "МСК-23 Зона 1 (Краснодар)",
    },
    "Новосибирск": {
        "region_code": "54",
        "region_name": "Новосибирская область",
        "norm_id": "russia_sp42",
        "center_lat": 55.0084,
        "center_lon": 82.9357,
        "msk_preset": None,
    },
    "Нижний Новгород": {
        "region_code": "52",
        "region_name": "Нижегородская область",
        "norm_id": "russia_sp42",
        "center_lat": 56.2965,
        "center_lon": 43.9361,
        "msk_preset": None,
    },
    "Тюмень": {
        "region_code": "72",
        "region_name": "Тюменская область",
        "norm_id": "russia_sp42",
        "center_lat": 57.1530,
        "center_lon": 65.5343,
        "msk_preset": "МСК-72 Зона 1 (Тюмень)",
    },
    "Барнаул": {
        "region_code": "22",
        "region_name": "Алтайский край",
        "norm_id": "russia_sp42",
        "center_lat": 53.3481,
        "center_lon": 83.7799,
        "msk_preset": "МСК-22 Зона 2 (Барнаул)",
    },
    "Уфа": {
        "region_code": "02",
        "region_name": "Республика Башкортостан",
        "norm_id": "russia_sp42",
        "center_lat": 54.7388,
        "center_lon": 55.9721,
        "msk_preset": None,
    },
    "Ростов-на-Дону": {
        "region_code": "61",
        "region_name": "Ростовская область",
        "norm_id": "russia_sp42",
        "center_lat": 47.2357,
        "center_lon": 39.7015,
        "msk_preset": None,
    },
}


# ─── Параметры МСК (Местных систем координат РФ) по ГОСТ 32453-2019 ─────────
# Делегировано в специализированный модуль src.geo.msk_converter
from src.geo.msk_converter import (
    MSK_PRESETS,
    ZONE_ALIASES,
    resolve_zone_preset,
    wgs84_to_msk_coords,
    msk_to_wgs84_coords,
    detect_msk_by_coordinates,
    get_msk_key_for_region,
    _single_gk_inverse,
)
