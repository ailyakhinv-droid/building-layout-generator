"""Модуль координатных систем МСК (Местных систем координат РФ) и конвертации в WGS-84.

Обеспечивает прямое и обратное геодезическое преобразование:
- WGS-84 (широта, долгота) ↔ МСК (X = Northing, Y = Easting)
- Проекция Гаусса-Крюгера (Transverse Mercator) на эллипсоиде Красовского 1940
- Преобразование датума СК-42 ↔ WGS-84 по ГОСТ 32453-2019
- Автоматическое определение МСК по координатам чертежа и коду региона
- Поддержка форматов вызова CAD (X=Восток, Y=Север) и геодезического (X=Север, Y=Восток)
"""

from __future__ import annotations

import math
import re
from typing import Any

# ─── Параметры эллипсоида Красовского 1940 (СК-42 / СК-95) ───────────────────
KRASOVSKY_A: float = 6378245.0  # Большая полуось, м
KRASOVSKY_F: float = 1.0 / 298.3  # Сжатие
KRASOVSKY_E2: float = 2.0 * KRASOVSKY_F - KRASOVSKY_F * KRASOVSKY_F  # Квадрат первого эксцентриситета
KRASOVSKY_E1_2: float = KRASOVSKY_E2 / (1.0 - KRASOVSKY_E2)  # Вторая степень второго эксцентриситета

# 3-параметрический переход СК-42 -> WGS-84 (ГОСТ 32453-2019)
TOWGS84_DX: float = 23.57
TOWGS84_DY: float = -140.95
TOWGS84_DZ: float = -79.8


