"""Модуль нарезки участка улично-дорожной сетью (Street-Driven Subdivision).

Позволяет автоматически или интерактивно нарезать территорию на отдельные урбан-блоки (кварталы)
по линиям дорог заданной ширины с сохранением геометрической корректности (Shapely).
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
    centerlines: list[LineString] = field(default_factory=list)
    roads_area_sqm: float = 0.0
    roads_length_m: float = 0.0
    roads_geojson: dict[str, Any] = field(default_factory=dict)


class RoadSlicer:
    """Движок моделирования улично-дорожной сети и нарезки участка."""

    DEFAULT_ROAD_WIDTH = 16.0
    MIN_BLOCK_AREA = 800.0  # Минимальная площадь жизнеспособного квартала в м²

    @classmethod
    def create_preset_centerlines(
        cls,
        boundary: Polygon,
        preset: str = "longitudinal",
    ) -> list[LineString]:
        """Сгенерировать осевые линии дорог по типовому пресету.

        Args:
            boundary: Контур участка или допустимой зоны застройки.
            preset: Название пресета:
                - 'none': без дорог
                - 'longitudinal': 1 сквозная продольная дорога (вдоль длинной стороны)
                - 'transverse': 1 сквозная поперечная дорога (вдоль короткой стороны)
                - 'cross_2x2': 2 пересекающиеся дороги (деление на 4 квартала)
        """
        if not boundary or boundary.is_empty or preset in ("none", "", None):
            return []

        minx, miny, maxx, maxy = boundary.bounds
        width = maxx - minx
        height = maxy - miny
        pad = max(width, height) * 0.1  # Выход линии за пределы участка для чистого реза

        cx = (minx + maxx) / 2.0
        cy = (miny + maxy) / 2.0

        lines: list[LineString] = []

        if preset == "longitudinal":
            if width >= height:
                lines.append(LineString([(minx - pad, cy), (maxx + pad, cy)]))
            else:
                lines.append(LineString([(cx, miny - pad), (cx, maxy + pad)]))

        elif preset == "transverse":
            if width >= height:
                lines.append(LineString([(cx, miny - pad), (cx, maxy + pad)]))
            else:
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
        min_block_area: float = MIN_BLOCK_AREA,
    ) -> RoadSliceResult:
        """Разрезать зону застройки дорожной сетью на урбан-блоки.

        Args:
            buildable_area: Исходная зона допустимой застройки.
            site_boundary: Внешняя граница земельного участка.
            road_lines: Список пользовательских линий дорог (координаты или LineString).
            preset: Типовой пресет (если road_lines не задан).
            road_width: Ширина полосы отвода дороги в метрах (проезжая часть + тротуары).
            min_block_area: Минимальный порог площади для образования квартала.

        Returns:
            RoadSliceResult с суб-кварталами, геометрией дорог и метриками.
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
            centerlines = cls.create_preset_centerlines(site_boundary, preset=preset)

        if not centerlines:
            # Дороги отсутствуют — возвращаем исходную зону как единый квартал
            sub_blocks = [buildable_area] if isinstance(buildable_area, Polygon) else list(buildable_area.geoms)
            return RoadSliceResult(
                sub_blocks=[b for b in sub_blocks if b.area >= min_block_area],
                roads_polygon=None,
                centerlines=[],
                roads_area_sqm=0.0,
                roads_length_m=0.0,
                roads_geojson={"type": "FeatureCollection", "features": []},
            )

        # 2. Построение коридоров дорог (буфер ширины)
        half_w = max(4.0, road_width / 2.0)
        corridors = []
        total_len = 0.0

        for line in centerlines:
            # Клиппируем линию по расширенным границам участка
            total_len += line.length
            # cap_style=2 (flat / butt cap), join_style=2 (mitre)
            poly_buf = line.buffer(half_w, cap_style="flat", join_style="mitre")
            corridors.append(poly_buf)

        roads_raw_union = unary_union(corridors)
        # Ограничиваем дороги границей участка
        roads_polygon = roads_raw_union.intersection(site_boundary)

        # 3. Разрезание зоны застройки
        diff = buildable_area.difference(roads_raw_union)

        sub_blocks: list[Polygon] = []
        if isinstance(diff, Polygon):
            if diff.area >= min_block_area:
                sub_blocks.append(diff)
        elif isinstance(diff, MultiPolygon):
            for part in diff.geoms:
                if part.area >= min_block_area:
                    sub_blocks.append(part)

        # Если в результате разрезания все блоки оказались меньше лимита, сохраняем исходную
        if not sub_blocks:
            sub_blocks = [buildable_area] if isinstance(buildable_area, Polygon) else list(buildable_area.geoms)

        # 4. Формирование GeoJSON для 3D/ГИС визуализации
        features = []
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

        return RoadSliceResult(
            sub_blocks=sub_blocks,
            roads_polygon=roads_polygon,
            centerlines=centerlines,
            roads_area_sqm=round(roads_polygon.area, 1) if roads_polygon else 0.0,
            roads_length_m=round(total_len, 1),
            roads_geojson=geojson,
        )
