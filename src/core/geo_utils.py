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
# Проекция Гаусса-Крюгера на эллипсоиде Красовского 1940
MSK_PRESETS: dict[str, dict[str, Any]] = {
    "МСК-63 Зона 1 (Самара)": {
        "region": "Самарская область",
        "city": "Самара",
        "L0_deg": 49.03333333333333,  # 49° 02'
        "x0": -5414743.504,
        "y0": 1500000.0,
        "default_lat": 53.1959,
        "default_lon": 50.1002,
    },
    "МСК-63 Зона 2 (Тольятти)": {
        "region": "Самарская область",
        "city": "Тольятти",
        "L0_deg": 52.03333333333333,  # 52° 02'
        "x0": -5414743.504,
        "y0": 2500000.0,
        "default_lat": 53.5078,
        "default_lon": 49.4204,
    },
    "МСК-77 (Москва)": {
        "region": "г. Москва",
        "city": "Москва",
        "L0_deg": 37.5,
        "x0": -11000.0,
        "y0": 16000.0,
        "default_lat": 55.7512,
        "default_lon": 37.6184,
    },
    "МСК-50 Зона 1 (МО Запад)": {
        "region": "Московская область",
        "city": "Подольск / Красногорск",
        "L0_deg": 35.48333333333333,  # 35° 29'
        "x0": -5711057.63,
        "y0": 1250000.0,
        "default_lat": 55.4312,
        "default_lon": 37.5458,
    },
    "МСК-50 Зона 2 (МО Восток)": {
        "region": "Московская область",
        "city": "Мытищи / Балашиха",
        "L0_deg": 38.48333333333333,  # 38° 29'
        "x0": -5711057.63,
        "y0": 2250000.0,
        "default_lat": 55.8036,
        "default_lon": 37.9546,
    },
    "МСК-78 (Санкт-Петербург)": {
        "region": "г. Санкт-Петербург",
        "city": "Санкт-Петербург",
        "L0_deg": 30.3141,
        "x0": 0.0,
        "y0": 0.0,
        "default_lat": 59.9386,
        "default_lon": 30.3141,
    },
    "МСК-16 Зона 1 (Татарстан)": {
        "region": "Республика Татарстан",
        "city": "Казань",
        "L0_deg": 49.03333333333333,
        "x0": -5714743.504,
        "y0": 1500000.0,
        "default_lat": 55.7887,
        "default_lon": 49.1221,
    },
    "МСК-66 Зона 1 (Свердловская обл.)": {
        "region": "Свердловская область",
        "city": "Екатеринбург",
        "L0_deg": 60.05,
        "x0": -6014743.504,
        "y0": 1500000.0,
        "default_lat": 56.8389,
        "default_lon": 60.6057,
    },
    "МСК-23 Зона 1 (Краснодар)": {
        "region": "Краснодарский край",
        "city": "Краснодар",
        "L0_deg": 38.98333333333333,
        "x0": -4514743.504,
        "y0": 1500000.0,
        "default_lat": 45.0355,
        "default_lon": 38.9753,
    },
    "МСК-72 Зона 1 (Тюмень)": {
        "region": "Тюменская область",
        "city": "Тюмень",
        "L0_deg": 65.51666667,  # 65° 31'
        "x0": -6000000.0,
        "y0": 1500000.0,
        "default_lat": 57.1530,
        "default_lon": 65.5343,
    },
    "МСК-72 Зона 2 (Тобольск / Ишим)": {
        "region": "Тюменская область",
        "city": "Тобольск",
        "L0_deg": 68.51666667,  # 68° 31'
        "x0": -6000000.0,
        "y0": 2500000.0,
        "default_lat": 58.1980,
        "default_lon": 68.2540,
    },
    "МСК-22 Зона 2 (Барнаул)": {
        "region": "Алтайский край",
        "city": "Барнаул",
        "L0_deg": 83.73333333,  # 83° 44'
        "x0": -5714743.504,
        "y0": 2500000.0,
        "default_lat": 53.3481,
        "default_lon": 83.7799,
    },
}