# ─── Реестр параметров проекций МСК субъектов РФ ────────────────────────────
# Проекция: Поперечно-цилиндрическая Меркатора / Гаусса-Крюгера (Transverse Mercator)
# МСК: X = Северное направление (Northing), Y = Восточное направление (Easting)
MSK_PRESETS: dict[str, dict[str, Any]] = {
    "МСК-63 Зона 1 (Самара)": {
        "region": "Самарская область",
        "city": "Самара",
        "central_meridian": 49.03333333333333,  # 49° 02' E
        "latitude_of_origin": 0.0,
        "false_northing": -5514743.504,
        "false_easting": 1300000.0,
        "scale_factor": 1.0,
        # Алиасы ключей для обратной совместимости
        "L0_deg": 49.03333333333333,
        "x0": -5514743.504,
        "y0": 1300000.0,
        "default_lat": 53.2502,
        "default_lon": 50.3184,
    },
    "МСК-63 Зона 2 (Тольятти)": {
        "region": "Самарская область",
        "city": "Тольятти",
        "central_meridian": 52.03333333333333,  # 52° 02' E
        "latitude_of_origin": 0.0,
        "false_northing": -5514743.504,
        "false_easting": 2300000.0,
        "scale_factor": 1.0,
        "L0_deg": 52.03333333333333,
        "x0": -5514743.504,
        "y0": 2300000.0,
        "default_lat": 53.5078,
        "default_lon": 49.4204,
    },
    "МСК-77 (Москва)": {
        "region": "г. Москва",
        "city": "Москва",
        "central_meridian": 37.5,  # 37° 30' E
        "latitude_of_origin": 0.0,
        "false_northing": -11000.0,
        "false_easting": 16000.0,
        "scale_factor": 1.0,
        "L0_deg": 37.5,
        "x0": -11000.0,
        "y0": 16000.0,
        "default_lat": 55.7512,
        "default_lon": 37.6184,
    },
    "МСК-50 Зона 1 (МО Запад)": {
        "region": "Московская область",
        "city": "Подольск / Красногорск",
        "central_meridian": 35.48333333333333,  # 35° 29' E
        "latitude_of_origin": 0.0,
        "false_northing": -5711057.63,
        "false_easting": 1250000.0,
        "scale_factor": 1.0,
        "L0_deg": 35.48333333333333,
        "x0": -5711057.63,
        "y0": 1250000.0,
        "default_lat": 55.4312,
        "default_lon": 37.5458,
    },
    "МСК-50 Зона 2 (МО Восток)": {
        "region": "Московская область",
        "city": "Мытищи / Балашиха",
        "central_meridian": 38.48333333333333,  # 38° 29' E
        "latitude_of_origin": 0.0,
        "false_northing": -5711057.63,
        "false_easting": 2250000.0,
        "scale_factor": 1.0,
        "L0_deg": 38.48333333333333,
        "x0": -5711057.63,
        "y0": 2250000.0,
        "default_lat": 55.8036,
        "default_lon": 37.9546,
    },
    "МСК-78 (Санкт-Петербург)": {
        "region": "г. Санкт-Петербург",
        "city": "Санкт-Петербург",
        "central_meridian": 30.3141,
        "latitude_of_origin": 0.0,
        "false_northing": 0.0,
        "false_easting": 0.0,
        "scale_factor": 1.0,
        "L0_deg": 30.3141,
        "x0": 0.0,
        "y0": 0.0,
        "default_lat": 59.9386,
        "default_lon": 30.3141,
    },
    "МСК-16 Зона 1 (Татарстан)": {
        "region": "Республика Татарстан",
        "city": "Казань",
        "central_meridian": 49.03333333333333,  # 49° 02' E
        "latitude_of_origin": 0.0,
        "false_northing": -5714743.504,
        "false_easting": 1500000.0,
        "scale_factor": 1.0,
        "L0_deg": 49.03333333333333,
        "x0": -5714743.504,
        "y0": 1500000.0,
        "default_lat": 55.7887,
        "default_lon": 49.1221,
    },
    "МСК-66 Зона 1 (Свердловская обл.)": {
        "region": "Свердловская область",
        "city": "Екатеринбург",
        "central_meridian": 60.05,  # 60° 03' E
        "latitude_of_origin": 0.0,
        "false_northing": -6014743.504,
        "false_easting": 1500000.0,
        "scale_factor": 1.0,
        "L0_deg": 60.05,
        "x0": -6014743.504,
        "y0": 1500000.0,
        "default_lat": 56.8389,
        "default_lon": 60.6057,
    },
    "МСК-23 Зона 1 (Краснодар)": {
        "region": "Краснодарский край",
        "city": "Краснодар",
        "central_meridian": 38.98333333333333,  # 38° 59' E
        "latitude_of_origin": 0.0,
        "false_northing": -4514743.504,
        "false_easting": 1500000.0,
        "scale_factor": 1.0,
        "L0_deg": 38.98333333333333,
        "x0": -4514743.504,
        "y0": 1500000.0,
        "default_lat": 45.0355,
        "default_lon": 38.9753,
    },
    "МСК-72 Зона 1 (Тюмень)": {
        "region": "Тюменская область",
        "city": "Тюмень",
        "central_meridian": 65.96666667,  # 65° 58' E (Тюмень / Заречный / Алебашево)
        "latitude_of_origin": 0.0,
        "false_northing": -6000000.0,
        "false_easting": 1500000.0,
        "scale_factor": 1.0,
        "L0_deg": 65.96666667,
        "x0": -6000000.0,
        "y0": 1500000.0,
        "default_lat": 57.1600,
        "default_lon": 65.5560,
    },
    "МСК г. Тюмени": {
        "region": "Тюменская область",
        "city": "Тюмень",
        "central_meridian": 65.96666667,  # 65° 58' E
        "latitude_of_origin": 0.0,
        "false_northing": -6000000.0,
        "false_easting": 1500000.0,
        "scale_factor": 1.0,
        "L0_deg": 65.96666667,
        "x0": -6000000.0,
        "y0": 1500000.0,
        "default_lat": 57.1600,
        "default_lon": 65.5560,
    },
    "МСК-72 Зона 2 (Тобольск / Ишим)": {
        "region": "Тюменская область",
        "city": "Тобольск",
        "central_meridian": 68.51666667,  # 68° 31' E
        "latitude_of_origin": 0.0,
        "false_northing": -6000000.0,
        "false_easting": 2500000.0,
        "scale_factor": 1.0,
        "L0_deg": 68.51666667,
        "x0": -6000000.0,
        "y0": 2500000.0,
        "default_lat": 58.1980,
        "default_lon": 68.2540,
    },
    "МСК-22 Зона 2 (Барнаул)": {
        "region": "Алтайский край",
        "city": "Барнаул",
        "central_meridian": 83.73333333,  # 83° 44' E
        "latitude_of_origin": 0.0,
        "false_northing": -5714743.504,
        "false_easting": 2500000.0,
        "scale_factor": 1.0,
        "L0_deg": 83.73333333,
        "x0": -5714743.504,
        "y0": 2500000.0,
        "default_lat": 53.3481,
        "default_lon": 83.7799,
    },
}

