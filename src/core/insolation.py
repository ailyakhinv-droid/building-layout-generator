"""Модуль расчета инсоляции жилой застройки и проверки норм СанПиН 1.2.3685-21 и СП 42.13330.

Реализует:
1. Астрономическую геометрию солнца (Solar Position / SPA) для заданной широты и даты (22 апреля).
2. Трассировку теней (Ray Casting) с учетом взаимного затенения корпусов и окружающей застройки (OSM/CAD).
3. Расчет продолжительности непрерывной инсоляции на сетке оконных проемов фасадов.
4. Формирование 3D-тепловой карты фасадов для MapLibre GL JS (зеленый >= 2ч, янтарный 1.5-2ч, красный < 1.5ч).
5. Градостроительные ограничения для генератора застройки (каскадное понижение этажности при затенении).

# ponytail: lightweight geometric ray tracer directly integrated with MapLibre fill-extrusion — upgrade path: WebGL compute shader shadow maps
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from src.core.geo_utils import transform_geometry_to_metric, transform_geometry_to_wgs84
from src.models.building import Building, PlacedSection


# Нежилые и вспомогательные типы объектов OSM, исключаемые из фасадного расчета инсоляции
EXCLUDED_SURROUNDING_TYPES: set[str] = {
    "roof", "shed", "garage", "garages", "substation", "transformer",
    "kiosk", "cabin", "construction", "service", "greenhouse", "ruins",
    "demolished", "storage", "tank", "hangar", "barn", "carport", "parking",
}


@dataclass
class SolarPosition:
    """Положение солнца на небесной сфере."""

    hour: float
    azimuth_deg: float  # Азимут от севера по часовой стрелке (Север=0, Восток=90, Юг=180, Запад=270)
    elevation_deg: float  # Угол возвышения над горизонтом в градусах (0..90)
    sun_vector: tuple[float, float, float]  # Единичный вектор (dx, dy, dz), где +X=Восток, +Y=Север, +Z=Вверх


@dataclass
class FacadePointResult:
    """Результат расчета инсоляции в одной контрольной точке / ячейке фасада."""

    building_id: str
    section_index: int
    floor: int
    x: float
    y: float
    z: float
    normal_x: float
    normal_y: float
    direct_sun_hours: float  # Суммарное время солнца в часах
    continuous_sun_hours: float  # Максимальный непрерывный интервал инсоляции по СанПиН
    is_compliant: bool  # Соответствует норме СанПиН (непрерывная или прерывистая)
    color_hex: str  # Цвет для тепловой карты 3D (#10b981 - непрерывная, #06b6d4 - прерывистая, #f59e0b - погранично, #ef4444 - тень)
    insolation_type: str = "CONTINUOUS"  # CONTINUOUS | INTERMITTENT_OK | INTERMITTENT_FAIL | SHADED
    intermittent_hours: float = 0.0      # Сумма часов интервалов >= 1.0 ч
    intervals: list[dict[str, Any]] = field(default_factory=list)  # Временные окна инсоляции


@dataclass
class FacadeFacet:
    """3D грань / ячейка фасада для объемной визуализации тепловой карты в MapLibre GL JS."""

    building_id: str
    section_index: int
    floor: int
    polygon_metric: Polygon  # 4-точечный прямоугольник ячейки в локальных метрах
    base_z: float            # Отметка низа ячейки (м)
    top_z: float             # Отметка верха ячейки (м)
    continuous_sun_hours: float
    direct_sun_hours: float
    is_compliant: bool
    color_hex: str
    insolation_type: str = "CONTINUOUS"
    intermittent_hours: float = 0.0
    intervals: list[dict[str, Any]] = field(default_factory=list)
    is_surrounding: bool = False
    surrounding_id: str = ""
    surrounding_name: str = ""
    baseline_hours: float = 0.0
    delta_hours: float = 0.0


@dataclass
class InsolationConfig:
    """Параметры и ограничения контроля инсоляции."""

    enabled: bool = True
    norm_hours: float = 2.0  # 2.0 ч — Центральная зона, 1.5 ч — Южная, 2.5 ч — Северная
    zone_name: str = "central"  # central / south / north
    allow_intermittent: bool = True  # Прерывистая инсоляция по СанПиН 1.2.3685-21 (п. 164)
    include_surroundings: bool = True
    default_surrounding_height: float = 15.0
    grid_step_m: float = 3.0
    auto_cascade_reduction: bool = True
    calculation_date: str = "22 апреля (СанПиН 1.2.3685-21)"


@dataclass
class InsolationReport:
    """Сводный отчет по инсоляции застройки."""

    site_lat: float
    site_lon: float
    calculation_date: str
    required_hours: float
    total_facade_points: int
    compliant_points: int
    compliance_rate_percent: float
    facade_points: list[FacadePointResult] = field(default_factory=list)
    facade_facets: list[FacadeFacet] = field(default_factory=list)
    surrounding_facets: list[FacadeFacet] = field(default_factory=list)
    building_summary: dict[str, dict[str, Any]] = field(default_factory=dict)
    sanpin_compliant: bool = True
    warnings: list[str] = field(default_factory=list)
    continuous_compliant_points: int = 0
    intermittent_compliant_points: int = 0
    surrounding_impact: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Сериализовать отчет в JSON-совместимый словарь."""
        return {
            "site_lat": self.site_lat,
            "site_lon": self.site_lon,
            "calculation_date": self.calculation_date,
            "required_hours": self.required_hours,
            "total_facade_points": self.total_facade_points,
            "compliant_points": self.compliant_points,
            "compliance_rate_percent": self.compliance_rate_percent,
            "continuous_compliant_points": self.continuous_compliant_points,
            "intermittent_compliant_points": self.intermittent_compliant_points,
            "surrounding_impact": self.surrounding_impact,
            "sanpin_compliant": self.sanpin_compliant,
            "warnings": self.warnings,
            "building_summary": self.building_summary,
            "points_count": len(self.facade_points),
            "facets_count": len(self.facade_facets),
            "surrounding_facets_count": len(self.surrounding_facets),
        }

    def to_geojson_facets(
        self,
        center_lat: float,
        center_lon: float,
        include_surroundings: bool = True,
    ) -> dict[str, Any]:
        """Сформировать GeoJSON FeatureCollection 3D-граней для MapLibre GL fill-extrusion."""
        features = []
        all_facets = list(self.facade_facets)
        if include_surroundings and self.surrounding_facets:
            all_facets.extend(self.surrounding_facets)

        for f in all_facets:
            wgs_poly = transform_geometry_to_wgs84(f.polygon_metric, center_lat, center_lon)
            type_label = (
                "непрерывная норма" if f.insolation_type == "CONTINUOUS"
                else "прерывистая норма" if f.insolation_type == "INTERMITTENT_OK"
                else "дефицит"
            )
            props = {
                "type": "insolation_facet",
                "is_surrounding": f.is_surrounding,
                "building_id": f.building_id,
                "section_index": f.section_index,
                "floor": f.floor,
                "base_z": round(f.base_z, 2),
                "top_z": round(f.top_z, 2),
                "min_height": round(f.base_z, 2),
                "height": round(f.top_z, 2),
                "continuous_sun_hours": round(f.continuous_sun_hours, 1),
                "direct_sun_hours": round(f.direct_sun_hours, 1),
                "intermittent_hours": round(f.intermittent_hours, 1),
                "insolation_type": f.insolation_type,
                "intervals": f.intervals,
                "is_compliant": f.is_compliant,
                "color": f.color_hex,
                "color_hex": f.color_hex,
            }
            if f.is_surrounding:
                props["surrounding_id"] = f.surrounding_id or f.building_id
                props["surrounding_name"] = f.surrounding_name or f.building_id
                props["baseline_hours"] = round(f.baseline_hours, 1)
                props["delta_hours"] = round(f.delta_hours, 1)
                props["label"] = f"{f.surrounding_name or 'Окружение'}: Этаж {f.floor} — {f.continuous_sun_hours:.1f} ч (дельта: {f.delta_hours:+.1f} ч)"
            else:
                props["label"] = f"Этаж {f.floor}: {f.continuous_sun_hours:.1f} ч ({type_label})"

            wgs_coords = [[round(coord[0], 6), round(coord[1], 6)] for coord in wgs_poly.exterior.coords]
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [wgs_coords],
                },
                "properties": props,
            })
        return {"type": "FeatureCollection", "features": features}