def get_msk_key_for_region(
    region_code: str,
    coord1: float | None = None,
    coord2: float | None = None,
) -> str | None:
    """Определить подходящую систему координат МСК для заданного кода региона РФ.

    Автоматически определяет номер зоны Гаусса-Крюгера (1 или 2) по координате Востока.

    Args:
        region_code: 2-значный код субъекта РФ (например, '63', '77', '50', '72', '22').
        coord1: Первая координата (X в CAD или Север в геодезии).
        coord2: Вторая координата (Y в CAD или Восток в геодезии).

    Returns:
        Название ключа из MSK_PRESETS или None.
    """
    clean_code = str(region_code).zfill(2)
    vals = [abs(float(c)) for c in (coord1, coord2) if c is not None]
    easting = max(vals) if vals else 0.0

    if clean_code == "63":
        return "МСК-63 Зона 2 (Тольятти)" if easting > 2000000.0 else "МСК-63 Зона 1 (Самара)"
    elif clean_code == "77":
        return "МСК-77 (Москва)"
    elif clean_code == "50":
        return "МСК-50 Зона 2 (МО Восток)" if easting > 2000000.0 else "МСК-50 Зона 1 (МО Запад)"
    elif clean_code == "78":
        return "МСК-78 (Санкт-Петербург)"
    elif clean_code == "16":
        return "МСК-16 Зона 1 (Татарстан)"
    elif clean_code == "66":
        return "МСК-66 Зона 1 (Свердловская обл.)"
    elif clean_code == "23":
        return "МСК-23 Зона 1 (Краснодар)"
    elif clean_code == "72":
        return "МСК-72 Зона 2 (Тобольск / Ишим)" if easting > 2000000.0 else "МСК-72 Зона 1 (Тюмень)"
    elif clean_code == "22":
        return "МСК-22 Зона 2 (Барнаул)"
    return None


def _single_gk_inverse(
    northing: float,
    easting: float,
    p: dict[str, Any],
) -> tuple[float, float]:
    """Выполнить обратное преобразование Гаусса-Крюгера (Красовский 1940 -> WGS-84).

    Args:
        northing: Прямоугольная координата Севера (м).
        easting: Прямоугольная координата Востока (м) со смещением зоны.
        p: Словарь параметров МСК из MSK_PRESETS.

    Returns:
        Кортеж (lat_wgs, lon_wgs) в градусах.
    """
    x_gk = northing - p["x0"]
    y_gk = easting - p["y0"]
    L0_deg = p["L0_deg"]

    # Параметры эллипсоида Красовского 1940
    a = 6378245.0
    f = 1.0 / 298.3
    e2 = 2 * f - f * f
    e1_2 = e2 / (1.0 - e2)

    A0 = 1.0 - e2 / 4.0 - 3.0 * (e2**2) / 64.0 - 5.0 * (e2**3) / 256.0
    B_appr = x_gk / (a * A0)
    for _ in range(6):
        s = a * (
            A0 * B_appr
            - (3.0 * e2 / 8.0 + 3.0 * (e2**2) / 32.0) * math.sin(2.0 * B_appr)
            + (15.0 * (e2**2) / 256.0) * math.sin(4.0 * B_appr)
        )
        diff = (x_gk - s) / (a * (1.0 - e2) / ((1.0 - e2 * math.sin(B_appr) ** 2) ** 1.5))
        B_appr += diff
        if abs(diff) < 1e-10:
            break

    Bf = B_appr
    sinBf = math.sin(Bf)
    cosBf = math.cos(Bf)
    tanBf = math.tan(Bf)

    denom = math.sqrt(1.0 - e2 * sinBf * sinBf)
    Nf = a / denom
    Mf = a * (1.0 - e2) / (denom * denom * denom)
    eta2 = e1_2 * cosBf * cosBf

    y_N = y_gk / Nf
    lat_sk42 = Bf - (tanBf / (2.0 * Mf / Nf)) * (
        y_N**2 - (y_N**4) / 12.0 * (5.0 + 3.0 * tanBf**2 + eta2 - 9.0 * eta2 * tanBf**2)
    )
    lon_sk42 = (1.0 / cosBf) * (
        y_N - (y_N**3) / 6.0 * (1.0 + 2.0 * tanBf**2 + eta2)
    )

    lat_kr = math.degrees(lat_sk42)
    lon_kr = L0_deg + math.degrees(lon_sk42)

    # 3-параметрический переход СК-42 -> WGS-84 (ГОСТ 32453)
    b_rad = math.radians(lat_kr)
    l_rad = math.radians(lon_kr)
    dx, dy, dz = 23.57, -140.95, -79.8
    N = a / math.sqrt(1.0 - e2 * math.sin(b_rad) ** 2)
    M = a * (1.0 - e2) / ((1.0 - e2 * math.sin(b_rad) ** 2) ** 1.5)

    lat_wgs = lat_kr + (
        dz * math.cos(b_rad)
        - (dx * math.cos(l_rad) + dy * math.sin(l_rad)) * math.sin(b_rad)
    ) / M * (180.0 / math.pi)
    lon_wgs = lon_kr + (-dx * math.sin(l_rad) + dy * math.cos(l_rad)) / (
        N * math.cos(b_rad)
    ) * (180.0 / math.pi)

    return lat_wgs, lon_wgs