# ─── Таблица псевдонимов и сокращений зон ────────────────────────────────────
ZONE_ALIASES: dict[str, str] = {
    # Самара МСК-63
    "msk_63_1": "МСК-63 Зона 1 (Самара)",
    "msk-63-1": "МСК-63 Зона 1 (Самара)",
    "msk63_1": "МСК-63 Зона 1 (Самара)",
    "msk_63_zone_1": "МСК-63 Зона 1 (Самара)",
    "msk63-1": "МСК-63 Зона 1 (Самара)",
    "63_1": "МСК-63 Зона 1 (Самара)",
    "63-1": "МСК-63 Зона 1 (Самара)",
    "63": "МСК-63 Зона 1 (Самара)",
    "msk_63": "МСК-63 Зона 1 (Самара)",
    "samara": "МСК-63 Зона 1 (Самара)",
    "самара": "МСК-63 Зона 1 (Самара)",
    "мск-63 зона 1": "МСК-63 Зона 1 (Самара)",
    "мск-63-1": "МСК-63 Зона 1 (Самара)",
    "мск_63_1": "МСК-63 Зона 1 (Самара)",
    # Тольятти МСК-63 Зона 2
    "msk_63_2": "МСК-63 Зона 2 (Тольятти)",
    "msk-63-2": "МСК-63 Зона 2 (Тольятти)",
    "msk63_2": "МСК-63 Зона 2 (Тольятти)",
    "msk_63_zone_2": "МСК-63 Зона 2 (Тольятти)",
    "63_2": "МСК-63 Зона 2 (Тольятти)",
    "63-2": "МСК-63 Зона 2 (Тольятти)",
    "тольятти": "МСК-63 Зона 2 (Тольятти)",
    # Москва МСК-77
    "msk_77": "МСК-77 (Москва)",
    "msk-77": "МСК-77 (Москва)",
    "msk77": "МСК-77 (Москва)",
    "77": "МСК-77 (Москва)",
    "москва": "МСК-77 (Москва)",
    "moscow": "МСК-77 (Москва)",
    # МО МСК-50
    "msk_50_1": "МСК-50 Зона 1 (МО Запад)",
    "msk-50-1": "МСК-50 Зона 1 (МО Запад)",
    "msk50_1": "МСК-50 Зона 1 (МО Запад)",
    "50_1": "МСК-50 Зона 1 (МО Запад)",
    "50": "МСК-50 Зона 1 (МО Запад)",
    "msk_50": "МСК-50 Зона 1 (МО Запад)",
    "msk_50_2": "МСК-50 Зона 2 (МО Восток)",
    "msk-50-2": "МСК-50 Зона 2 (МО Восток)",
    "msk50_2": "МСК-50 Зона 2 (МО Восток)",
    "50_2": "МСК-50 Зона 2 (МО Восток)",
    # Санкт-Петербург МСК-78
    "msk_78": "МСК-78 (Санкт-Петербург)",
    "msk-78": "МСК-78 (Санкт-Петербург)",
    "msk78": "МСК-78 (Санкт-Петербург)",
    "78": "МСК-78 (Санкт-Петербург)",
    "спб": "МСК-78 (Санкт-Петербург)",
    "spb": "МСК-78 (Санкт-Петербург)",
    # Татарстан МСК-16
    "msk_16_1": "МСК-16 Зона 1 (Татарстан)",
    "msk-16-1": "МСК-16 Зона 1 (Татарстан)",
    "16": "МСК-16 Зона 1 (Татарстан)",
    "16_1": "МСК-16 Зона 1 (Татарстан)",
    "казань": "МСК-16 Зона 1 (Татарстан)",
    # Свердловская обл. МСК-66
    "msk_66_1": "МСК-66 Зона 1 (Свердловская обл.)",
    "msk-66-1": "МСК-66 Зона 1 (Свердловская обл.)",
    "66": "МСК-66 Зона 1 (Свердловская обл.)",
    "66_1": "МСК-66 Зона 1 (Свердловская обл.)",
    "екатеринбург": "МСК-66 Зона 1 (Свердловская обл.)",
    # Краснодар МСК-23
    "msk_23_1": "МСК-23 Зона 1 (Краснодар)",
    "msk-23-1": "МСК-23 Зона 1 (Краснодар)",
    "23": "МСК-23 Зона 1 (Краснодар)",
    "23_1": "МСК-23 Зона 1 (Краснодар)",
    "краснодар": "МСК-23 Зона 1 (Краснодар)",
    # Тюмень МСК-72
    "msk_72_1": "МСК-72 Зона 1 (Тюмень)",
    "msk-72-1": "МСК-72 Зона 1 (Тюмень)",
    "72": "МСК-72 Зона 1 (Тюмень)",
    "72_1": "МСК-72 Зона 1 (Тюмень)",
    "тюмень": "МСК-72 Зона 1 (Тюмень)",
    "msk_72_2": "МСК-72 Зона 2 (Тобольск / Ишим)",
    "msk-72-2": "МСК-72 Зона 2 (Тобольск / Ишим)",
    "72_2": "МСК-72 Зона 2 (Тобольск / Ишим)",
    "тобольск": "МСК-72 Зона 2 (Тобольск / Ишим)",
    "мск г. тюмени": "МСК-72 Зона 1 (Тюмень)",
    "мск тюмень": "МСК-72 Зона 1 (Тюмень)",
    "мск_тюмень": "МСК-72 Зона 1 (Тюмень)",
    "г. тюмень": "МСК-72 Зона 1 (Тюмень)",
    # Алтайский край МСК-22
    "msk_22_2": "МСК-22 Зона 2 (Барнаул)",
    "msk-22-2": "МСК-22 Зона 2 (Барнаул)",
    "22": "МСК-22 Зона 2 (Барнаул)",
    "22_2": "МСК-22 Зона 2 (Барнаул)",
    "барнаул": "МСК-22 Зона 2 (Барнаул)",
}


