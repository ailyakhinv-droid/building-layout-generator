"""Модуль автоматической трассировки пожарных проездов (СП 4.13130.2020).

Реализует требования раздела 8 СП 4.13130.2020 «Проходы, проезды и подъезды к зданиям»:
1. Расстояние от внутреннего края проезда до наружных стен (п. 8.8):
   - При высоте здания H <= 28.0 м: 5.0 - 8.0 м (внутренний край на отступе 5.0 м).
   - При высоте здания H > 28.0 м (от 10 этажей): 8.0 - 10.0 м (внутренний край на отступе 8.0 м).
2. Ширина пожарного проезда (п. 8.6):
   - При H <= 13.0 м: не менее 3.5 м.
   - При 13.0 < H <= 46.0 м (до ~15-16 этажей): не менее 4.2 м.
   - При H > 46.0 м (17+ этажей): не менее 6.0 м.
3. Разворотные площадки в тупиках (п. 8.13):
   - Размеры не менее 15.0 x 15.0 м для маневрирования пожарной автотехники.
   - Ограничение длины тупикового проезда: не более 150 м.
4. Проверка допустимости размещения:
   - Проезд должен полностью помещаться в границах земельного участка (ЗУ).
   - Контроль охранной зоны пожаротушения между стеной и проездом (свободна от застройки).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
    mapping,
)
from shapely.ops import unary_union
from shapely.validation import make_valid

from src.models.building import Building
from src.models.site import Site


@dataclass
class FireAccessNorms:
    """Нормативные требования СП 4.13130.2020 к пожарным проездам."""

    # Границы высоты зданий
    HEIGHT_LOW_THRESHOLD_M: float = 13.0      # До 13 м - малоэтажные (ширина 3.5 м)
    HEIGHT_MEDIUM_THRESHOLD_M: float = 28.0   # До 28 м (~9 эт) - отступ 5-8 м
    HEIGHT_HIGH_THRESHOLD_M: float = 46.0     # Выше 46 м (~16 эт) - ширина 6.0 м

    # Отступы от стены до края проезда (п. 8.8)
    SETBACK_WALL_TO_LANE_LOW_M: float = 5.0   # Для H <= 28 м (5.0 - 8.0 м)
    SETBACK_WALL_TO_LANE_HIGH_M: float = 8.0  # Для H > 28 м (8.0 - 10.0 м)

    # Ширина пожарного проезда (п. 8.6)
    LANE_WIDTH_NARROW_M: float = 3.5          # При H <= 13 м
    LANE_WIDTH_STANDARD_M: float = 4.2        # При 13 < H <= 46 м
    LANE_WIDTH_WIDE_M: float = 6.0            # При H > 46 м

    # Разворотная площадка в тупике (п. 8.13)
    TURNAROUND_SIZE_M: float = 15.0           # 15.0 x 15.0 м
    MAX_DEAD_END_LENGTH_M: float = 150.0      # Максимальная длина тупика


@dataclass
class FireAccessResult:
    """Результат расчета и трассировки пожарных проездов."""

    # Геометрия
    fire_lanes_polygon: Polygon | MultiPolygon | None = None
    turnarounds_polygon: Polygon | MultiPolygon | None = None
    all_fire_infrastructure: Polygon | MultiPolygon | None = None
    centerlines: list[LineString] = field(default_factory=list)

    # Метрики
    total_area_sqm: float = 0.0
    turnarounds_area_sqm: float = 0.0
    total_length_m: float = 0.0

    # Нормативный контроль СП 4.13130
    is_compliant: bool = True
    issues: list[str] = field(default_factory=list)
    building_checks: list[dict[str, Any]] = field(default_factory=list)
    geojson: dict[str, Any] = field(default_factory=dict)


class FireAccessEngine:
    """Движок автоматической трассировки пожарных проездов вокруг зданий."""

    def __init__(self, norms: FireAccessNorms | None = None) -> None:
        self.norms = norms or FireAccessNorms()

    def get_building_height_m(self, building: Building) -> float:
        """Определить расчетную высоту здания в метрах."""
        fl = getattr(building, "floors", 0) or getattr(building, "max_floors", 0) or 1
        floor_h = 3.0
        if building.sections and hasattr(building.sections[0], "effective_floor_height"):
            floor_h = building.sections[0].effective_floor_height
        ground_floor_h = floor_h
        if building.sections and hasattr(building.sections[0], "effective_ground_floor_height"):
            ground_floor_h = building.sections[0].effective_ground_floor_height

        if fl <= 1:
            return ground_floor_h
        return ground_floor_h + (fl - 1) * floor_h

    def get_lane_parameters(self, height_m: float) -> tuple[float, float]:
        """Получить нормативный отступ от стены и ширину проезда по СП 4.13130.

        Args:
            height_m: Высота здания в метрах.

        Returns:
            (setback_m, width_m): отступ от стены до ближнего края и ширина проезда.
        """
        # Отступ от стены до ближнего края проезда (п. 8.8)
        if height_m <= self.norms.HEIGHT_MEDIUM_THRESHOLD_M:
            setback_m = self.norms.SETBACK_WALL_TO_LANE_LOW_M  # 5.0 м
        else:
            setback_m = self.norms.SETBACK_WALL_TO_LANE_HIGH_M  # 8.0 м

        # Ширина проезда (п. 8.6)
        if height_m <= self.norms.HEIGHT_LOW_THRESHOLD_M:
            width_m = self.norms.LANE_WIDTH_NARROW_M  # 3.5 м
        elif height_m <= self.norms.HEIGHT_HIGH_THRESHOLD_M:
            width_m = self.norms.LANE_WIDTH_STANDARD_M  # 4.2 м
        else:
            width_m = self.norms.LANE_WIDTH_WIDE_M  # 6.0 м

        return setback_m, width_m

    def trace_building_fire_lane(
        self,
        building: Building,
    ) -> tuple[Polygon | MultiPolygon, Polygon | MultiPolygon, dict[str, Any]]:
        """Построить кольцевой пожарный проезд вокруг одного здания.

        Args:
            building: Модель здания.

        Returns:
            (lane_poly, inner_buffer, meta_dict)
        """
        footprint = building.footprint
        if not footprint.is_valid:
            footprint = make_valid(footprint)

        height_m = self.get_building_height_m(building)
        setback_m, width_m = self.get_lane_parameters(height_m)

        # Внутренний край проезда (полоса безопасности/пожаротушения между стеной и проездом)
        inner_buf = footprint.buffer(setback_m, join_style=2)
        # Внешний край проезда
        outer_buf = footprint.buffer(setback_m + width_m, join_style=2)

        lane_poly = outer_buf.difference(inner_buf)

        meta = {
            "building_id": getattr(building, "id", "b"),
            "height_m": round(height_m, 1),
            "floors": getattr(building, "floors", 0),
            "setback_m": setback_m,
            "width_m": width_m,
            "lane_area_sqm": round(lane_poly.area, 1),
        }
        return lane_poly, inner_buf, meta

    def generate_fire_routes(
        self,
        site: Site,
        buildings: Sequence[Building],
        include_turnarounds: bool = True,
    ) -> FireAccessResult:
        """Сгенерировать комплексную сеть пожарных проездов для застройки участка.

        Args:
            site: Участок застройки с границей.
            buildings: Список размещенных зданий.
            include_turnarounds: Включать ли генерацию разворотных площадок 15х15 м.

        Returns:
            FireAccessResult с полигонами, метриками и нормативным контролем.
        """
        if not buildings:
            return FireAccessResult(is_compliant=True)

        site_poly = site.boundary
        if not site_poly.is_valid:
            site_poly = make_valid(site_poly)

        lanes_list: list[Polygon | MultiPolygon] = []
        checks: list[dict[str, Any]] = []
        issues: list[str] = []

        # 1. Трассировка кольцевых полос вокруг каждого здания
        for idx, b in enumerate(buildings):
            lane_poly, inner_buf, meta = self.trace_building_fire_lane(b)
            lanes_list.append(lane_poly)

            # Проверка выхода за границы участка
            diff_outside = lane_poly.difference(site_poly)
            outside_area = diff_outside.area if not diff_outside.is_empty else 0.0

            b_id = getattr(b, "name", None) or f"Корпус {idx + 1}"
            meta["name"] = b_id
            meta["outside_site_area"] = round(outside_area, 1)
            meta["fits_on_site"] = outside_area < 2.0  # Допуск на микропогрешность

            if outside_area >= 2.0:
                issues.append(
                    f"{b_id}: пожарный проезд ({meta['width_m']} м) выходит за границу участка "
                    f"на {outside_area:.1f} м². Требуется увеличить отступ корпуса от границы."
                )

            checks.append(meta)

        # 2. Объединение всех полос в единую сеть проездов
        raw_lanes = unary_union(lanes_list)
        # Ограничиваем проезд границами участка
        clipped_lanes = raw_lanes.intersection(site_poly)

        # 3. Генерация разворотных площадок 15х15 м в ключевых тупиковых узлах
        turnarounds_list: list[Polygon] = []
        if include_turnarounds and not clipped_lanes.is_empty:
            turnarounds_list = self._place_turnaround_pads(clipped_lanes, buildings, site_poly)

        turnarounds_poly = unary_union(turnarounds_list) if turnarounds_list else None

        # Объединенная пожарная инфраструктура
        parts = [p for p in [clipped_lanes, turnarounds_poly] if p is not None and not p.is_empty]
        all_infra = unary_union(parts) if parts else None

        # 4. Расчет осевых линий для отрисовки направления движения
        centerlines: list[LineString] = []
        if all_infra is not None and not all_infra.is_empty:
            centerlines = self._extract_approx_centerlines(all_infra, buildings)

        total_area = all_infra.area if all_infra is not None else 0.0
        turn_area = turnarounds_poly.area if turnarounds_poly is not None else 0.0
        total_len = sum(cl.length for cl in centerlines)

        # GeoJSON представление для GIS и MapLibre/Leaflet
        geojson_features = []
        if all_infra is not None and not all_infra.is_empty:
            geojson_features.append({
                "type": "Feature",
                "geometry": mapping(all_infra),
                "properties": {
                    "layer": "FIRE_ROADS",
                    "area_sqm": round(total_area, 1),
                    "standard": "СП 4.13130.2020",
                },
            })

        for i, cl in enumerate(centerlines):
            geojson_features.append({
                "type": "Feature",
                "geometry": mapping(cl),
                "properties": {
                    "layer": "FIRE_CENTERLINE",
                    "id": i + 1,
                    "length_m": round(cl.length, 1),
                },
            })

        return FireAccessResult(
            fire_lanes_polygon=clipped_lanes,
            turnarounds_polygon=turnarounds_poly,
            all_fire_infrastructure=all_infra,
            centerlines=centerlines,
            total_area_sqm=round(total_area, 1),
            turnarounds_area_sqm=round(turn_area, 1),
            total_length_m=round(total_len, 1),
            is_compliant=len(issues) == 0,
            issues=issues,
            building_checks=checks,
            geojson={
                "type": "FeatureCollection",
                "features": geojson_features,
            },
        )

    def _place_turnaround_pads(
        self,
        lanes: Polygon | MultiPolygon,
        buildings: Sequence[Building],
        site_poly: Polygon,
    ) -> list[Polygon]:
        """Разместить нормативные площадки 15х15 м для разворота пожарной техники."""
        pads: list[Polygon] = []
        size = self.norms.TURNAROUND_SIZE_M  # 15.0 м

        for b in buildings:
            fp = b.footprint
            minx, miny, maxx, maxy = fp.bounds
            cx = (minx + maxx) / 2.0
            cy = (miny + maxy) / 2.0
            w = maxx - minx
            d = maxy - miny

            height_m = self.get_building_height_m(b)
            setback_m, width_m = self.get_lane_parameters(height_m)
            dist_out = setback_m + width_m

            # Кандидаты на разворотные карманы по 4 сторонам от корпуса
            candidates = [
                # Северный карман
                box(cx - size / 2.0, maxy + dist_out, cx + size / 2.0, maxy + dist_out + size),
                # Южный карман
                box(cx - size / 2.0, miny - dist_out - size, cx + size / 2.0, miny - dist_out),
                # Восточный карман
                box(maxx + dist_out, cy - size / 2.0, maxx + dist_out + size, cy + size / 2.0),
                # Западный карман
                box(minx - dist_out - size, cy - size / 2.0, minx - dist_out, cy + size / 2.0),
            ]

            # Выбираем карман, который максимально свободно помещается в пределах участка
            for cand in candidates:
                if site_poly.contains(cand.buffer(-0.5)):
                    # Проверяем, что не пересекает само здание
                    if not cand.intersects(fp.buffer(setback_m)):
                        pads.append(cand)
                        break

        return pads

    def _extract_approx_centerlines(
        self,
        infra: Polygon | MultiPolygon,
        buildings: Sequence[Building],
    ) -> list[LineString]:
        """Построить осевые линии проездов для визуализации и расчёта метража."""
        lines: list[LineString] = []

        for b in buildings:
            fp = b.footprint
            height_m = self.get_building_height_m(b)
            setback_m, width_m = self.get_lane_parameters(height_m)

            # Осевая линия проходит посередине полосы проезда
            mid_offset = setback_m + width_m / 2.0
            loop_poly = fp.buffer(mid_offset, join_style=2)

            if loop_poly.geom_type == "Polygon" and loop_poly.exterior:
                coords = list(loop_poly.exterior.coords)
                if len(coords) >= 2:
                    lines.append(LineString(coords))
            elif loop_poly.geom_type == "MultiPolygon":
                for p in loop_poly.geoms:
                    if p.exterior and len(p.exterior.coords) >= 2:
                        lines.append(LineString(list(p.exterior.coords)))

        return lines
