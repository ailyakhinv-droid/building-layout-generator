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

        elif preset in ("cross_2x2", "cross", "grid"):
            lines.append(LineString([(minx - pad, cy), (maxx + pad, cy)]))
            lines.append(LineString([(cx, miny - pad), (cx, maxy + pad)]))

        return lines

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

        Returns:
            RoadSliceResult с суб-кварталами, геометрией асфальта, буферной зоны и метриками.
        """
        if not buildable_area or buildable_area.is_empty:
            return RoadSliceResult(sub_blocks=[])

        # 1. Сбор осевых линий
        centerlines: list[LineString] = []

        if road_lines:
            for item in road_lines:
                if isinstance(item, LineString):
                    if len(item.coords) >= 2:
                        centerlines.append(item)
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    try:
                        centerlines.append(LineString(item))
                    except Exception:
                        pass
                elif isinstance(item, dict) and "points" in item:
                    pts = item["points"]
                    if isinstance(pts, (list, tuple)) and len(pts) >= 2:
                        try:
                            centerlines.append(LineString(pts))
                        except Exception:
                            pass
        elif preset and preset != "none":
            centerlines = cls.create_preset_centerlines(
                site_boundary,
                preset=preset,
                pos_ratio=pos_ratio,
                pos_ratio_x=pos_ratio_x,
                pos_ratio_y=pos_ratio_y,
            )

        if not centerlines:
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
                roads_geojson={"type": "FeatureCollection", "features": []},
            )

        # 2. Построение коридоров:
        # - асфальтовое полотно (half_w)
        # - коридор вырезки зоны застройки (half_w + road_setback)
        half_w = max(2.0, road_width / 2.0)
        setback = max(0.0, float(road_setback))
        cut_half_w = half_w + setback

        asphalt_corridors = []
        cut_corridors = []
        total_len = 0.0

        for line in centerlines:
            total_len += line.length
            # cap_style=2 (flat / butt cap), join_style=2 (mitre)
            poly_asphalt = line.buffer(half_w, cap_style="flat", join_style="mitre")
            poly_cut = line.buffer(cut_half_w, cap_style="flat", join_style="mitre")
            asphalt_corridors.append(poly_asphalt)
            cut_corridors.append(poly_cut)

        roads_raw_union = unary_union(asphalt_corridors)
        cut_raw_union = unary_union(cut_corridors)

        # Ограничиваем контуры границей участка
        roads_polygon = roads_raw_union.intersection(site_boundary)
        cut_polygon = cut_raw_union.intersection(site_boundary)

        # Буферная полоса отступа (между краем асфальта и линией застройки)
        buffer_polygon = cut_polygon.difference(roads_polygon) if setback > 0.0 else None

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
                    "name": f"Техническая зона / отступ {setback} м",
                    "setback": setback,
                    "area": round(buffer_polygon.area, 1),
                },
            })

        # Осевые линии
        for i, line in enumerate(centerlines):
            features.append({
                "type": "Feature",
                "geometry": mapping(line.intersection(site_boundary.buffer(10.0))),
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
            centerlines=centerlines,
            roads_area_sqm=roads_area,
            buffer_area_sqm=buffer_area,
            roads_length_m=round(total_len, 1),
            road_setback=setback,
            roads_geojson=geojson,
        )