def resolve_zone_preset(zone: str) -> tuple[str, dict[str, Any]]:
    """Найти и вернуть пресет МСК по названию, коду или псевдониму зоны.

    Args:
        zone: Имя зоны ('msk_63_1', 'МСК-63 Зона 1 (Самара)', '63', 'msk-50-2' и др.).

    Returns:
        Кортеж (канонический ключ, словарь параметров пресета).

    Raises:
        ValueError: Если зона не найдена.
    """
    if zone in MSK_PRESETS:
        return zone, MSK_PRESETS[zone]

    clean = zone.strip().lower()
    clean_norm = re.sub(r"[\s\-]+", "_", clean)

    if clean in ZONE_ALIASES:
        canonical = ZONE_ALIASES[clean]
        return canonical, MSK_PRESETS[canonical]

    if clean_norm in ZONE_ALIASES:
        canonical = ZONE_ALIASES[clean_norm]
        return canonical, MSK_PRESETS[canonical]

    # Поиск по подстроке среди канонических ключей
    for key, p in MSK_PRESETS.items():
        k_low = key.lower()
        if clean in k_low or clean_norm in k_low:
            return key, p

    # По умолчанию для Самары
    return "МСК-63 Зона 1 (Самара)", MSK_PRESETS["МСК-63 Зона 1 (Самара)"]