def calculate_solar_position(
    lat_deg: float,
    time_hour: float,
    day_of_year: int = 112,  # 22 апреля = 112-й день года (день равноденствия по СанПиН)
) -> SolarPosition:
    """Вычислить азимут и высоту солнца по астрономическому алгоритму SPA.
    
    Args:
        lat_deg: Географическая широта в градусах (например, 56.85 для Ижевска, 55.75 для Москвы).
        time_hour: Местное солнечное время в часах (например, 12.0 = истинный астрономический полдень).
        day_of_year: День года (1..365). 22 апреля = 112-й день.
    """
    phi = math.radians(lat_deg)
    
    # 1. Склонение солнца (Solar Declination angle)
    # По формуле Купера: delta = 23.45 * sin(360/365 * (284 + n))
    gamma = 2.0 * math.pi * (284 + day_of_year) / 365.0
    delta = math.radians(23.45 * math.sin(gamma))

    # 2. Часовой угол солнца (Hour Angle): 15 градусов на час от полудня
    omega = math.radians(15.0 * (time_hour - 12.0))

    # 3. Угол возвышения солнца (Solar Altitude / Elevation)
    sin_beta = math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.cos(omega)
    sin_beta = max(-1.0, min(1.0, sin_beta))
    beta = math.asin(sin_beta)
    elev_deg = math.degrees(beta)

    if elev_deg <= 0.0:
        return SolarPosition(
            hour=time_hour,
            azimuth_deg=0.0,
            elevation_deg=0.0,
            sun_vector=(0.0, 0.0, -1.0)
        )

    # 4. Солнечный азимут (от севера по часовой стрелке: Восток=90, Юг=180, Запад=270)
    cos_phi = math.cos(phi)
    cos_beta = math.cos(beta)
    
    cos_alpha = (math.sin(delta) * math.cos(phi) - math.cos(delta) * math.sin(phi) * math.cos(omega)) / max(1e-6, cos_beta)
    cos_alpha = max(-1.0, min(1.0, cos_alpha))
    alpha = math.acos(cos_alpha)
    
    # Если до полудня (утро) — солнце на востоке (0..180), после полудня — на западе (180..360)
    if omega > 0:
        azim_deg = 360.0 - math.degrees(alpha)
    else:
        azim_deg = math.degrees(alpha)

    # Вектор солнца (+X = Восток, +Y = Север, +Z = Вверх)
    rad_azim = math.radians(azim_deg)
    sx = math.sin(rad_azim) * cos_beta
    sy = math.cos(rad_azim) * cos_beta
    sz = sin_beta

    return SolarPosition(
        hour=round(time_hour, 2),
        azimuth_deg=round(azim_deg, 2),
        elevation_deg=round(elev_deg, 2),
        sun_vector=(sx, sy, sz)
    )


def get_sun_path(
    lat_deg: float,
    day_of_year: int = 112,
    start_hour: float = 7.0,
    end_hour: float = 19.0,
    step_minutes: int = 30,
) -> list[SolarPosition]:
    """Сгенерировать суточный путь солнца на расчетный день 22 апреля по СанПиН."""
    step_h = step_minutes / 60.0
    positions: list[SolarPosition] = []
    t = start_hour
    while t <= end_hour + 1e-4:
        pos = calculate_solar_position(lat_deg, t, day_of_year)
        # По нормам СанПиН солнце учитывается только при высоте над горизонтом >= 8 градусов
        if pos.elevation_deg >= 8.0:
            positions.append(pos)
        t += step_h
    return positions