def msk_to_wgs84_coords(
    coord1: float,
    coord2: float,
    msk_key: str,
    axis_order: str = "auto",
    expected_center: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """Преобразовать прямоугольные координаты МСК (метры) в WGS-84 (lat, lon).

    Интеллектуальный алгоритм:
    - Автоматически распознает ориентацию осей (CAD: X=Восток, Y=Север vs Геодезия: X=Север, Y=Восток).
    - Корректно восстанавливает усечённые координаты Востока (без префикса номера зоны +1 млн или без сдвига +1.5 млн).
    - Проверяет кандидатов относительно ожидаемого центра региона, исключая телепортацию в другие субъекты РФ.

    Args:
        coord1: Первая координата (X в CAD или Север в геодезии).
        coord2: Вторая координата (Y в CAD или Восток в геодезии).
        msk_key: Ключ из MSK_PRESETS.
        axis_order: "auto" (интеллектуальный автоподбор),
                    "cad" (coord1=Восток, coord2=Север),
                    "geodetic" (coord1=Север, coord2=Восток),
                    "swap" (принудительно поменять оси местами).
        expected_center: Ожидаемый географический центр (lat, lon) для валидации и выбора ветви.

    Returns:
        Кортеж (latitude, longitude) в градусах WGS-84.
    """
    p = MSK_PRESETS.get(msk_key)
    if not p:
        return (55.7512, 37.6184)

    # Если для системы задан простой дефолтный центр (МСК-78 / городские СК без ключа)
    if p["x0"] == 0.0 and p["y0"] == 0.0:
        return (p["default_lat"], p["default_lon"])

    c1 = float(coord1)
    c2 = float(coord2)

    exp_lat, exp_lon = expected_center if expected_center else (p["default_lat"], p["default_lon"])

    # Формируем пары кандидатов (Север, Восток) в зависимости от выбранного режима
    base_pairs: list[tuple[float, float, str]] = []
    if axis_order == "cad":
        base_pairs = [(c2, c1, "cad_X_east_Y_north")]
    elif axis_order == "geodetic":
        base_pairs = [(c1, c2, "geodetic_X_north_Y_east")]
    elif axis_order == "swap":
        base_pairs = [(c2, c1, "swap_axes")]
    else:
        # Режим 'auto': генерируем оба варианта осей
        # Если величины резко отличаются (одна > 800к, другая < 800к), упорядочиваем
        if c1 > 800000.0 and c2 < 800000.0:
            base_pairs = [(c2, c1, "auto_cad"), (c1, c2, "auto_geo")]
        elif c2 > 800000.0 and c1 < 800000.0:
            base_pairs = [(c1, c2, "auto_geo"), (c2, c1, "auto_cad")]
        else:
            base_pairs = [(c1, c2, "auto_geo"), (c2, c1, "auto_cad")]

    # Расширяем кандидатов вариантами восстановления усечённых координат Востока:
    # 1. Полный Восток (как есть)
    # 2. Восток без номера зоны (например, 580k вместо 1.58M -> добавляем zone_num * 1M)
    # 3. Восток без ложного сдвига (например, 80k вместо 1.58M -> добавляем y0 = 1.5M)
    expanded: list[tuple[float, float, str]] = []
    zone_num = int(p["y0"] // 1000000.0) if p["y0"] >= 1000000.0 else 1

    for n, e, desc in base_pairs:
        expanded.append((n, e, desc))
        if e < 1000000.0:
            if e > 300000.0:
                expanded.append((n, e + zone_num * 1000000.0, f"{desc}+zone{zone_num}M"))
            else:
                expanded.append((n, e + p["y0"], f"{desc}+false_east"))

    best_point: tuple[float, float] | None = None
    min_dist_km = float("inf")
    cos_lat = math.cos(math.radians(exp_lat))

    for n, e, desc in expanded:
        try:
            lat, lon = _single_gk_inverse(n, e, p)
            if 40.0 <= lat <= 75.0 and 19.0 <= lon <= 180.0:
                dlat = (lat - exp_lat) * 111.0
                dlon = (lon - exp_lon) * 111.0 * cos_lat
                dist_km = math.sqrt(dlat * dlat + dlon * dlon)
                if dist_km < min_dist_km:
                    min_dist_km = dist_km
                    best_point = (round(lat, 6), round(lon, 6))
        except Exception:
            pass

    # Если найден кандидат в радиусе до 150 км от ожидаемого центра региона — возвращаем его
    if best_point and min_dist_km <= 150.0:
        return best_point

    # Если геодезический пересчет МСК не подошел, проверяем, являются ли координаты городскими (СК города)
    # В СК города координаты отсчитываются от триангуляционного центра города (обычно от -50 км до +50 км)
    v_max = max(abs(c1), abs(c2))
    v_min = min(abs(c1), abs(c2))
    if 500 < v_max < 120000 and v_min < 120000:
        # Вариант 1 (AutoCAD формат: c1 = Восток/X, c2 = Север/Y)
        lat_cad = exp_lat + c2 / 111320.0
        lon_cad = exp_lon + c1 / (111320.0 * cos_lat)

        # Вариант 2 (Геодезический: c1 = Север/X, c2 = Восток/Y)
        lat_geo = exp_lat + c1 / 111320.0
        lon_geo = exp_lon + c2 / (111320.0 * cos_lat)

        if axis_order == "geodetic":
            return (round(lat_geo, 6), round(lon_geo, 6))
        elif axis_order in ("cad", "auto"):
            return (round(lat_cad, 6), round(lon_cad, 6))
        else:
            return (round(lat_cad, 6), round(lon_cad, 6))

    # Если координаты не удалось надежно привязать — возвращаем ожидаемый центр
    return exp_lat, exp_lon


def detect_msk_by_coordinates(x: float, y: float) -> str | None:
    """Определить вероятную систему координат МСК по числовым значениям offset.

    Поддерживает как полные геодезические координаты (с номером зоны), так и усечённые.

    Args:
        x: Координата X (север) или Y (восток).
        y: Координата Y или X.

    Returns:
        Название ключа из MSK_PRESETS или None, если определить невозможно.
    """
    vals = sorted([abs(x), abs(y)])
    v_small, v_large = vals[0], vals[1]

    # Полные координаты МСК-63 Зона 1 (Самара): X ~ 450 000..550 000, Y ~ 1 450 000..1 650 000
    if 400000 <= v_small <= 600000 and 1400000 <= v_large <= 1700000:
        return "МСК-63 Зона 1 (Самара)"

    # Усечённые координаты МСК-63 Зона 1 (Самара):
    # - без номера зоны: Northing ~ 480k..520k, Easting ~ 550k..650k
    # - без ложного сдвига: Northing ~ 480k..520k, Easting ~ 10k..200k
    if 400000 <= v_large <= 600000 and 10000 <= v_small <= 200000:
        return "МСК-63 Зона 1 (Самара)"
    if 450000 <= v_small <= 540000 and 540000 <= v_large <= 650000:
        return "МСК-63 Зона 1 (Самара)"

    # Самарская область (МСК-63 Зона 2, Тольятти): X ~ 450 000..550 000, Y ~ 2 400 000..2 600 000
    if 400000 <= v_small <= 600000 and 2400000 <= v_large <= 2700000:
        return "МСК-63 Зона 2 (Тольятти)"

    # Московская область (МСК-50 Зона 1): X ~ 350 000..550 000, Y ~ 1 150 000..1 350 000
    if 300000 <= v_small <= 600000 and 1100000 <= v_large <= 1400000:
        return "МСК-50 Зона 1 (МО Запад)"

    # Московская область (МСК-50 Зона 2): X ~ 350 000..550 000, Y ~ 2 150 000..2 350 000
    if 300000 <= v_small <= 600000 and 2100000 <= v_large <= 2400000:
        return "МСК-50 Зона 2 (МО Восток)"

    # Тюменская область (МСК-72 Зона 1): X ~ 350 000..550 000, Y ~ 1 400 000..1 650 000
    if 350000 <= v_small <= 550000 and 1400000 <= v_large <= 1650000:
        return "МСК-72 Зона 1 (Тюмень)"
    # МСК-72 усечённые координаты:
    if 350000 <= v_small <= 550000 and 400000 <= v_large <= 650000:
        return "МСК-72 Зона 1 (Тюмень)"
    if 350000 <= v_large <= 550000 and 10000 <= v_small <= 200000:
        return "МСК-72 Зона 1 (Тюмень)"
    # Тюменская область (МСК-72 Зона 2): Y ~ 2 400 000..2 650 000
    if 350000 <= v_small <= 550000 and 2400000 <= v_large <= 2650000:
        return "МСК-72 Зона 2 (Тобольск / Ишим)"

    # Алтайский край (МСК-22 Зона 2, Барнаул): X ~ 160 000..240 000, Y ~ 2 450 000..2 550 000
    if 160000 <= v_small <= 240000 and 2450000 <= v_large <= 2550000:
        return "МСК-22 Зона 2 (Барнаул)"

    # Москва МСК-77: X, Y в диапазоне 0..50 000
    if v_small < 50000 and v_large < 50000 and (v_small > 500 or v_large > 500):
        return "МСК-77 (Москва)"

    # Свердловская область (МСК-66 Зона 1): X ~ 350 000..600 000, Y ~ 1 400 000..1 650 000
    if 350000 <= v_small <= 600000 and 1400000 <= v_large <= 1650000:
        return "МСК-66 Зона 1 (Свердловская обл.)"

    # Краснодарский край (МСК-23 Зона 1): X ~ 400 000..600 000, Y ~ 1 300 000..1 500 000
    if 400000 <= v_small <= 600000 and 1300000 <= v_large <= 1500000:
        return "МСК-23 Зона 1 (Краснодар)"

    # Республика Татарстан (МСК-16 Зона 1): X ~ 400 000..600 000, Y ~ 1 400 000..1 600 000
    if 400000 <= v_small <= 600000 and 1400000 <= v_large <= 1600000:
        return "МСК-16 Зона 1 (Татарстан)"

    return None