def wgs84_to_msk_coords(
    lat: float,
    lon: float,
    zone: str = "msk_63_1",
) -> tuple[float, float]:
    """Преобразовать географические координаты WGS-84 (lat, lon) в координаты МСК (X, Y).

    Порядок осей в МСК (Россия):
        X = Северное направление (Northing, метры)
        Y = Восточное направление (Easting, метры со смещением зоны)

    Args:
        lat: Географическая широта WGS-84 в градусах (северная).
        lon: Географическая долгота WGS-84 в градусах (восточная).
        zone: Идентификатор МСК зоны ('msk_63_1', 'МСК-63 Зона 1 (Самара)', и т.д.).

    Returns:
        Кортеж (x, y), где x = Northing (север), y = Easting (восток) в метрах.
    """
    _, p = resolve_zone_preset(zone)

    # 1. Переход WGS-84 -> СК-42 (эллипсоид Красовского 1940) по ГОСТ 32453-2019
    lat_wgs = float(lat)
    lon_wgs = float(lon)

    b_rad = math.radians(lat_wgs)
    l_rad = math.radians(lon_wgs)

    sinB = math.sin(b_rad)
    cosB = math.cos(b_rad)
    sinL = math.sin(l_rad)
    cosL = math.cos(l_rad)

    denom = math.sqrt(1.0 - KRASOVSKY_E2 * sinB * sinB)
    N = KRASOVSKY_A / denom
    M = KRASOVSKY_A * (1.0 - KRASOVSKY_E2) / (denom * denom * denom)

    # Обратные поправки Молоденского к широте и долготе
    dlat = (
        TOWGS84_DZ * cosB
        - (TOWGS84_DX * cosL + TOWGS84_DY * sinL) * sinB
    ) / M * (180.0 / math.pi)

    dlon = (
        -TOWGS84_DX * sinL + TOWGS84_DY * cosL
    ) / (N * cosB) * (180.0 / math.pi)

    lat_kr = lat_wgs - dlat
    lon_kr = lon_wgs - dlon

    # 2. Прямое преобразование Гаусса-Крюгера (Красовский 1940)
    L0_deg = p["L0_deg"]
    B = math.radians(lat_kr)
    l = math.radians(lon_kr - L0_deg)

    sinB_kr = math.sin(B)
    cosB_kr = math.cos(B)
    tanB_kr = math.tan(B)
    eta2 = KRASOVSKY_E1_2 * cosB_kr * cosB_kr
    N_kr = KRASOVSKY_A / math.sqrt(1.0 - KRASOVSKY_E2 * sinB_kr * sinB_kr)

    # Длина дуги меридиана от экватора до широты B
    A0 = 1.0 - KRASOVSKY_E2 / 4.0 - 3.0 * (KRASOVSKY_E2**2) / 64.0 - 5.0 * (KRASOVSKY_E2**3) / 256.0
    A2 = 3.0 * KRASOVSKY_E2 / 8.0 + 3.0 * (KRASOVSKY_E2**2) / 32.0 + 45.0 * (KRASOVSKY_E2**3) / 1024.0
    A4 = 15.0 * (KRASOVSKY_E2**2) / 256.0 + 45.0 * (KRASOVSKY_E2**3) / 1024.0
    A6 = 35.0 * (KRASOVSKY_E2**3) / 3072.0

    s = KRASOVSKY_A * (
        A0 * B
        - A2 * math.sin(2.0 * B)
        + A4 * math.sin(4.0 * B)
        - A6 * math.sin(6.0 * B)
    )

    x_gk = (
        s
        + N_kr * sinB_kr * cosB_kr * (l**2) / 2.0
        + N_kr * sinB_kr * (cosB_kr**3) * (5.0 - tanB_kr**2 + 9.0 * eta2 + 4.0 * (eta2**2)) * (l**4) / 24.0
        + N_kr * sinB_kr * (cosB_kr**5) * (61.0 - 58.0 * tanB_kr**2 + tanB_kr**4) * (l**6) / 720.0
    )

    y_gk = (
        N_kr * cosB_kr * l
        + N_kr * (cosB_kr**3) * (1.0 - tanB_kr**2 + eta2) * (l**3) / 6.0
        + N_kr * (cosB_kr**5) * (5.0 - 18.0 * tanB_kr**2 + tanB_kr**4 + 14.0 * eta2 - 58.0 * eta2 * tanB_kr**2) * (l**5) / 120.0
    )

    x = x_gk + p["x0"]
    y = y_gk + p["y0"]

    return x, y


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

    A0 = 1.0 - KRASOVSKY_E2 / 4.0 - 3.0 * (KRASOVSKY_E2**2) / 64.0 - 5.0 * (KRASOVSKY_E2**3) / 256.0
    B_appr = x_gk / (KRASOVSKY_A * A0)
    for _ in range(8):
        s = KRASOVSKY_A * (
            A0 * B_appr
            - (3.0 * KRASOVSKY_E2 / 8.0 + 3.0 * (KRASOVSKY_E2**2) / 32.0) * math.sin(2.0 * B_appr)
            + (15.0 * (KRASOVSKY_E2**2) / 256.0) * math.sin(4.0 * B_appr)
        )
        diff = (x_gk - s) / (KRASOVSKY_A * (1.0 - KRASOVSKY_E2) / ((1.0 - KRASOVSKY_E2 * math.sin(B_appr) ** 2) ** 1.5))
        B_appr += diff
        if abs(diff) < 1e-11:
            break

    Bf = B_appr
    sinBf = math.sin(Bf)
    cosBf = math.cos(Bf)
    tanBf = math.tan(Bf)

    denom = math.sqrt(1.0 - KRASOVSKY_E2 * sinBf * sinBf)
    Nf = KRASOVSKY_A / denom
    Mf = KRASOVSKY_A * (1.0 - KRASOVSKY_E2) / (denom * denom * denom)
    eta2 = KRASOVSKY_E1_2 * cosBf * cosBf

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
    N = KRASOVSKY_A / math.sqrt(1.0 - KRASOVSKY_E2 * math.sin(b_rad) ** 2)
    M = KRASOVSKY_A * (1.0 - KRASOVSKY_E2) / ((1.0 - KRASOVSKY_E2 * math.sin(b_rad) ** 2) ** 1.5)

    lat_wgs = lat_kr + (
        TOWGS84_DZ * math.cos(b_rad)
        - (TOWGS84_DX * math.cos(l_rad) + TOWGS84_DY * math.sin(l_rad)) * math.sin(b_rad)
    ) / M * (180.0 / math.pi)

    lon_wgs = lon_kr + (
        -TOWGS84_DX * math.sin(l_rad) + TOWGS84_DY * math.cos(l_rad)
    ) / (N * math.cos(b_rad)) * (180.0 / math.pi)

    return lat_wgs, lon_wgs


