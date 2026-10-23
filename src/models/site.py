"""Модель земельного участка.

Содержит класс Site, описывающий границу участка,
красные линии и зону допустимой застройки.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union


@dataclass
class Site:
    """Земельный участок для размещения застройки.

    Attributes:
        boundary: Полигон границы участка.
        red_lines: Список красных линий (опционально).
        setbacks: Словарь с величинами отступов (ключ — название, значение — метры).
        buildable_area: Вычисленная зона допустимой застройки (изначально None).
    """

    boundary: Polygon
    red_lines: list[LineString] = field(default_factory=list)
    setbacks: dict[str, float] = field(default_factory=dict)
    base_offset: tuple[float, float] = (0.0, 0.0)
    geo_center: tuple[float, float] | None = None  # (latitude, longitude)
    cadastral_number: str | None = None
    address: str | None = None
    georef_source: str = ""
    rotation_deg: float = 0.0
    buildable_area: Polygon | None = field(default=None, init=False)

    @property
    def area(self) -> float:
        """Площадь участка в квадратных метрах."""
        return self.boundary.area

    def rotate(self, angle_deg: float) -> None:
        """Повернуть границы участка и красные линии вокруг геометрического центра.
        Положительный угол angle_deg соответствует вращению по часовой стрелке (↻) от севера на восток.
        """
        if angle_deg == 0.0:
            return
        import shapely.affinity
        minx, miny, maxx, maxy = self.boundary.bounds
        c = ((minx + maxx) / 2.0, (miny + maxy) / 2.0)
        # В Shapely положительный угол вращает против часовой стрелки,
        # поэтому для вращения по часовой стрелке (азимут, стороны света, UI) передаём -angle_deg.
        self.boundary = shapely.affinity.rotate(self.boundary, -angle_deg, origin=c)
        if self.red_lines:
            self.red_lines = [
                shapely.affinity.rotate(rl, -angle_deg, origin=c)
                for rl in self.red_lines
            ]
        new_rot = (self.rotation_deg + angle_deg) % 360.0
        while new_rot > 180.0:
            new_rot -= 360.0
        while new_rot < -180.0:
            new_rot += 360.0
        self.rotation_deg = new_rot

    def to_wgs84_boundary(self) -> Polygon | None:
        """Получить полигон границы в координатах WGS-84 (lon, lat), если задан geo_center."""
        if not self.geo_center:
            return None
        from src.core.geo_utils import transform_geometry_to_wgs84
        return transform_geometry_to_wgs84(self.boundary, self.geo_center[0], self.geo_center[1])

    def to_wgs84_buildable_area(self) -> Polygon | None:
        """Получить зону застройки в координатах WGS-84 (lon, lat), если задан geo_center."""
        if not self.geo_center or not self.buildable_area:
            return None
        from src.core.geo_utils import transform_geometry_to_wgs84
        return transform_geometry_to_wgs84(self.buildable_area, self.geo_center[0], self.geo_center[1])

    def to_wgs84_red_lines(self) -> list[LineString]:
        """Получить красные линии в координатах WGS-84 (lon, lat)."""
        if not self.geo_center or not self.red_lines:
            return []
        from src.core.geo_utils import transform_geometry_to_wgs84
        return [transform_geometry_to_wgs84(rl, self.geo_center[0], self.geo_center[1]) for rl in self.red_lines]

    def compute_buildable_area(
        self,
        boundary_setback: float = 6.0,
        red_line_setback: float = 5.0,
    ) -> Polygon:
        """Вычислить зону допустимой застройки.

        Алгоритм:
        1. Эрозия (отрицательный буфер) границы участка на величину boundary_setback.
        2. Для каждой красной линии создаётся буферная зона шириной red_line_setback,
           которая вычитается из допустимой зоны.

        Args:
            boundary_setback: Отступ от границы участка в метрах.
            red_line_setback: Отступ от красной линии в метрах.

        Returns:
            Полигон зоны допустимой застройки.

        Raises:
            ValueError: Если после применения отступов зона застройки пуста.
        """
        # Эрозия границы участка (отрицательный буфер)
        buildable = self.boundary.buffer(-boundary_setback)

        if buildable.is_empty:
            raise ValueError(
                f"Участок слишком мал для отступа {boundary_setback} м от границы. "
                f"Площадь участка: {self.area:.1f} м²."
            )

        # Вычитание буферных зон красных линий
        if self.red_lines:
            red_line_buffers = [
                line.buffer(red_line_setback) for line in self.red_lines
            ]
            red_line_union = unary_union(red_line_buffers)
            buildable = buildable.difference(red_line_union)

        if buildable.is_empty:
            raise ValueError(
                "После применения отступов от красных линий "
                "зона застройки оказалась пустой."
            )

        # Если результат — MultiPolygon, берём наибольший полигон
        if buildable.geom_type == "MultiPolygon":
            buildable = max(buildable.geoms, key=lambda g: g.area)

        self.buildable_area = buildable
        return buildable

    def __repr__(self) -> str:
        """Строковое представление участка."""
        return (
            f"Site(area={self.area:.1f} м², "
            f"red_lines={len(self.red_lines)}, "
            f"buildable={'да' if self.buildable_area else 'нет'})"
        )