class InsolationCalculator:
    """Движок расчета инсоляции и построения тепловых карт фасадов."""

    def __init__(
        self,
        site_lat: float = 56.85,
        site_lon: float = 53.20,
        required_hours: float = 2.0,
        day_of_year: int = 112,
        grid_step_m: float = 3.0,
        surrounding_buildings: list[Any] | None = None,
        default_surrounding_height: float = 15.0,
        surrounding_height_overrides: dict[str, float] | None = None,
        allow_intermittent: bool = True,
        site_boundary: Polygon | None = None,
    ):
        self.lat = site_lat if abs(site_lat) > 1.0 else 56.85
        self.lon = site_lon if abs(site_lon) > 1.0 else 53.20
        self.required_hours = float(required_hours)
        self.day_of_year = day_of_year
        self.grid_step = max(1.5, float(grid_step_m))
        self.default_surrounding_height = default_surrounding_height
        self.surrounding_height_overrides = surrounding_height_overrides or {}
        self.allow_intermittent = allow_intermittent
        self.site_boundary = site_boundary
        self.surrounding_polys: list[tuple[Polygon, float]] = []
        self.surrounding_raw_items: list[dict[str, Any]] = []

        site_bounds = site_boundary.bounds if (site_boundary is not None and not site_boundary.is_empty) else None

        # Загружаем окружающую застройку в локальных метрах с поддержкой ручных переопределений
        if surrounding_buildings:
            for item_idx, item in enumerate(surrounding_buildings):
                if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], Polygon):
                    poly_t = orient(item[0], sign=1.0)
                    h_t = float(item[1])
                    if poly_t.is_valid and poly_t.area >= 20.0 and h_t >= 3.0:
                        if site_bounds is not None and self.lat > 0:
                            if poly_t.bounds[1] > site_bounds[3] + 5.0:
                                continue
                            max_shadow_reach = min(220.0, max(120.0, h_t * 3.75))
                            if self.site_boundary is not None and poly_t.distance(self.site_boundary) > max_shadow_reach:
                                continue
                        self.surrounding_polys.append((poly_t, h_t))
                        self.surrounding_raw_items.append({
                            "id": f"surr_{item_idx + 1}",
                            "name": f"Здание {item_idx + 1}",
                            "building_type": "building",
                            "levels": max(1, round(h_t / 3.0)),
                            "height_m": h_t,
                            "polygon_metric": poly_t,
                            "properties": {},
                        })
                    continue

                if isinstance(item, dict):
                    geom = item.get("geometry")
                    props = item.get("properties", {})
                    b_id = str(props.get("id") or props.get("osm_id") or f"surr_{item_idx + 1}")
                    b_type = str(props.get("building_type") or props.get("building") or "building").lower()

                    # Отсекаем нежилые хозпостройки: сараи, гаражи, кровли, подстанции
                    if b_type in EXCLUDED_SURROUNDING_TYPES:
                        continue

                    if b_id in self.surrounding_height_overrides:
                        h = float(self.surrounding_height_overrides[b_id])
                    else:
                        h = float(
                            props.get("height")
                            or props.get("height_m")
                            or (float(props.get("levels") or 5) * 3.0)
                            or default_surrounding_height
                        )

                    if h < 3.0:
                        continue

                    if geom:
                        try:
                            shp = shape(geom)
                            sub_polys: list[Polygon] = []
                            if isinstance(shp, Polygon):
                                sub_polys = [shp]
                            elif isinstance(shp, MultiPolygon):
                                sub_polys = list(shp.geoms)

                            for p_i, poly in enumerate(sub_polys):
                                if not poly.is_valid or poly.is_empty:
                                    continue
                                minx, miny, maxx, maxy = poly.bounds
                                if poly.area < 0.05 and -180 <= minx <= 180 and -90 <= miny <= 90:
                                    poly_metric = transform_geometry_to_metric(poly, self.lat, self.lon)
                                else:
                                    poly_metric = poly

                                if not poly_metric.is_valid or poly_metric.is_empty:
                                    continue

                                # Отсекаем мелкие объекты < 35 м²
                                if poly_metric.area < 35.0:
                                    continue

                                # Отсекаем здания, физически не способные затенять участок
                                if site_bounds is not None and self.lat > 0:
                                    # В северном полушарии солнце светит с юга; здание строго севернее участка не отбрасывает тень на юг
                                    if poly_metric.bounds[1] > site_bounds[3] + 5.0:
                                        continue
                                    # Здания дальше максимальной расчетной длины тени (3.75 * H, макс 220м)
                                    max_shadow_reach = min(220.0, max(120.0, h * 3.75))
                                    if self.site_boundary is not None and poly_metric.distance(self.site_boundary) > max_shadow_reach:
                                        continue

                                poly_metric = orient(poly_metric, sign=1.0)
                                sub_id = b_id if len(sub_polys) == 1 else f"{b_id}_{p_i+1}"
                                self.surrounding_polys.append((poly_metric, h))
                                self.surrounding_raw_items.append({
                                    "id": sub_id,
                                    "name": props.get("name") or b_id,
                                    "building_type": b_type,
                                    "levels": max(1, round(h / 3.0)),
                                    "height_m": h,
                                    "polygon_metric": poly_metric,
                                    "properties": props,
                                })
                        except Exception:
                            pass

    def calculate_masterplan_insolation(
        self,
        buildings: list[Building],
        include_surroundings: bool = True,
        compute_surrounding_heatmap: bool = True,
    ) -> InsolationReport:
        """Рассчитать инсоляцию для всех фасадов застройки по сетке точек оконных проемов.
        
        Args:
            buildings: Список размещенных зданий комплекса.
            include_surroundings: Учитывать ли затенение от окружающей застройки.
            compute_surrounding_heatmap: Выполнять ли расчет тепловой карты для окружающих зданий (отключается для быстрых промежуточных калибровок).
        """
        sun_path = get_sun_path(self.lat, self.day_of_year, start_hour=7.0, end_hour=19.0, step_minutes=30)
        dt_hour = 0.5  # Шаг времени 30 минут

        if not sun_path or not buildings:
            return InsolationReport(
                site_lat=self.lat,
                site_lon=self.lon,
                calculation_date="22 апреля (СанПиН 1.2.3685-21)",
                required_hours=self.required_hours,
                total_facade_points=0,
                compliant_points=0,
                compliance_rate_percent=100.0,
                sanpin_compliant=True,
            )

        # 1. Подготавливаем затеняющие полигоны всех препятствий (наши здания + окружение) с предрасчитанными габаритами AABB и ребрами
        def _extract_edges(poly_geom: Any) -> list[tuple[float, float, float, float, float, float]]:
            res_edges = []
            geoms = getattr(poly_geom, "geoms", [poly_geom])
            for g in geoms:
                if not hasattr(g, "exterior") or not g.exterior:
                    continue
                c = list(g.exterior.coords)
                for i in range(len(c) - 1):
                    x1, y1 = c[i]
                    x2, y2 = c[i + 1]
                    res_edges.append((x1, y1, x2, y2, x2 - x1, y2 - y1))
            return res_edges

        obstacles: list[tuple[Any, float, tuple[float, float, float, float], list[Any]]] = []
        for b_idx, b in enumerate(buildings):
            h_b = b.height
            fp = getattr(b, "footprint", None) or b.polygon
            if fp and not fp.is_empty:
                obstacles.append((fp, h_b, fp.bounds, _extract_edges(fp)))

        if include_surroundings and self.surrounding_polys:
            for p, h in self.surrounding_polys:
                obstacles.append((p, h, p.bounds, _extract_edges(p)))

        facade_results: list[FacadePointResult] = []
        facade_facets: list[FacadeFacet] = []
        building_stats: dict[str, dict[str, Any]] = {}

        # 2. Генерируем контрольные точки и 3D-грани на наружных гранях секций каждого корпуса
        # ponytail: фильтрация глухих стыковочных стен между секциями + 8-28 см отступ и скос углов исключают рябь (Z-fighting) — upgrade path: поддержка криволинейных радиусных фасадов
        for b_idx, b in enumerate(buildings):
            b_id = f"b{b_idx + 1}"
            b_points: list[FacadePointResult] = []

            b_fp = getattr(b, "footprint", None) or getattr(b, "polygon", None)
            if b_fp is None or b_fp.is_empty:
                b_fp = unary_union([s.footprint for s in b.sections if s.footprint and not s.footprint.is_empty])
            if b_fp is not None and not b_fp.is_empty:
                b_fp = orient(b_fp, sign=1.0)
            b_boundary = b_fp.boundary if (b_fp and not b_fp.is_empty) else None

            for s_idx, sec in enumerate(b.sections):
                s_fp = sec.footprint
                if not s_fp or s_fp.is_empty:
                    continue
                # Нормализуем ориентацию полигона секции против часовой стрелки (CCW)
                # Это гарантирует, что внешняя нормаль (dy, -dx) смотрит строго наружу здания
                s_fp = orient(s_fp, sign=1.0)

                fl_count = sec.floors
                fh = sec.effective_floor_height
                gfh = sec.effective_ground_floor_height

                coords = list(s_fp.exterior.coords)[:-1]
                n_coords = len(coords)

                for seg_i in range(n_coords):
                    p1 = coords[seg_i]
                    p2 = coords[(seg_i + 1) % n_coords]
                    dx = p2[0] - p1[0]
                    dy = p2[1] - p1[1]
                    seg_len = math.hypot(dx, dy)
                    if seg_len < 1.0:
                        continue

                    # Вектор нормали к грани наружу
                    nx = dy / seg_len
                    ny = -dx / seg_len
                    ux = dx / seg_len
                    uy = dy / seg_len

                    # Проверка наружности сегмента стены
                    mx = (p1[0] + p2[0]) * 0.5
                    my = (p1[1] + p2[1]) * 0.5
                    mid_pt = Point(mx, my)

                    # 1. Отсекаем внутренние стыковочные стены между секциями внутри корпуса
                    if b_boundary is not None and b_boundary.distance(mid_pt) > 0.15:
                        continue

                    # 2. Проверяем, что нормаль направлена строго наружу здания (а не внутрь смежной секции)
                    test_out = Point(mx + nx * 0.20, my + ny * 0.20)
                    if b_fp is not None and b_fp.contains(test_out):
                        continue

                    # Проверка на глухой торец секции (без жилых окон):
                    # У рядовых секций (MIDDLE) торцы шириной = depth глухие стыковочные.
                    # По СанПиН 1.2.3685-21 (п. 164) инсоляция нормируется для жилых комнат, а не для глухих торцов.
                    is_blind_wall = False
                    if getattr(sec.section_type, "category", "").upper() == "MIDDLE":
                        sec_ang_rad = math.radians(sec.angle)
                        dot_long = abs(nx * math.cos(sec_ang_rad) + ny * math.sin(sec_ang_rad))
                        if dot_long > 0.8:
                            is_blind_wall = True

                    # Шаг ячеек вдоль грани
                    n_steps = max(1, round(seg_len / self.grid_step))
                    d_in = 0.08   # 8 см от стены (исключает Z-fighting с телом здания)
                    d_out = 0.28  # 28 см от стены (толщина расчетной фасадной кассеты 20 см)

                    for step_k in range(n_steps):
                        t_a = step_k / n_steps
                        t_b = (step_k + 1) / n_steps
                        t_mid = (step_k + 0.5) / n_steps

                        # Скос угловых стыков: на крайних панелях отступаем от угловой вершины на 29 см (толщина d_out = 0.28 м + 1 см запас),
                        # чтобы перпендикулярные фасадные кассеты на углах не пересекались и не рябили в 3D (исключение Z-fighting)
                        corner_inset = min(0.29, seg_len * 0.25)
                        w_ax = p1[0] + dx * t_a + (ux * corner_inset if step_k == 0 else 0.0)
                        w_ay = p1[1] + dy * t_a + (uy * corner_inset if step_k == 0 else 0.0)
                        w_bx = p1[0] + dx * t_b - (ux * corner_inset if step_k == n_steps - 1 else 0.0)
                        w_by = p1[1] + dy * t_b - (uy * corner_inset if step_k == n_steps - 1 else 0.0)

                        # Точка расчета инсоляции (на 18 см снаружи стены, строго по центру кассеты)
                        gx = p1[0] + dx * t_mid + nx * 0.18
                        gy = p1[1] + dy * t_mid + ny * 0.18

                        # 2D полигон ячейки фасада (выдвинут на 8-28 см наружу от стены)
                        poly_facet = Polygon([
                            (w_ax + nx * d_in, w_ay + ny * d_in),
                            (w_bx + nx * d_in, w_by + ny * d_in),
                            (w_bx + nx * d_out, w_by + ny * d_out),
                            (w_ax + nx * d_out, w_ay + ny * d_out),
                            (w_ax + nx * d_in, w_ay + ny * d_in),
                        ])

                        # По каждому жилому этажу
                        start_fl = 2 if getattr(sec.section_type, "has_commercial_ground", False) else 1
                        for fl in range(start_fl, fl_count + 1):
                            fl_base = gfh + (fl - 2) * fh if fl > 1 else 0.0
                            fl_h = fh if fl > 1 else gfh
                            # 3 см отступ по вертикали исключает наложение ребер между этажами
                            base_z = round(fl_base + 0.03, 2)
                            top_z = round(fl_base + fl_h - 0.03, 2)
                            gz = (base_z + top_z) * 0.5
                            gz = (base_z + top_z) * 0.5

                            # Проверяем видимость солнца для каждого момента дня
                            sun_timeline: list[bool] = []
                            for sun_pos in sun_path:
                                # Проверка ориентации грани к солнцу (нормаль . вектор солнца)
                                sx, sy, sz = sun_pos.sun_vector
                                if (nx * sx + ny * sy) <= 0.05:
                                    # Солнце с обратной стороны стены
                                    sun_timeline.append(False)
                                    continue

                                # Трассировка луча к солнцу (Ray Casting против препятствий)
                                is_shaded = self._is_ray_blocked(
                                    gx, gy, gz, sx, sy, sz, obstacles, current_footprint=s_fp
                                )
                                sun_timeline.append(not is_shaded)

                            # Анализ интервалов инсоляции по нормам СанПиН 1.2.3685-21 (п. 164)
                            (
                                max_continuous,
                                sum_intermittent,
                                insol_type,
                                is_ok,
                                col,
                                intervals,
                            ) = self._analyze_intervals(
                                sun_timeline, sun_path, dt_hour, self.required_hours, self.allow_intermittent
                            )
                            total_hours = sum(sun_timeline) * dt_hour

                            if is_blind_wall:
                                # Глухой торец секции без жилых окон (СанПиН 1.2.3685-21 не требует инсоляции глухих стен)
                                is_ok = True
                                col = "#94a3b8"
                                insol_type = "blind_wall"

                            pt_res = FacadePointResult(
                                building_id=b_id,
                                section_index=s_idx,
                                floor=fl,
                                x=round(gx, 2),
                                y=round(gy, 2),
                                z=round(gz, 2),
                                normal_x=round(nx, 3),
                                normal_y=round(ny, 3),
                                direct_sun_hours=round(total_hours, 1),
                                continuous_sun_hours=round(max_continuous, 1),
                                is_compliant=is_ok,
                                color_hex=col,
                                insolation_type=insol_type,
                                intermittent_hours=round(sum_intermittent, 1),
                                intervals=intervals,
                            )
                            b_points.append(pt_res)

                            # 3D грань фасада
                            facade_facets.append(FacadeFacet(
                                building_id=b_id,
                                section_index=s_idx,
                                floor=fl,
                                polygon_metric=poly_facet,
                                base_z=base_z,
                                top_z=top_z,
                                continuous_sun_hours=max_continuous,
                                direct_sun_hours=total_hours,
                                is_compliant=is_ok,
                                color_hex=col,
                                insolation_type=insol_type,
                                intermittent_hours=sum_intermittent,
                                intervals=intervals,
                            ))

            facade_results.extend(b_points)
            if b_points:
                b_ok = sum(1 for p in b_points if p.is_compliant)
                building_stats[b_id] = {
                    "total_points": len(b_points),
                    "compliant_points": b_ok,
                    "rate_percent": round(b_ok / len(b_points) * 100.0, 1),
                    "avg_sun_hours": round(sum(p.continuous_sun_hours for p in b_points) / len(b_points), 1),
                }

        total_pts = len(facade_results)
        comp_pts = sum(1 for p in facade_results if p.is_compliant)
        cont_ok = sum(1 for p in facade_results if p.insolation_type == "CONTINUOUS")
        interm_ok = sum(1 for p in facade_results if p.insolation_type == "INTERMITTENT_OK")
        rate = round((comp_pts / total_pts * 100.0), 1) if total_pts > 0 else 100.0

        # Оценка влияния на окружающую застройку (затенение соседних домов)
        surrounding_impact = None
        if include_surroundings and compute_surrounding_heatmap and self.surrounding_raw_items:
            try:
                surrounding_impact = self.calculate_surrounding_impact(buildings)
            except Exception as e:
                surrounding_impact = {"error": str(e), "buildings": []}

        warnings = []
        if rate < 75.0:
            warnings.append(
                f"Внимание: {100.0 - rate:.1f}% фасадов имеют инсоляцию менее {self.required_hours:.1f} ч по СанПиН 1.2.3685-21. Рекомендуется ориентация широтных корпусов или каскадное понижение южных крыльев."
            )
        if surrounding_impact and surrounding_impact.get("critical_violations_count", 0) > 0:
            warnings.append(
                f"Внимание: затенение проектом снизило инсоляцию ниже норм СанПиН в {surrounding_impact['critical_violations_count']} точках окружающей застройки."
            )

        return InsolationReport(
            site_lat=self.lat,
            site_lon=self.lon,
            calculation_date="22 апреля (СанПиН 1.2.3685-21)",
            required_hours=self.required_hours,
            total_facade_points=total_pts,
            compliant_points=comp_pts,
            compliance_rate_percent=rate,
            facade_points=facade_results,
            facade_facets=facade_facets,
            surrounding_facets=getattr(self, "_surrounding_facets", []),
            building_summary=building_stats,
            sanpin_compliant=(rate >= 75.0),
            warnings=warnings,
            continuous_compliant_points=cont_ok,
            intermittent_compliant_points=interm_ok,
            surrounding_impact=surrounding_impact,
        )

    def calculate_surrounding_impact(
        self,
        new_buildings: list[Building],
        max_distance_m: float = 180.0,
    ) -> dict[str, Any]:
        """Оценить затенение окружающей застройки проектируемыми корпусами (Baseline vs With-Project).
        
        Выявляет:
        1. Здания, попавшие в зону затенения от новых корпусов (дельта инсоляции < -0.1 ч).
        2. Критические точки, где до проекта норма СанПиН выполнялась, а после посадки — нарушена.
        3. Генерирует 3D-фасетки инсоляции фасадов для окружающей застройки с цветовой дифференциацией.
        """
        sun_path = get_sun_path(self.lat, self.day_of_year, start_hour=7.0, end_hour=19.0, step_minutes=30)
        dt_hour = 0.5

        new_obstacles: list[tuple[Polygon, float]] = []
        for b in new_buildings:
            fp = getattr(b, "footprint", None) or getattr(b, "polygon", None)
            if fp and not fp.is_empty:
                new_obstacles.append((fp, b.height))

        if not self.surrounding_raw_items or not new_obstacles:
            self._surrounding_facets = []
            return {
                "total_surrounding_checked": 0,
                "buildings_with_shadow_impact": 0,
                "critical_violations_count": 0,
                "sanpin_surroundings_compliant": True,
                "buildings": [],
                "summary_text": "Окружающая застройка или проектируемые здания отсутствуют.",
            }

        def _extract_edges_local(poly_geom: Any) -> list[tuple[float, float, float, float, float, float]]:
            res_edges = []
            geoms = getattr(poly_geom, "geoms", [poly_geom])
            for g in geoms:
                if not hasattr(g, "exterior") or not g.exterior:
                    continue
                c = list(g.exterior.coords)
                for i in range(len(c) - 1):
                    x1, y1 = c[i]
                    x2, y2 = c[i + 1]
                    res_edges.append((x1, y1, x2, y2, x2 - x1, y2 - y1))
            return res_edges

        all_surr_obstacles = [(s["polygon_metric"], s["height_m"], s["polygon_metric"].bounds, _extract_edges_local(s["polygon_metric"])) for s in self.surrounding_raw_items]
        new_union = unary_union([p for p, _ in new_obstacles])

        candidate_buildings = []
        for item in self.surrounding_raw_items:
            poly = item["polygon_metric"]
            b_type = str(item.get("building_type", "")).lower()
            if b_type in EXCLUDED_SURROUNDING_TYPES:
                continue
            if poly.area < 35.0 or float(item.get("height_m", 0)) < 3.5:
                continue
            dist = poly.distance(new_union)
            if dist <= max_distance_m:
                candidate_buildings.append(item)

        if not candidate_buildings:
            self._surrounding_facets = []
            return {
                "total_surrounding_checked": 0,
                "buildings_with_shadow_impact": 0,
                "critical_violations_count": 0,
                "sanpin_surroundings_compliant": True,
                "buildings": [],
                "summary_text": f"Окружающая застройка находится за пределами радиуса возможного взаимодействия ({max_distance_m:.0f} м).",
            }

        surrounding_results = []
        surrounding_facets: list[FacadeFacet] = []
        total_critical_points = 0
        combined_obstacles = all_surr_obstacles + [(p, h, p.bounds, _extract_edges_local(p)) for p, h in new_obstacles]

        for item in candidate_buildings:
            # Нормализуем ориентацию полигона здания против часовой стрелки (CCW)
            # Это гарантирует, что фасетки фасадов строятся СНАРУЖИ объема здания, а не внутри!
            s_poly = orient(item["polygon_metric"], sign=1.0)
            s_id = str(item["id"])
            s_name = str(item["name"] or item["id"])
            s_h = float(item["height_m"])
            s_levels = int(item["levels"] or max(1, round(s_h / 3.0)))
            b_type = item["building_type"]

            coords = list(s_poly.exterior.coords)[:-1]
            n_c = len(coords)
            pts_baseline_hours = []
            pts_project_hours = []
            building_critical_pts = 0

            n_floors = max(1, min(16, s_levels))
            fl_h = s_h / n_floors

            for i in range(n_c):
                p1 = coords[i]
                p2 = coords[(i + 1) % n_c]
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                seg_len = math.hypot(dx, dy)
                if seg_len < 2.5:
                    continue

                nx = dy / seg_len
                ny = -dx / seg_len
                ux = dx / seg_len
                uy = dy / seg_len

                n_panels = max(1, min(3, int(math.ceil(seg_len / 12.0))))
                for p_idx in range(n_panels):
                    t_a = p_idx / n_panels
                    t_b = (p_idx + 1) / n_panels
                    t_mid = (t_a + t_b) * 0.5
                    corner_inset = min(0.18, (seg_len / n_panels) * 0.2)
                    w_ax = p1[0] + dx * t_a + (ux * corner_inset if p_idx == 0 else 0.0)
                    w_ay = p1[1] + dy * t_a + (uy * corner_inset if p_idx == 0 else 0.0)
                    w_bx = p1[0] + dx * t_b - (ux * corner_inset if p_idx == n_panels - 1 else 0.0)
                    w_by = p1[1] + dy * t_b - (uy * corner_inset if p_idx == n_panels - 1 else 0.0)

                    d_in = 0.08
                    d_out = 0.28
                    facet_poly = Polygon([
                        (w_ax + nx * d_in, w_ay + ny * d_in),
                        (w_bx + nx * d_in, w_by + ny * d_in),
                        (w_bx + nx * d_out, w_by + ny * d_out),
                        (w_ax + nx * d_out, w_ay + ny * d_out),
                        (w_ax + nx * d_in, w_ay + ny * d_in),
                    ])

                    gx = p1[0] + dx * t_mid + nx * 0.20
                    gy = p1[1] + dy * t_mid + ny * 0.20

                    for fl in range(1, n_floors + 1):
                        base_z = round((fl - 1) * fl_h + 0.03, 2)
                        top_z = round(fl * fl_h - 0.03, 2)
                        gz = (base_z + top_z) * 0.5

                        # 1. Baseline (БЕЗ нового проекта)
                        base_timeline = []
                        for sp in sun_path:
                            sx, sy, sz = sp.sun_vector
                            if (nx * sx + ny * sy) <= 0.05:
                                base_timeline.append(False)
                            else:
                                is_blk = self._is_ray_blocked(gx, gy, gz, sx, sy, sz, all_surr_obstacles, s_poly)
                                base_timeline.append(not is_blk)

                        base_cont, base_sum, _, base_ok, _, base_intervals = self._analyze_intervals(
                            base_timeline, sun_path, dt_hour, self.required_hours, self.allow_intermittent
                        )

                        # 2. With-Project (С новым проектом)
                        proj_timeline = []
                        for sp in sun_path:
                            sx, sy, sz = sp.sun_vector
                            if (nx * sx + ny * sy) <= 0.05:
                                proj_timeline.append(False)
                            else:
                                is_blk = self._is_ray_blocked(gx, gy, gz, sx, sy, sz, combined_obstacles, s_poly)
                                proj_timeline.append(not is_blk)

                        proj_cont, proj_sum, insol_type, proj_ok, _, proj_intervals = self._analyze_intervals(
                            proj_timeline, sun_path, dt_hour, self.required_hours, self.allow_intermittent
                        )

                        delta = round(proj_cont - base_cont, 1)

                        # Раскраска фасетки окружающего дома:
                        # Зеленый — норма непрерывная, Бирюзовый — норма прерывистая,
                        # Красный — критическое затенение проектом (была норма, стала не норма!),
                        # Янтарный — затенение проектом (без нарушения нормы, если нормы не было или норма осталась),
                        # Нейтрально-серый — затенение собственным домом / северный фасад
                        if proj_cont >= self.required_hours:
                            f_col = "#10b981"
                        elif proj_ok:
                            f_col = "#06b6d4"
                        elif base_ok and not proj_ok:
                            f_col = "#ef4444"
                        elif delta < -0.2:
                            f_col = "#f59e0b"
                        else:
                            f_col = "#94a3b8"

                        surrounding_facets.append(FacadeFacet(
                            building_id=s_id,
                            section_index=0,
                            floor=fl,
                            polygon_metric=facet_poly,
                            base_z=base_z,
                            top_z=top_z,
                            continuous_sun_hours=proj_cont,
                            direct_sun_hours=round(sum(proj_timeline) * dt_hour, 1),
                            is_compliant=proj_ok,
                            color_hex=f_col,
                            insolation_type=insol_type,
                            intermittent_hours=proj_sum,
                            intervals=proj_intervals,
                            is_surrounding=True,
                            surrounding_id=s_id,
                            surrounding_name=s_name,
                            baseline_hours=base_cont,
                            delta_hours=delta,
                        ))

                        # На 1 этаже фиксируем статистику здания по СанПиН
                        if fl == 1:
                            pts_baseline_hours.append(base_cont)
                            pts_project_hours.append(proj_cont)
                            if base_ok and not proj_ok:
                                building_critical_pts += 1
                                total_critical_points += 1

            if not pts_baseline_hours:
                continue

            avg_base = sum(pts_baseline_hours) / len(pts_baseline_hours)
            avg_proj = sum(pts_project_hours) / len(pts_project_hours)
            delta = avg_proj - avg_base

            status = "CRITICAL_DEFICIT" if building_critical_pts > 0 else ("SHADED" if delta < -0.1 else "NO_IMPACT")

            surrounding_results.append({
                "id": s_id,
                "name": s_name,
                "building_type": b_type,
                "levels": s_levels,
                "height_m": round(s_h, 1),
                "is_overridden": bool(s_id in self.surrounding_height_overrides),
                "baseline_avg_hours": round(avg_base, 1),
                "project_avg_hours": round(avg_proj, 1),
                "delta_hours": round(delta, 1),
                "is_shaded_by_project": (delta < -0.1),
                "critical_points_count": building_critical_pts,
                "sanpin_status": status,
            })

        self._surrounding_facets = surrounding_facets

        impacted_cnt = sum(1 for b in surrounding_results if b["is_shaded_by_project"])
        is_compliant = (total_critical_points == 0)

        if is_compliant:
            summary_txt = f"Проверено {len(surrounding_results)} соседних зданий. Нормы СанПиН соблюдены: критических затенений не выявлено."
        else:
            summary_txt = f"Внимание: выявлено {total_critical_points} контрольных точек с падением инсоляции ниже СанПиН в {impacted_cnt} зданиях окружения."

        return {
            "total_surrounding_checked": len(surrounding_results),
            "buildings_with_shadow_impact": impacted_cnt,
            "critical_violations_count": total_critical_points,
            "sanpin_surroundings_compliant": is_compliant,
            "buildings": surrounding_results,
            "summary_text": summary_txt,
        }

    @staticmethod
    def _analyze_intervals(
        timeline: list[bool],
        sun_path: list[SolarPosition],
        dt_hour: float,
        required_hours: float,
        allow_intermittent: bool = True,
    ) -> tuple[float, float, str, bool, str, list[dict[str, Any]]]:
        """Анализ интервалов инсоляции по нормам СанПиН 1.2.3685-21 (п. 164).
        
        Нормативные требования:
        1. Непрерывная инсоляция: один непрерывный интервал >= required_hours (например, 2.0 ч).
        2. Прерывистая инсоляция: допускается прерывистость, если один из периодов >= 1.0 ч,
           а суммарная продолжительность всех периодов >= 1.0 ч увеличивается на 0.5 ч
           (т.е. >= required_hours + 0.5 = 2.5 ч для центральной зоны).
        """
        intervals: list[dict[str, Any]] = []
        n = len(timeline)
        i = 0

        def _fmt_time(h_val: float) -> str:
            hh = int(h_val)
            mm = int(round((h_val - hh) * 60))
            return f"{hh:02d}:{mm:02d}"

        while i < n:
            if timeline[i]:
                start_idx = i
                while i < n and timeline[i]:
                    i += 1
                end_idx = i
                streak_len = end_idx - start_idx
                dur = round(streak_len * dt_hour, 2)
                start_h = sun_path[start_idx].hour if start_idx < len(sun_path) else 7.0 + start_idx * dt_hour
                end_h = round(start_h + dur, 2)
                intervals.append({
                    "start": start_h,
                    "end": end_h,
                    "start_str": _fmt_time(start_h),
                    "end_str": _fmt_time(end_h),
                    "duration": dur,
                    "qualifies": dur >= 1.0,
                })
            else:
                i += 1

        max_continuous = max((iv["duration"] for iv in intervals), default=0.0)
        qualifying_intervals = [iv for iv in intervals if iv["duration"] >= 1.0]
        sum_qualifying = round(sum(iv["duration"] for iv in qualifying_intervals), 2)
        intermittent_req = required_hours + 0.5

        if max_continuous >= required_hours:
            insolation_type = "CONTINUOUS"
            is_compliant = True
            color_hex = "#10b981"  # Изумрудный / зеленый
        elif allow_intermittent and len(qualifying_intervals) >= 2 and sum_qualifying >= intermittent_req:
            insolation_type = "INTERMITTENT_OK"
            is_compliant = True
            color_hex = "#06b6d4"  # Бирюзовый / циановый (прерывистая норма)
        elif max_continuous >= (required_hours - 0.5) or (allow_intermittent and sum_qualifying >= required_hours):
            insolation_type = "INTERMITTENT_FAIL"
            is_compliant = False
            color_hex = "#f59e0b"  # Янтарный / желтый (дефицит)
        else:
            insolation_type = "SHADED"
            is_compliant = False
            color_hex = "#ef4444"  # Красный (тень)

        return max_continuous, sum_qualifying, insolation_type, is_compliant, color_hex, intervals

    def _is_ray_blocked(
        self,
        x0: float,
        y0: float,
        z0: float,
        sx: float,
        sy: float,
        sz: float,
        obstacles: list[Any],
        current_footprint: Polygon,
    ) -> bool:
        """Быстрая 2D/3D проверка блокировки луча солнца окружающими телами с AABB-отсечением и параметрическим пересечением."""
        if sz <= 0.01:
            return True

        hyp = math.hypot(sx, sy)
        if hyp <= 1e-6:
            return False

        tan_elev = sz / hyp
        ray_dir_x = sx / hyp
        ray_dir_y = sy / hyp

        # Длина луча для проверки (до 250 м)
        max_dist = 250.0
        p_end_x = x0 + ray_dir_x * max_dist
        p_end_y = y0 + ray_dir_y * max_dist

        # AABB bounding box луча для быстрого отсечения препятствий
        ray_minx = min(x0, p_end_x)
        ray_miny = min(y0, p_end_y)
        ray_maxx = max(x0, p_end_x)
        ray_maxy = max(y0, p_end_y)

        ray_seg = None

        for item in obstacles:
            if len(item) == 4:
                obst_poly, obst_h, (o_minx, o_miny, o_maxx, o_maxy), edges = item
                if ray_maxx < o_minx or ray_minx > o_maxx or ray_maxy < o_miny or ray_miny > o_maxy:
                    continue
                if obst_poly is current_footprint:
                    continue
                if obst_h <= z0:
                    continue

                min_t = float("inf")
                for x1, y1, x2, y2, ex, ey in edges:
                    denom = ray_dir_x * ey - ray_dir_y * ex
                    if denom == 0.0:
                        continue
                    t = ((x1 - x0) * ey - (y1 - y0) * ex) / denom
                    u = ((x1 - x0) * ray_dir_y - (y1 - y0) * ray_dir_x) / denom
                    if 0.35 <= t <= max_dist and 0.0 <= u <= 1.0:
                        if t < min_t:
                            min_t = t

                if min_t < float("inf"):
                    ray_z_at_obst = z0 + min_t * tan_elev
                    if ray_z_at_obst < obst_h:
                        return True
                continue

            elif len(item) == 3:
                obst_poly, obst_h, (o_minx, o_miny, o_maxx, o_maxy) = item
                if ray_maxx < o_minx or ray_minx > o_maxx or ray_maxy < o_miny or ray_miny > o_maxy:
                    continue
            else:
                obst_poly, obst_h = item[0], item[1]

            # Игнорируем саму секцию, из стены которой исходит луч
            if obst_poly is current_footprint:
                continue

            if obst_h <= z0:
                continue

            if ray_seg is None:
                ray_seg = LineString([(x0, y0), (p_end_x, p_end_y)])

            # Быстрое пересечение 2D-луча с проекцией препятствия
            if obst_poly.intersects(ray_seg):
                inter = obst_poly.intersection(ray_seg)
                if inter.is_empty:
                    continue
                # Находим ближайшую точку входа луча в полигон
                dist_to_obst = Point(x0, y0).distance(inter)
                if dist_to_obst < 0.35:
                    continue  # Микроклиппинг у стены (фасад отнесен на 18 см от стены)

                # Высота луча над препятствием в точке входа
                ray_z_at_obst = z0 + dist_to_obst * tan_elev
                if ray_z_at_obst < obst_h:
                    return True  # Препятствие выше луча солнца -> тень!

        return False

    @staticmethod
    def _max_continuous_hours(timeline: list[bool], dt_hour: float) -> float:
        """Найти максимальный непрерывный интервал инсоляции (подряд идущие True)."""
        max_streak = 0
        cur_streak = 0
        for is_sun in timeline:
            if is_sun:
                cur_streak += 1
                if cur_streak > max_streak:
                    max_streak = cur_streak
            else:
                cur_streak = 0
        return max_streak * dt_hour