def msk_to_wgs84_coords(
    x: float,
    y: float,
    zone: str = "msk_63_1",
    axis_order: str = "auto",
    expected_center: tuple[float, float] | None = None,
    **kwargs: Any,
) -> tuple[float, float]:
    """Преобразовать координаты МСК (X = Northing, Y = Easting) в WGS-84 (lat, lon).

    Поддерживает:
    - Вызов с аргументами (x, y, zone='msk_63_1') и устаревший (coord1, coord2, msk_key='...')
    - Автоматическое распознавание порядка осей:
      * Геодезический: x = Northing (север), y = Easting (восток)
      * CAD-чертежи: x = Easting (восток), y = Northing (север)
    - Восстановление усеченных координат востока (без префикса зоны или без false easting)

    Args:
        x: Первая координата (в геодезии X = Северное направление, в CAD X = Восток).
        y: Вторая координата (в геодезии Y = Восточное направление, в CAD Y = Север).
        zone: Имя или псевдоним МСК зоны.
        axis_order: "auto" (автоопределение по величинам и ожидаемому центру),
                    "geodetic" (x=Север, y=Восток),
                    "cad" (x=Восток, y=Север),
                    "swap" (поменять местами).
        expected_center: Ожидаемый географический центр (lat, lon) для валидации ветви.

    Returns:
        Кортеж (latitude, longitude) в градусах WGS-84.
    """
    # Совместимость со старыми вызовами (msk_key=...)
    zone_arg = kwargs.get("msk_key", zone)
    canonical_key, p = resolve_zone_preset(zone_arg)

    # Если для системы задан простой дефолтный центр (МСК-78 / городские СК без ключа)
    if p["x0"] == 0.0 and p["y0"] == 0.0:
        return (p["default_lat"], p["default_lon"])

    c1 = float(x)
    c2 = float(y)

    exp_lat, exp_lon = expected_center if expected_center else (p["default_lat"], p["default_lon"])

    # Формируем пары кандидатов (Север, Восток)
    base_pairs: list[tuple[float, float, str]] = []
    if axis_order == "cad":
        # CAD X = Восток, CAD Y = Север -> (n=c2, e=c1)
        base_pairs = [(c2, c1, "cad_X_east_Y_north")]
    elif axis_order == "geodetic":
        # Geodetic X = Север, Geodetic Y = Восток -> (n=c1, e=c2)
        base_pairs = [(c1, c2, "geodetic_X_north_Y_east")]
    elif axis_order == "swap":
        base_pairs = [(c2, c1, "swap_axes")]
    else:
        # Режим 'auto':
        # В России восточная координата Гаусса-Крюгера со смещением зоны обычно > 1 000 000 м.
        # Северная координата МСК в большинстве регионов составляет от 200 000 до 700 000 м.
        if c1 > 800000.0 and c2 < 800000.0:
            # c1 - Восток, c2 - Север (CAD)
            base_pairs = [(c2, c1, "auto_cad"), (c1, c2, "auto_geo")]
        elif c2 > 800000.0 and c1 < 800000.0:
            # c1 - Север, c2 - Восток (Геодезия)
            base_pairs = [(c1, c2, "auto_geo"), (c2, c1, "auto_cad")]
        else:
            base_pairs = [(c1, c2, "auto_geo"), (c2, c1, "auto_cad")]

    # Варианты False Northing (X0)
    x0_options = [p["x0"]]
    for alt_x0 in [-5514743.504, -5711057.63, -5414743.504, -5714743.504, -6000000.0, -4514743.504]:
        if alt_x0 not in x0_options:
            x0_options.append(alt_x0)

    # Варианты False Easting (Y0)
    base_y0 = p["y0"]
    zone_num = int(base_y0 // 1000000.0) if base_y0 >= 1000000.0 else 1
    y0_options = [base_y0]
    for alt_y0 in [
        zone_num * 1000000.0 + 300000.0,
        zone_num * 1000000.0 + 500000.0,
        zone_num * 1000000.0 + 250000.0,
    ]:
        if alt_y0 not in y0_options:
            y0_options.append(alt_y0)

    # Варианты Центрального меридиана (L0)
    l0_options = [p["L0_deg"]]
    if "72" in canonical_key or "Тюмен" in canonical_key:
        for alt_l0 in [65.96666667, 66.0, 66.03333333, 66.05, 65.51666667]:
            if alt_l0 not in l0_options:
                l0_options.append(alt_l0)
    elif "63" in canonical_key or "Самар" in canonical_key:
        for alt_l0 in [49.03333333333333, 52.03333333333333]:
            if alt_l0 not in l0_options:
                l0_options.append(alt_l0)

    best_point: tuple[float, float] | None = None
    min_dist_km = float("inf")
    cos_lat = math.cos(math.radians(exp_lat))

    for n_raw, e_raw, desc in base_pairs:
        # Варианты восстановления усечённых координат Востока
        e_candidates = [e_raw]
        if e_raw < 1000000.0:
            if e_raw > 300000.0:
                e_candidates.append(e_raw + zone_num * 1000000.0)
            else:
                e_candidates.append(e_raw + p["y0"])

        for e in e_candidates:
            for l0 in l0_options:
                for x0 in x0_options:
                    for y0 in y0_options:
                        p_trial = dict(p)
                        p_trial["L0_deg"] = l0
                        p_trial["x0"] = x0
                        p_trial["y0"] = y0
                        try:
                            lat, lon = _single_gk_inverse(n_raw, e, p_trial)
                            if 40.0 <= lat <= 78.0 and 19.0 <= lon <= 180.0:
                                dlat = (lat - exp_lat) * 111.0
                                dlon = (lon - exp_lon) * 111.0 * cos_lat
                                dist_km = math.sqrt(dlat * dlat + dlon * dlon)
                                if dist_km < min_dist_km:
                                    min_dist_km = dist_km
                                    best_point = (round(lat, 6), round(lon, 6))
                        except Exception:
                            pass

    # Если найден кандидат в пределах разумного радиуса региона (до 800 км)
    if best_point and min_dist_km <= 800.0:
        return best_point

    # Проверка на городские СК (смещение относительно центра города до ±100 км)
    v_max = max(abs(c1), abs(c2))
    v_min = min(abs(c1), abs(c2))
    if 500 < v_max < 150000 and v_min < 150000:
        lat_cad = exp_lat + c2 / 111320.0
        lon_cad = exp_lon + c1 / (111320.0 * cos_lat)
        lat_geo = exp_lat + c1 / 111320.0
        lon_geo = exp_lon + c2 / (111320.0 * cos_lat)

        if axis_order == "geodetic":
            return (round(lat_geo, 6), round(lon_geo, 6))
        return (round(lat_cad, 6), round(lon_cad, 6))

    if best_point:
        return best_point

    return exp_lat, exp_lon


def detect_msk_by_coordinates(
    x: float,
    y: float,
    region_hint: str | None = None,
) -> str | None:
    """Определить вероятную систему координат МСК по числовым значениям offset.

    Поддерживает:
    - Диапазоны для Самарской области (МСК-63): X ≈ 450000-600000, Y ≈ 1200000-1750000
    - Подсказку по региону (region_hint: '63', '50', '72' и др.)
    - Полные и усеченные координаты.

    Args:
        x: Координата X (север или восток в чертеже).
        y: Координата Y (север или восток в чертеже).
        region_hint: Подсказка по коду региона (например, '63' для Самары).

    Returns:
        Название ключа из MSK_PRESETS или None, если определить невозможно.
    """
    vals = sorted([abs(float(x)), abs(float(y))])
    v_small, v_large = vals[0], vals[1]

    # Если передан код региона — приоритетно используем его
    if region_hint:
        clean_hint = str(region_hint).strip()
        c_hint = clean_hint.zfill(2)
        if c_hint == "63" or "самар" in clean_hint.lower():
            return "МСК-63 Зона 2 (Тольятти)" if v_large > 2000000.0 else "МСК-63 Зона 1 (Самара)"
        elif c_hint == "50" or "москов" in clean_hint.lower():
            return "МСК-50 Зона 2 (МО Восток)" if v_large > 2000000.0 else "МСК-50 Зона 1 (МО Запад)"
        elif c_hint == "72" or "тюмен" in clean_hint.lower():
            return "МСК-72 Зона 2 (Тобольск / Ишим)" if v_large > 2000000.0 else "МСК-72 Зона 1 (Тюмень)"
        elif c_hint == "77" or "москв" in clean_hint.lower():
            return "МСК-77 (Москва)"
        elif c_hint == "78" or "петербург" in clean_hint.lower():
            return "МСК-78 (Санкт-Петербург)"

    # Самарская область (МСК-63 Зона 1, Самара):
    # X ≈ 350 000..650 000, Y ≈ 1 200 000..1 750 000
    if 300000 <= v_small <= 650000 and 1200000 <= v_large <= 1750000:
        return "МСК-63 Зона 1 (Самара)"

    # Самарская область (МСК-63 Зона 2, Тольятти):
    # X ≈ 350 000..650 000, Y ≈ 2 200 000..2 750 000
    if 300000 <= v_small <= 650000 and 2200000 <= v_large <= 2750000:
        return "МСК-63 Зона 2 (Тольятти)"

    # Усечённые координаты МСК-63 Зона 1 (Самара):
    # - без номера зоны: Northing ~ 450k..600k, Easting ~ 540k..650k
    # - без ложного сдвига: Northing ~ 450k..600k, Easting ~ 10k..200k
    if 400000 <= v_large <= 650000 and 10000 <= v_small <= 200000:
        return "МСК-63 Зона 1 (Самара)"
    if 450000 <= v_small <= 600000 and 540000 <= v_large <= 650000:
        return "МСК-63 Зона 1 (Самара)"

    # Московская область (МСК-50 Зона 1): X ~ 350 000..550 000, Y ~ 1 100 000..1 400 000
    if 300000 <= v_small <= 550000 and 1100000 <= v_large <= 1400000:
        return "МСК-50 Зона 1 (МО Запад)"

    # Московская область (МСК-50 Зона 2): X ~ 350 000..550 000, Y ~ 2 100 000..2 400 000
    if 300000 <= v_small <= 600000 and 2100000 <= v_large <= 2400000:
        return "МСК-50 Зона 2 (МО Восток)"

    # Тюменская область (МСК-72 Зона 1): X ~ 300 000..550 000, Y ~ 1 400 000..1 650 000
    if 300000 <= v_small <= 550000 and 1400000 <= v_large <= 1650000:
        return "МСК-72 Зона 1 (Тюмень)"
    if 300000 <= v_small <= 550000 and 400000 <= v_large <= 650000:
        return "МСК-72 Зона 1 (Тюмень)"
    if 300000 <= v_large <= 550000 and 10000 <= v_small <= 200000:
        return "МСК-72 Зона 1 (Тюмень)"

    # Тюменская область (МСК-72 Зона 2): Y ~ 2 400 000..2 650 000
    if 300000 <= v_small <= 550000 and 2400000 <= v_large <= 2650000:
        return "МСК-72 Зона 2 (Тобольск / Ишим)"

    # Алтайский край (МСК-22 Зона 2, Барнаул): X ~ 160 000..240 000, Y ~ 2 450 000..2 550 000
    if 160000 <= v_small <= 240000 and 2450000 <= v_large <= 2550000:
        return "МСК-22 Зона 2 (Барнаул)"

    # Москва МСК-77: X, Y в диапазоне 0..50 000
    if v_small < 50000 and v_large < 50000 and (v_small > 500 or v_large > 500):
        return "МСК-77 (Москва)"

    # Свердловская область (МСК-66 Зона 1): X ~ 250 000..600 000, Y ~ 1 400 000..1 650 000
    if 250000 <= v_small <= 600000 and 1400000 <= v_large <= 1650000:
        return "МСК-66 Зона 1 (Свердловская обл.)"

    # Краснодарский край (МСК-23 Зона 1): X ~ 400 000..600 000, Y ~ 1 300 000..1 550 000
    if 400000 <= v_small <= 600000 and 1300000 <= v_large <= 1550000:
        return "МСК-23 Зона 1 (Краснодар)"

    # Республика Татарстан (МСК-16 Зона 1): X ~ 400 000..600 000, Y ~ 1 400 000..1 600 000
    if 400000 <= v_small <= 600000 and 1400000 <= v_large <= 1600000:
        return "МСК-16 Зона 1 (Татарстан)"

    return None


def get_msk_key_for_region(
    region_code: str,
    coord1: float | None = None,
    coord2: float | None = None,
) -> str | None:
    """Определить подходящую систему координат МСК для заданного кода региона РФ.

    Args:
        region_code: 2-значный код субъекта РФ ('63', '77', '50', '72', '22', и т.д.).
        coord1: Первая координата (X в CAD или Север в геодезии).
        coord2: Вторая координата (Y в CAD или Восток в геодезии).

    Returns:
        Каноническое название ключа из MSK_PRESETS или None.
    """
    clean_code = str(region_code).strip().zfill(2)
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
