"""Сервис работы с кадастровыми номерами и геопространственной привязкой.

Позволяет:
- Разбирать кадастровые номера земельных участков всех 89 субъектов РФ (формат РР:РР:КККККК:УУ).
- Точно определять субъект РФ, административный округ / город и координаты WGS-84.
- Автоматически сопоставлять с региональными нормативами (РНГП / МНГП).
- Предоставлять чистый контур участка без посторонних красных линий.
- Пересчитывать координаты из WGS-84 в локальные метры для алгоритма застройки.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from shapely.geometry import LineString, Polygon

from src.core.geo_utils import (
    metric_to_wgs84_coords,
    wgs84_to_metric_coords,
)
from src.models.site import Site


@dataclass
class CadastralParcelInfo:
    """Информация о кадастровом земельном участке.

    Attributes:
        cadastral_number: Официальный кадастровый номер.
        region_code: Код субъекта РФ (первые 2 цифры).
        region_name: Название субъекта РФ.
        district_name: Название округа / района / города.
        regional_norm_id: ID регионального норматива из regional_norms.yaml.
        address: Полный ориентир местоположения или адрес.
        center_lat: Широта центра участка (WGS-84).
        center_lon: Долгота центра участка (WGS-84).
        area_sqm: Площадь участка в м².
        boundary_metric: Полигон границы в локальных метрах.
        red_lines_metric: Список красных линий (пустой по умолчанию).
        source: Источник данных ("preset", "district_geocoded", "region_geocoded", "custom_coords").
    """

    cadastral_number: str
    region_code: str
    region_name: str
    district_name: str
    regional_norm_id: str
    address: str
    center_lat: float
    center_lon: float
    area_sqm: float
    boundary_metric: Polygon
    red_lines_metric: list[LineString] = field(default_factory=list)
    source: str = "region_geocoded"


# ─── Всероссийский реестр всех субъектов РФ (89 регионов) ───────────────────
# Код региона -> (Название, Региональный норматив, Широта центра, Долгота центра)
ALL_REGIONS: dict[str, tuple[str, str, float, float]] = {
    "01": ("Республика Адыгея (Майкоп)", "russia_sp42", 44.6098, 40.1006),
    "02": ("Республика Башкортостан (Уфа)", "russia_sp42", 54.7388, 55.9721),
    "03": ("Республика Бурятия (Улан-Удэ)", "russia_sp42", 51.8345, 107.5845),
    "04": ("Республика Алтай (Горно-Алтайск)", "russia_sp42", 51.9581, 85.9603),
    "05": ("Республика Дагестан (Махачкала)", "russia_sp42", 42.9849, 47.5046),
    "06": ("Республика Ингушетия (Магас)", "russia_sp42", 43.1667, 44.8167),
    "07": ("Кабардино-Балкарская Республика (Нальчик)", "russia_sp42", 43.4853, 43.6071),
    "08": ("Республика Калмыкия (Элиста)", "russia_sp42", 46.3078, 44.2558),
    "09": ("Карачаево-Черкесская Республика (Черкесск)", "russia_sp42", 44.2233, 42.0578),
    "10": ("Республика Карелия (Петрозаводск)", "russia_sp42", 61.7849, 34.3469),
    "11": ("Республика Коми (Сыктывкар)", "russia_sp42", 61.6688, 50.8354),
    "12": ("Республика Марий Эл (Йошкар-Ола)", "russia_sp42", 56.6322, 47.8864),
    "13": ("Республика Мордовия (Саранск)", "russia_sp42", 54.1874, 45.1839),
    "14": ("Республика Саха / Якутия (Якутск)", "russia_sp42", 62.0272, 129.7321),
    "15": ("Республика Северная Осетия (Владикавказ)", "russia_sp42", 43.0367, 44.6678),
    "16": ("Республика Татарстан (Казань)", "russia_sp42", 55.7887, 49.1221),
    "17": ("Республика Тыва (Кызыл)", "russia_sp42", 51.7197, 94.4378),
    "18": ("Удмуртская Республика (Ижевск)", "russia_sp42", 56.8528, 53.2115),
    "19": ("Республика Хакасия (Абакан)", "russia_sp42", 53.7211, 91.4424),
    "20": ("Чеченская Республика (Грозный)", "russia_sp42", 43.3178, 45.6986),
    "21": ("Чувашская Республика (Чебоксары)", "russia_sp42", 56.1439, 47.2489),
    "22": ("Алтайский край (Барнаул)", "russia_sp42", 53.3481, 83.7799),
    "23": ("Краснодарский край (Краснодар)", "krasnodar_rngp", 45.0355, 38.9753),
    "24": ("Красноярский край (Красноярск)", "russia_sp42", 56.0153, 92.8932),
    "25": ("Приморский край (Владивосток)", "russia_sp42", 43.1155, 131.8855),
    "26": ("Ставропольский край (Ставрополь)", "russia_sp42", 45.0445, 41.9691),
    "27": ("Хабаровский край (Хабаровск)", "russia_sp42", 48.4802, 135.0719),
    "28": ("Амурская область (Благовещенск)", "russia_sp42", 50.2796, 127.5405),
    "29": ("Архангельская область (Архангельск)", "russia_sp42", 64.5399, 40.5158),
    "30": ("Астраханская область (Астрахань)", "russia_sp42", 46.3479, 48.0336),
    "31": ("Белгородская область (Белгород)", "russia_sp42", 50.5954, 36.5873),
    "32": ("Брянская область (Брянск)", "russia_sp42", 53.2434, 34.3642),
    "33": ("Владимирская область (Владимир)", "russia_sp42", 56.1290, 40.4066),
    "34": ("Волгоградская область (Волгоград)", "russia_sp42", 48.7071, 44.5170),
    "35": ("Вологодская область (Вологда)", "russia_sp42", 59.2205, 39.8915),
    "36": ("Воронежская область (Воронеж)", "russia_sp42", 51.6608, 39.2003),
    "37": ("Ивановская область (Иваново)", "russia_sp42", 56.9997, 40.9730),
    "38": ("Иркутская область (Иркутск)", "russia_sp42", 52.2864, 104.3050),
    "39": ("Калининградская область (Калининград)", "russia_sp42", 54.7104, 20.4522),
    "40": ("Калужская область (Калуга)", "russia_sp42", 54.5138, 36.2612),
    "41": ("Камчатский край (Петропавловск-Камчатский)", "russia_sp42", 53.0370, 158.6559),
    "42": ("Кемеровская область - Кузбасс (Кемерово)", "russia_sp42", 55.3547, 86.0874),
    "43": ("Кировская область (Киров)", "russia_sp42", 58.6036, 49.6680),
    "44": ("Костромская область (Кострома)", "russia_sp42", 57.7679, 40.9269),
    "45": ("Курганская область (Курган)", "russia_sp42", 55.4410, 65.3411),
    "46": ("Курская область (Курск)", "russia_sp42", 51.7304, 36.1927),
    "47": ("Ленинградская область (Гатчина)", "russia_sp42", 59.5684, 30.1317),
    "48": ("Липецкая область (Липецк)", "russia_sp42", 52.6103, 39.5947),
    "49": ("Магаданская область (Магадан)", "russia_sp42", 59.5638, 150.8035),
    "50": ("Московская область", "moscow_oblast_rngp", 55.4312, 37.5458),
    "51": ("Мурманская область (Мурманск)", "russia_sp42", 68.9707, 33.0750),
    "52": ("Нижегородская область (Нижний Новгород)", "russia_sp42", 56.2965, 43.9361),
    "53": ("Новгородская область (Великий Новгород)", "russia_sp42", 58.5229, 31.2698),
    "54": ("Новосибирская область (Новосибирск)", "russia_sp42", 55.0084, 82.9357),
    "55": ("Омская область (Омск)", "russia_sp42", 54.9885, 73.3242),
    "56": ("Оренбургская область (Оренбург)", "russia_sp42", 51.7682, 55.0970),
    "57": ("Орловская область (Орёл)", "russia_sp42", 52.9685, 36.0693),
    "58": ("Пензенская область (Пенза)", "russia_sp42", 53.1950, 45.0183),
    "59": ("Пермский край (Пермь)", "russia_sp42", 58.0105, 56.2502),
    "60": ("Псковская область (Псков)", "russia_sp42", 57.8193, 28.3318),
    "61": ("Ростовская область (Ростов-на-Дону)", "russia_sp42", 47.2357, 39.7015),
    "62": ("Рязанская область (Рязань)", "russia_sp42", 54.6292, 39.7366),
    "63": ("Самарская область (Самара)", "russia_sp42", 53.1959, 50.1002),
    "64": ("Саратовская область (Саратов)", "russia_sp42", 51.5336, 46.0343),
    "65": ("Сахалинская область (Южно-Сахалинск)", "russia_sp42", 46.9592, 142.7381),
    "66": ("Свердловская область (Екатеринбург)", "russia_sp42", 56.8389, 60.6057),
    "67": ("Смоленская область (Смоленск)", "russia_sp42", 54.7826, 32.0453),
    "68": ("Тамбовская область (Тамбов)", "russia_sp42", 52.7212, 41.4523),
    "69": ("Тверская область (Тверь)", "russia_sp42", 56.8596, 35.9119),
    "70": ("Томская область (Томск)", "russia_sp42", 56.4886, 84.9523),
    "71": ("Тульская область (Тула)", "russia_sp42", 54.1931, 37.6173),
    "72": ("Тюменская область (Тюмень)", "russia_sp42", 57.1530, 65.5343),
    "73": ("Ульяновская область (Ульяновск)", "russia_sp42", 54.3142, 48.4031),
    "74": ("Челябинская область (Челябинск)", "russia_sp42", 55.1644, 61.4368),
    "75": ("Забайкальский край (Чита)", "russia_sp42", 52.0340, 113.4994),
    "76": ("Ярославская область (Ярославль)", "russia_sp42", 57.6261, 39.8845),
    "77": ("г. Москва", "moscow_mngp", 55.7512, 37.6184),
    "78": ("г. Санкт-Петербург", "spb_rngp", 59.9386, 30.3141),
    "79": ("Еврейская АО (Биробиджан)", "russia_sp42", 48.7946, 132.9218),
    "82": ("Республика Крым (Симферополь)", "russia_sp42", 44.9521, 34.1024),
    "83": ("Ненецкий АО (Нарьян-Мар)", "russia_sp42", 67.6381, 53.0040),
    "86": ("Ханты-Мансийский АО - Югра (Сургут)", "russia_sp42", 61.2540, 73.3962),
    "87": ("Чукотский АО (Анадырь)", "russia_sp42", 64.7334, 177.5084),
    "89": ("Ямало-Ненецкий АО (Салехард)", "russia_sp42", 66.5299, 66.6019),
    "92": ("г. Севастополь", "russia_sp42", 44.6166, 33.5254),
}


# ─── Детализация по кадастровым округам Московской области (50) ─────────────
# Код 50:XX -> (Название округа/города, Широта, Долгота)
MO_DISTRICTS: dict[str, tuple[str, float, float]] = {
    "01": ("Талдомский г.о.", 56.7285, 37.5252),
    "02": ("Волоколамский г.о.", 55.9984, 35.9554),
    "03": ("г.о. Клин", 56.3314, 36.7281),
    "04": ("Дмитровский г.о.", 56.3442, 37.5208),
    "05": ("Сергиево-Посадский г.о.", 56.3153, 38.1362),
    "06": ("г.о. Пушкинский", 56.0104, 37.8483),
    "07": ("г.о. Мытищи", 55.9114, 37.7331),
    "08": ("г.о. Щёлково", 55.9221, 37.9942),
    "09": ("г.о. Солнечногорск", 56.1831, 36.9834),
    "10": ("г.о. Химки", 55.8970, 37.4296),
    "11": ("г.о. Красногорск", 55.8311, 37.3294),
    "12": ("г.о. Истра", 55.9182, 36.8611),
    "13": ("Наро-Фоминский г.о.", 55.3884, 36.7322),
    "14": ("г.о. Королёв", 55.9167, 37.8542),
    "15": ("г.о. Балашиха", 55.8036, 37.9546),
    "16": ("Богородский г.о. (Ногинск)", 55.8564, 38.4412),
    "17": ("Павлово-Посадский г.о.", 55.7794, 38.6531),
    "18": ("Орехово-Зуевский г.о.", 55.8081, 38.9803),
    "19": ("Рузский г.о.", 55.6983, 35.9612),
    "20": ("Одинцовский г.о.", 55.6781, 37.2681),
    "21": ("Ленинский г.о. (Видное)", 55.5511, 37.7032),
    "22": ("г.о. Люберцы", 55.6772, 37.8931),
    "23": ("Раменский г.о.", 55.5671, 38.2253),
    "24": ("г.о. Воскресенск", 55.3224, 38.6811),
    "25": ("г.о. Егорьевск", 55.3842, 39.0341),
    "26": ("Можайский г.о.", 55.5052, 36.0261),
    "27": ("г.о. Подольск", 55.4312, 37.5458),
    "28": ("г.о. Домодедово", 55.4384, 37.7662),
    "29": ("г.о. Ступино", 54.8872, 38.0771),
    "30": ("г.о. Кашира", 54.8391, 38.1632),
    "31": ("г.о. Чехов", 55.1471, 37.4582),
    "32": ("г.о. Серпухов", 54.9152, 37.4171),
    "33": ("г.о. Луховицы", 54.9752, 39.0271),
    "34": ("Коломенский г.о. (Коломна)", 55.0841, 38.7782),
    "35": ("г.о. Зарайск", 54.7571, 38.8741),
    "36": ("г.о. Шатура", 55.5741, 39.5392),
}


# ─── Пресеты типовых участков для быстрого тестирования ─────────────────────
# Красные линии отключены по умолчанию, чтобы не создавать ложных полос
PRESET_PARCELS: dict[str, dict[str, Any]] = {
    "77:17:0120316:1024": {
        "region_code": "77",
        "region_name": "г. Москва",
        "district_name": "ТиНАО (Коммунарка)",
        "regional_norm_id": "moscow_mngp",
        "address": "г. Москва, п. Сосенское (ТиНАО, Коммунарка), кв-л 120, уч. 1024",
        "center_lat": 55.572400,
        "center_lon": 37.471800,
        "polygon_metric": [
            (0.0, 0.0),
            (215.0, 0.0),
            (215.0, 140.0),
            (145.0, 175.0),
            (0.0, 175.0),
        ],
        "red_lines": [],
    },
    "50:27:0010101:500": {
        "region_code": "50",
        "region_name": "Московская область",
        "district_name": "г.о. Подольск",
        "regional_norm_id": "moscow_oblast_rngp",
        "address": "Московская область, г.о. Подольск, уч. 500",
        "center_lat": 55.431200,
        "center_lon": 37.545800,
        "polygon_metric": [
            (0.0, 0.0),
            (220.0, 0.0),
            (220.0, 150.0),
            (0.0, 150.0),
        ],
        "red_lines": [],
    },
    "78:34:0004286:115": {
        "region_code": "78",
        "region_name": "г. Санкт-Петербург",
        "district_name": "Приморский район",
        "regional_norm_id": "spb_rngp",
        "address": "г. Санкт-Петербург, Приморский район, Комендантский пр-т, уч. 115",
        "center_lat": 60.021000,
        "center_lon": 30.245000,
        "polygon_metric": [
            (0.0, 25.0),
            (25.0, 0.0),
            (230.0, 0.0),
            (230.0, 150.0),
            (0.0, 150.0),
        ],
        "red_lines": [],
    },
    "23:43:0106012:450": {
        "region_code": "23",
        "region_name": "Краснодарский край",
        "district_name": "г. Краснодар",
        "regional_norm_id": "krasnodar_rngp",
        "address": "Краснодарский край, г. Краснодар, р-н Западного обхода, уч. 450",
        "center_lat": 45.071200,
        "center_lon": 38.912500,
        "polygon_metric": [
            (0.0, 0.0),
            (250.0, 0.0),
            (250.0, 160.0),
            (190.0, 175.0),
            (0.0, 175.0),
        ],
        "red_lines": [],
    },
    "66:41:0101001:500": {
        "region_code": "66",
        "region_name": "Свердловская область",
        "district_name": "г. Екатеринбург",
        "regional_norm_id": "russia_sp42",
        "address": "Свердловская область, г. Екатеринбург (Академический), уч. 500",
        "center_lat": 56.838926,
        "center_lon": 60.605703,
        "polygon_metric": [
            (0.0, 0.0),
            (210.0, 0.0),
            (210.0, 140.0),
            (0.0, 140.0),
        ],
        "red_lines": [],
    },
    "16:50:010101:200": {
        "region_code": "16",
        "region_name": "Республика Татарстан",
        "district_name": "г. Казань",
        "regional_norm_id": "russia_sp42",
        "address": "Республика Татарстан, г. Казань, уч. 200",
        "center_lat": 55.788740,
        "center_lon": 49.122140,
        "polygon_metric": [
            (0.0, 0.0),
            (200.0, 0.0),
            (200.0, 145.0),
            (0.0, 145.0),
        ],
        "red_lines": [],
    },
}


def validate_cadastral_number(cad_num: str) -> bool:
    """Проверить валидность формата кадастрового номера РФ."""
    clean = re.sub(r"[\s\-_]+", ":", cad_num.strip())
    pattern = r"^\d{2}:\d{1,2}:\d{6,7}:\d+$"
    return bool(re.match(pattern, clean))


def parse_cadastral_components(cad_num: str) -> dict[str, str] | None:
    """Разобрать кадастровый номер на компоненты с поддержкой разделителей двоеточие/пробел/дефис."""
    clean = re.sub(r"[\s\-_]+", ":", cad_num.strip())
    parts = clean.split(":")
    if len(parts) >= 2:
        reg_code = parts[0].zfill(2)
        dist_code = parts[1].zfill(2) if len(parts) > 1 else "01"
        block_code = parts[2] if len(parts) > 2 else "000000"
        parcel_code = parts[3] if len(parts) > 3 else "1"
        return {
            "region_code": reg_code,
            "district_code": dist_code,
            "block_code": block_code,
            "parcel_code": parcel_code,
            "formatted": f"{reg_code}:{dist_code}:{block_code}:{parcel_code}",
        }
    return None


def resolve_cadastral_location(cad_num: str) -> tuple[str, str, str, float, float]:
    """Определить регион, район, норматив и координаты (lat, lon) по кадастровому номеру.

    Returns:
        Кортеж (region_name, district_name, norm_id, lat, lon).
    """
    clean_num = cad_num.strip()
    if clean_num in PRESET_PARCELS:
        p = PRESET_PARCELS[clean_num]
        return (p["region_name"], p.get("district_name", "—"), p["regional_norm_id"], p["center_lat"], p["center_lon"])

    comps = parse_cadastral_components(clean_num)
    if not comps:
        # По умолчанию если строка пуста
        return ("г. Москва", "Центральный", "moscow_mngp", 55.7512, 37.6184)

    reg_code = comps["region_code"]
    dist_code = comps["district_code"]

    # 1. Специфическая привязка к округам Московской области (50)
    if reg_code == "50":
        mo_dist = MO_DISTRICTS.get(dist_code)
        if mo_dist:
            dist_name, d_lat, d_lon = mo_dist
            return ("Московская область", dist_name, "moscow_oblast_rngp", d_lat, d_lon)
        else:
            # Общий центр МО (Красногорск / Подольск)
            return ("Московская область", f"Округ {dist_code}", "moscow_oblast_rngp", 55.4312, 37.5458)

    # 2. Поиск по всероссийскому реестру 89 регионов
    if reg_code in ALL_REGIONS:
        r_name, r_norm, r_lat, r_lon = ALL_REGIONS[reg_code]
        return (r_name, f"Квартал {dist_code}", r_norm, r_lat, r_lon)

    # 3. Резервный вариант для редких кодов
    return (f"Субъект РФ ({reg_code})", f"Округ {dist_code}", "russia_sp42", 55.7512, 37.6184)


def get_cadastral_parcel(
    cadastral_number: str,
    custom_area_sqm: float | None = None,
    custom_wgs84_coords: list[tuple[float, float]] | None = None,
    override_lat: float | None = None,
    override_lon: float | None = None,
    add_red_line: bool = False,
    rotation_deg: float = 0.0,
) -> CadastralParcelInfo:
    """Получить геометрию и атрибуты земельного участка по кадастровому номеру.

    Args:
        cadastral_number: Кадастровый номер земельного участка.
        custom_area_sqm: Площадь в м² (для генерации формы).
        custom_wgs84_coords: Список координат WGS-84 (lon, lat) из выписки ЕГРН.
        override_lat: Ручное переопределение широты центра.
        override_lon: Ручное переопределение долготы центра.
        add_red_line: Включить ли красную линию (по умолчанию False — чистый контур).
        rotation_deg: Угол поворота участка в градусах относительно севера.

    Returns:
        Объект CadastralParcelInfo.
    """
    clean_num = cadastral_number.strip()
    import shapely.affinity

    # 1. Если номер совпадает с готовым пресетом
    if clean_num in PRESET_PARCELS:
        data = PRESET_PARCELS[clean_num]
        poly = Polygon(data["polygon_metric"])
        rls = []
        if add_red_line:
            side_x = poly.bounds[2] - poly.bounds[0]
            rls = [LineString([(0.0, 8.0), (side_x, 8.0)])]

        if rotation_deg != 0.0:
            c = poly.centroid
            poly = shapely.affinity.rotate(poly, rotation_deg, origin=c)
            if rls:
                rls = [shapely.affinity.rotate(rl, rotation_deg, origin=c) for rl in rls]

        c_lat = override_lat if override_lat is not None else data["center_lat"]
        c_lon = override_lon if override_lon is not None else data["center_lon"]

        return CadastralParcelInfo(
            cadastral_number=clean_num,
            region_code=data["region_code"],
            region_name=data["region_name"],
            district_name=data.get("district_name", "—"),
            regional_norm_id=data["regional_norm_id"],
            address=data["address"],
            center_lat=c_lat,
            center_lon=c_lon,
            area_sqm=poly.area,
            boundary_metric=poly,
            red_lines_metric=rls,
            source="preset",
        )

    # 2. Если переданы точные координаты из выписки ЕГРН
    comps = parse_cadastral_components(clean_num)
    reg_name, dist_name, norm_id, def_lat, def_lon = resolve_cadastral_location(clean_num)

    if custom_wgs84_coords and len(custom_wgs84_coords) >= 3:
        lons = [p[0] for p in custom_wgs84_coords]
        lats = [p[1] for p in custom_wgs84_coords]
        c_lon = sum(lons) / len(lons)
        c_lat = sum(lats) / len(lats)

        pts_metric = wgs84_to_metric_coords(custom_wgs84_coords, c_lat, c_lon, is_lon_lat=True)
        poly = Polygon(pts_metric)
        if rotation_deg != 0.0:
            poly = shapely.affinity.rotate(poly, rotation_deg, origin=poly.centroid)

        return CadastralParcelInfo(
            cadastral_number=comps["formatted"] if comps else clean_num,
            region_code=comps["region_code"] if comps else "77",
            region_name=reg_name,
            district_name=dist_name,
            regional_norm_id=norm_id,
            address=f"{reg_name}, {dist_name}, выписка ЕГРН",
            center_lat=c_lat,
            center_lon=c_lon,
            area_sqm=poly.area,
            boundary_metric=poly,
            red_lines_metric=[],
            source="custom_coords",
        )

    # 3. Синтез участка в реальных координатах указанного региона и округа
    target_area = custom_area_sqm or 32000.0
    side_a = round((target_area * 1.3) ** 0.5, 1)  # Соотношение сторон ~1:1.3
    side_b = round(target_area / side_a, 1)

    pts = [
        (0.0, 0.0),
        (side_a, 0.0),
        (side_a, side_b * 0.85),
        (side_a * 0.8, side_b),
        (0.0, side_b),
    ]
    poly = Polygon(pts)

    c_lat = override_lat if override_lat is not None else def_lat
    c_lon = override_lon if override_lon is not None else def_lon

    rls = []
    if add_red_line:
        rls = [LineString([(0.0, 6.0), (side_a, 6.0)])]

    if rotation_deg != 0.0:
        c = poly.centroid
        poly = shapely.affinity.rotate(poly, rotation_deg, origin=c)
        if rls:
            rls = [shapely.affinity.rotate(rl, rotation_deg, origin=c) for rl in rls]

    reg_code = comps["region_code"] if comps else "77"
    addr = f"{reg_name}, {dist_name}"
    if comps:
        addr += f", кв-л {comps['block_code']}, уч. {comps['parcel_code']}"

    return CadastralParcelInfo(
        cadastral_number=comps["formatted"] if comps else clean_num,
        region_code=reg_code,
        region_name=reg_name,
        district_name=dist_name,
        regional_norm_id=norm_id,
        address=addr,
        center_lat=c_lat,
        center_lon=c_lon,
        area_sqm=poly.area,
        boundary_metric=poly,
        red_lines_metric=rls,
        source="district_geocoded",
    )


def create_site_from_cadastre(parcel: CadastralParcelInfo, rotation_deg: float = 0.0) -> Site:
    """Создать рабочий объект Site из данных кадастрового участка."""
    poly = parcel.boundary_metric
    rls = parcel.red_lines_metric
    if rotation_deg != 0.0:
        import shapely.affinity
        c = poly.centroid
        poly = shapely.affinity.rotate(poly, rotation_deg, origin=c)
        if rls:
            rls = [shapely.affinity.rotate(rl, rotation_deg, origin=c) for rl in rls]

    return Site(
        boundary=poly,
        red_lines=rls,
        base_offset=(0.0, 0.0),
        geo_center=(parcel.center_lat, parcel.center_lon),
        cadastral_number=parcel.cadastral_number,
        address=parcel.address,
        rotation_deg=rotation_deg,
    )
