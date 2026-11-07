"""Модуль нарезки участка улично-дорожной сетью (Street-Driven Subdivision).

Позволяет автоматически или интерактивно нарезать территорию на отдельные урбан-блоки (кварталы)
по линиям дорог заданной ширины с гарантированным отступом застройки (road_setback)
и сохранением геометрической корректности (Shapely).
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


ROAD_CATEGORIES: dict[str, dict[str, Any]] = {
    "arterial": {
        "name": "Магистральная улица районного значения",
        "category": "arterial",
        "default_width": 22.0,
        "default_setback": 6.0,
        "lanes": "2+2 полосы (СП 42.13330)",
        "color": "#1e293b",
    },
    "district": {
        "name": "Внутриквартальная улица",
        "category": "district",
        "default_width": 15.0,
        "default_setback": 4.0,
        "lanes": "1+1 полоса (СП 42.13330)",
        "color": "#334155",
    },
    "local": {
        "name": "Местный / пожарный проезд",
        "category": "local",
        "default_width": 8.0,
        "default_setback": 3.0,
        "lanes": "Двухполосный проезд (СП 4.13130)",
        "color": "#475569",
    },
    "custom": {
        "name": "Пользовательская улица",
        "category": "custom",
        "default_width": 16.0,
        "default_setback": 4.0,
        "lanes": "Индивидуальная",
        "color": "#334155",
    },
}


@dataclass
class RoadSliceResult:
    """Результат нарезки территории дорожной сетью."""

    sub_blocks: list[Polygon] = field(default_factory=list)
    roads_polygon: Polygon | MultiPolygon | None = None
    buffer_polygon: Polygon | MultiPolygon | None = None
    centerlines: list[LineString] = field(default_factory=list)
    roads_area_sqm: float = 0.0
    buffer_area_sqm: float = 0.0
    roads_length_m: float = 0.0
    road_setback: float = 4.0
    roads_items: list[dict[str, Any]] = field(default_factory=list)
    roads_geojson: dict[str, Any] = field(default_factory=dict)


class RoadSlicer:
    """Движок моделирования улично-дорожной сети и нарезки участка."""

    DEFAULT_ROAD_WIDTH = 16.0
    DEFAULT_SETBACK = 4.0  # СП 42.13330 (3–6 м до линии застройки)
    MIN_BLOCK_AREA = 800.0  # Минимальная площадь жизнеспособного квартала в м²

    @classmethod
    def create_preset_centerlines(
        cls,
        boundary: Polygon,
        preset: str = "longitudinal",
        pos_ratio: float = 0.5,
        pos_ratio_x: float = 0.5,
        pos_ratio_y: float = 0.5,
    ) -> list[LineString]:
        """Сгенерировать осевые линии дорог по типовому пресету со смещением.

        Args:
            boundary: Контур участка или допустимой зоны застройки.
            preset: Название пресета:
                - 'none': без дорог
                - 'longitudinal': 1 сквозная продольная дорога (вдоль длинной стороны)
                - 'transverse': 1 сквозная поперечная дорога (вдоль короткой стороны)
                - 'cross_2x2': 2 пересекающиеся дороги (деление на 4 квартала)
            pos_ratio: Общее смещение (0.15 .. 0.85), default 0.5 (центр).
            pos_ratio_x: Смещение по оси X (для поперечной или сетки).
            pos_ratio_y: Смещение по оси Y (для продольной или сетки).
        """
        if not boundary or boundary.is_empty or preset in ("none", "", None):
            return []

        minx, miny, maxx, maxy = boundary.bounds
        width = maxx - minx
        height = maxy - miny
        pad = max(width, height) * 0.15  # Запас выхода линии за пределы для чистого реза

        def _clamp(v: float) -> float:
            return max(0.15, min(0.85, float(v)))

        rx = _clamp(pos_ratio_x if pos_ratio_x != 0.5 else pos_ratio)
        ry = _clamp(pos_ratio_y if pos_ratio_y != 0.5 else pos_ratio)

        cx = minx + width * rx
        cy = miny + height * ry

        lines: list[LineString] = []

        if preset == "longitudinal":
            if width >= height:
                # Длинная сторона вдоль X: горизонтальная дорога на высоте cy
                lines.append(LineString([(minx - pad, cy), (maxx + pad, cy)]))
            else:
                # Длинная сторона вдоль Y: вертикальная дорога на координате cx
                lines.append(LineString([(cx, miny - pad), (cx, maxy + pad)]))

        elif preset == "transverse":
            if width >= height:
                # Поперечная дорога перпендикулярно длинной оси (вертикальный разрез)
                lines.append(LineString([(cx, miny - pad), (cx, maxy + pad)]))
            else:
                # Поперечная дорога (горизонтальный разрез)
                lines.append(LineString([(minx - pad, cy), (maxx + pad, cy)]))

        elif preset in ("cross_2x2", "cross", "grid", "grid_2x2"):
            lines.append(LineString([(minx - pad, cy), (maxx + pad, cy)]))
            lines.append(LineString([(cx, miny - pad), (cx, maxy + pad)]))

        return lines

    @classmethod
    def extend_line_to_boundary(
        cls, line: LineString, site_boundary: Polygon
    ) -> LineString:
        """Продлить линию дороги в обе стороны за пределы участка для чистого сквозного разреза."""
        if not site_boundary or site_boundary.is_empty or len(line.coords) < 2:
            return line

        minx, miny, maxx, maxy = site_boundary.bounds
        diag = math.hypot(maxx - minx, maxy - miny) * 1.5
        coords = list(line.coords)

        # 1. Продление начального отрезка назад
        p0, p1 = coords[0], coords[1]
        dx0, dy0 = p0[0] - p1[0], p0[1] - p1[1]
        len0 = math.hypot(dx0, dy0)
        ext_p0 = (p0[0] + (dx0 / len0) * diag, p0[1] + (dy0 / len0) * diag) if len0 > 1e-6 else p0

        # 2. Продление конечного отрезка вперед
        pn_prev, pn = coords[-2], coords[-1]
        dxn, dyn = pn[0] - pn_prev[0], pn[1] - pn_prev[1]
        lenn = math.hypot(dxn, dyn)
        ext_pn = (pn[0] + (dxn / lenn) * diag, pn[1] + (dyn / lenn) * diag) if lenn > 1e-6 else pn

        return LineString([ext_p0] + coords[1:-1] + [ext_pn])

    @classmethod
    def snap_and_extend_boundary_ends(
        cls, line: LineString, site_boundary: Polygon, tolerance: float = 20.0
    ) -> LineString:
        """Продлить только те концы дороги, которые расположены близко к внешней меже участка.
        
        Это гарантирует чистый разрез строительного пятна у внешних въездов/выездов,
        но НЕ простреливает тупики, Т-образные узлы и 3-сторонние перекрестки внутри участка.
        """
        if not site_boundary or site_boundary.is_empty or len(line.coords) < 2:
            return line

        coords = list(line.coords)
        exterior = site_boundary.exterior
        ext_out = 20.0

        # Проверка начала (p0)
        p0 = Point(coords[0])
        ext_p0 = coords[0]
        if exterior.distance(p0) <= tolerance:
            dx0 = coords[0][0] - coords[1][0]
            dy0 = coords[0][1] - coords[1][1]
            l0 = math.hypot(dx0, dy0)
            if l0 > 1e-4:
                ext_p0 = (coords[0][0] + (dx0 / l0) * ext_out, coords[0][1] + (dy0 / l0) * ext_out)

        # Проверка конца (pn)
        pn = Point(coords[-1])
        ext_pn = coords[-1]
        if exterior.distance(pn) <= tolerance:
            dxn = coords[-1][0] - coords[-2][0]
            dyn = coords[-1][1] - coords[-2][1]
            ln = math.hypot(dxn, dyn)
            if ln > 1e-4:
                ext_pn = (coords[-1][0] + (dxn / ln) * ext_out, coords[-1][1] + (dyn / ln) * ext_out)

        return LineString([ext_p0] + coords[1:-1] + [ext_pn])

    @classmethod
    def slice_buildable_area(
        cls,
        buildable_area: Polygon | MultiPolygon,
        site_boundary: Polygon,
        road_lines: Sequence[LineString | list[tuple[float, float]] | dict[str, Any]] | None = None,
        preset: str = "none",
        road_width: float = DEFAULT_ROAD_WIDTH,
        road_setback: float = DEFAULT_SETBACK,
        pos_ratio: float = 0.5,
        pos_ratio_x: float = 0.5,
        pos_ratio_y: float = 0.5,
        min_block_area: float = MIN_BLOCK_AREA,
        extend_to_boundary: bool | None = None,
    ) -> RoadSliceResult:
        """Разрезать зону застройки дорожной сетью на урбан-блоки с отступом застройки.

        Args:
            buildable_area: Исходная зона допустимой застройки.
            site_boundary: Внешняя граница земельного участка.
            road_lines: Список пользовательских линий дорог (координаты или LineString).
            preset: Типовой пресет (если road_lines не задан).
            road_width: Ширина проезжей части/полосы отвода дороги в метрах.
            road_setback: Гарантированный отступ зданий от дороги в метрах (СП 42.13330).
            pos_ratio: Положение оси дороги относительно участка (0.15 .. 0.85).
            pos_ratio_x: Положение по оси X (для сетки и поперечных дорог).
            pos_ratio_y: Положение по оси Y (для сетки и продольных дорог).
            min_block_area: Минимальный порог площади для образования квартала.
            extend_to_boundary: Продлевать ли дороги сквозь весь участок. По умолчанию:
                False для пользовательских дорог (уважает тупики, Т-образные примыкания и перекрестки 3-х дорог),
                True для стандартных пресетов (сквозная сетка).

        Returns:
            RoadSliceResult с суб-кварталами, геометрией асфальта, буферной зоны и метриками.
        """
        is_custom = bool(road_lines)
        if extend_to_boundary is None:
            should_extend = False if is_custom else True
        else:
            should_extend = extend_to_boundary
        if not buildable_area or buildable_area.is_empty:
            return RoadSliceResult(sub_blocks=[])

        # 1. Сбор дорог и их параметров (ширина, отступ, категория)
        road_defs: list[dict[str, Any]] = []

        if road_lines:
            for idx, item in enumerate(road_lines):
                line = None
                width = road_width
                setback = road_setback
                category = "district"
                name = f"Улица {idx + 1}"

                if isinstance(item, LineString):
                    if len(item.coords) >= 2:
                        line = item
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    try:
                        line = LineString(item)
                    except Exception:
                        pass
                elif isinstance(item, dict):
                    pts = item.get("points")
                    if isinstance(pts, (list, tuple)) and len(pts) >= 2:
                        try:
                            line = LineString(pts)
                        except Exception:
                            pass
                    category = item.get("category", "district")
                    cat_info = ROAD_CATEGORIES.get(category, ROAD_CATEGORIES["district"])
                    width = float(item.get("width") or cat_info["default_width"])
                    setback = float(item.get("setback") if item.get("setback") is not None else cat_info["default_setback"])
                    name = item.get("name") or cat_info["name"]

                if line and len(line.coords) >= 2:
                    road_defs.append({
                        "line": line,
                        "width": width,
                        "setback": setback,
                        "category": category,
                        "name": name,
                    })
        elif preset and preset != "none":
            preset_lines = cls.create_preset_centerlines(
                site_boundary,
                preset=preset,
                pos_ratio=pos_ratio,
                pos_ratio_x=pos_ratio_x,
                pos_ratio_y=pos_ratio_y,
            )
            for idx, pl in enumerate(preset_lines):
                road_defs.append({
                    "line": pl,
                    "width": road_width,
                    "setback": road_setback,
                    "category": "district",
                    "name": f"Улица {idx + 1}",
                })

        if not road_defs:
            # Дороги отсутствуют — возвращаем исходную зону как единый квартал
            sub_blocks = [buildable_area] if isinstance(buildable_area, Polygon) else list(buildable_area.geoms)
            return RoadSliceResult(
                sub_blocks=[b for b in sub_blocks if b.area >= min_block_area],
                roads_polygon=None,
                buffer_polygon=None,
                centerlines=[],
                roads_area_sqm=0.0,
                buffer_area_sqm=0.0,
                roads_length_m=0.0,
                road_setback=road_setback,
                roads_items=[],
                roads_geojson={"type": "FeatureCollection", "features": []},
            )

        # 2. Построение коридоров:
        # - асфальтовое полотно (индивидуальный half_w)
        # - коридор вырезки зоны застройки (half_w + road_setback)
        asphalt_corridors = []
        cut_corridors = []
        clipped_centerlines: list[LineString] = []
        roads_items_metadata: list[dict[str, Any]] = []
        total_len = 0.0

        for rdef in road_defs:
            line = rdef["line"]
            r_w = rdef["width"]
            r_s = rdef["setback"]
            half_w = max(2.0, r_w / 2.0)
            cut_half_w = half_w + max(0.0, r_s)

            if should_extend and site_boundary and not site_boundary.is_empty:
                working_line = cls.extend_line_to_boundary(line, site_boundary)
            elif site_boundary and not site_boundary.is_empty:
                working_line = cls.snap_and_extend_boundary_ends(line, site_boundary, tolerance=20.0)
            else:
                working_line = line

            # Клипирование осевой линии границей участка
            r_len = 0.0
            if site_boundary and not site_boundary.is_empty:
                inter = working_line.intersection(site_boundary)
                if not inter.is_empty:
                    if isinstance(inter, LineString):
                        clipped_centerlines.append(inter)
                        r_len = inter.length
                    elif isinstance(inter, MultiLineString):
                        for g in inter.geoms:
                            clipped_centerlines.append(g)
                            r_len += g.length
                else:
                    clipped_centerlines.append(line)
                    r_len = line.length
            else:
                clipped_centerlines.append(line)
                r_len = line.length

            total_len += r_len

            # cap_style=2 (flat / butt cap), join_style=2 (mitre)
            poly_asphalt = working_line.buffer(half_w, cap_style="flat", join_style="mitre")
            poly_cut = working_line.buffer(cut_half_w, cap_style="flat", join_style="mitre")
            asphalt_corridors.append(poly_asphalt)
            cut_corridors.append(poly_cut)

            roads_items_metadata.append({
                "name": rdef["name"],
                "category": rdef["category"],
                "width": r_w,
                "setback": r_s,
                "length_m": round(r_len, 1),
                "points": list(line.coords),
            })

        roads_raw_union = unary_union(asphalt_corridors)
        cut_raw_union = unary_union(cut_corridors)

        # Ограничиваем контуры границей участка
        roads_polygon = roads_raw_union.intersection(site_boundary)
        cut_polygon = cut_raw_union.intersection(site_boundary)

        # Буферная полоса отступа (между краем асфальта и линией застройки)
        buffer_polygon = cut_polygon.difference(roads_polygon) if any(r["setback"] > 0 for r in road_defs) else None

        # 3. Разрезание зоны допустимой застройки с гарантированным отступом
        diff = buildable_area.difference(cut_raw_union)

        sub_blocks: list[Polygon] = []
        if isinstance(diff, Polygon):
            if diff.area >= min_block_area:
                sub_blocks.append(diff)
        elif isinstance(diff, MultiPolygon):
            for part in diff.geoms:
                if part.area >= min_block_area:
                    sub_blocks.append(part)

        # Если после разрезания блоки оказались меньше лимита, сохраняем исходную зону
        if not sub_blocks:
            sub_blocks = [buildable_area] if isinstance(buildable_area, Polygon) else list(buildable_area.geoms)

        # 4. Формирование GeoJSON для 3D/ГИС визуализации
        features = []

        # Асфальтовое полотно
        if roads_polygon and not roads_polygon.is_empty:
            features.append({
                "type": "Feature",
                "geometry": mapping(roads_polygon),
                "properties": {
                    "type": "internal_road",
                    "name": "Внутриквартальная улично-дорожная сеть",
                    "width": road_width,
                    "area": round(roads_polygon.area, 1),
                },
            })

        # Буферная зона / тротуар / озеленение вдоль дороги
        if buffer_polygon and not buffer_polygon.is_empty:
            features.append({
                "type": "Feature",
                "geometry": mapping(buffer_polygon),
                "properties": {
                    "type": "road_buffer",
                    "name": f"Техническая зона / отступ {road_setback} м",
                    "setback": road_setback,
                    "area": round(buffer_polygon.area, 1),
                },
            })

        # Осевые линии
        for i, line in enumerate(clipped_centerlines):
            features.append({
                "type": "Feature",
                "geometry": mapping(line),
                "properties": {
                    "type": "road_centerline",
                    "name": f"Ось улицы {i + 1}",
                },
            })

        geojson = {
            "type": "FeatureCollection",
            "features": features,
        }

        roads_area = round(roads_polygon.area, 1) if roads_polygon and not roads_polygon.is_empty else 0.0
        buffer_area = round(buffer_polygon.area, 1) if buffer_polygon and not buffer_polygon.is_empty else 0.0

        return RoadSliceResult(
            sub_blocks=sub_blocks,
            roads_polygon=roads_polygon,
            buffer_polygon=buffer_polygon,
            centerlines=clipped_centerlines,
            roads_area_sqm=roads_area,
            buffer_area_sqm=buffer_area,
            roads_length_m=round(total_len, 1),
            road_setback=road_setback,
            roads_items=roads_items_metadata,
            roads_geojson=geojson,
        )
