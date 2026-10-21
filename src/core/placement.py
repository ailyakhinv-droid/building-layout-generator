"""Движок расстановки зданий на участке.

Основной модуль генератора застройки. Реализует алгоритм
размещения типовых секций в цепочки (здания) внутри зоны
допустимой застройки с учётом нормативных ограничений.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import unary_union

from src.core.buildable_area import get_obb_dimensions, get_primary_axes
from src.models.building import Building, PlacedSection
from src.models.section import SectionType
from src.models.site import Site
from src.library.section_library import SectionLibrary


@dataclass
class PlacementConfig:
    """Параметры для алгоритма расстановки.

    Attributes:
        target_floors: Целевая этажность (None = default из секции).
        placement_angle: Угол размещения в градусах (None = авто).
        preferred_section_ids: Список предпочтительных ID секций.
        min_sections_per_building: Мин. кол-во секций в здании.
        max_sections_per_building: Макс. кол-во секций в здании.
    """
    target_floors: int | None = None
    placement_angle: float | None = None
    preferred_section_ids: list[str] | None = None
    min_sections_per_building: int = 2
    max_sections_per_building: int = 8


class PlacementEngine:
    """Движок расстановки зданий.

    Размещает здания (цепочки типовых секций) внутри зоны
    допустимой застройки параллельными рядами.
    """

    def __init__(
        self,
        site: Site,
        library: SectionLibrary,
        config: dict[str, Any],
    ) -> None:
        """Инициализировать движок.

        Args:
            site: Участок с вычисленной зоной застройки.
            library: Библиотека типовых секций.
            config: Нормативные параметры (из defaults.yaml).
        """
        self.site = site
        self.library = library
        self.config = config

        if site.buildable_area is None:
            raise ValueError(
                "Зона допустимой застройки не вычислена. "
                "Вызовите site.compute_buildable_area() перед расстановкой."
            )

    def generate(
        self,
        placement_config: PlacementConfig | None = None,
    ) -> list[Building]:
        """Сгенерировать расстановку зданий.

        Алгоритм:
        1. Определить основные оси участка
        2. Разбить зону застройки на полосы (ряды)
        3. В каждой полосе разместить здание (цепочку секций)
        4. Проверить все нормативные ограничения
        5. Вернуть список зданий

        Args:
            placement_config: Параметры расстановки (опционально).

        Returns:
            Список размещённых зданий.
        """
        if placement_config is None:
            placement_config = PlacementConfig()

        buildable = self.site.buildable_area

        # 1. Определяем направление размещения
        if placement_config.placement_angle is not None:
            primary_angle = placement_config.placement_angle
        else:
            primary_angle, _ = get_primary_axes(buildable)

        # 2. Выбираем секции
        sections = self._select_sections(placement_config)
        if not sections:
            return []

        middle = sections["middle"]
        end = sections["end"]

        # 3. Определяем этажность
        floors = placement_config.target_floors
        if floors is None:
            floors = middle.default_floors

        floors = max(middle.min_floors, min(floors, middle.max_floors))

        # 4. Вычисляем шаг рядов (глубина секции + пожарный разрыв)
        fire_gap = self._get_fire_gap(floors)
        insol_gap = self._get_insolation_gap(floors, middle)
        row_spacing = middle.depth + max(fire_gap, insol_gap)

        # 5. Генерируем ряды
        row_lines = self._compute_row_positions(buildable, primary_angle, row_spacing)

        # 6. Размещаем здания по рядам
        buildings: list[Building] = []

        for row_line in row_lines:
            building = self._place_building_along_line(
                row_line, middle, end, floors, primary_angle, placement_config
            )
            if building is not None:
                # Проверяем ограничения
                if self._check_constraints(building, buildings):
                    buildings.append(building)

        return buildings

    def _select_sections(
        self, placement_config: PlacementConfig
    ) -> dict[str, SectionType] | None:
        """Выбрать секции для расстановки.

        Returns:
            Словарь с ключами 'middle', 'end', 'corner' или None.
        """
        # Если указаны предпочтительные секции
        if placement_config.preferred_section_ids:
            sections = {}
            for sid in placement_config.preferred_section_ids:
                s = self.library.get_by_id(sid)
                if s:
                    if s.category == "MIDDLE":
                        sections["middle"] = s
                    elif s.category == "END":
                        sections["end"] = s
                    elif s.category == "CORNER":
                        sections["corner"] = s
            # Дополняем недостающие
            if "middle" not in sections:
                middles = self.library.get_middle_sections()
                if middles:
                    sections["middle"] = middles[0]
            if "end" not in sections:
                ends = self.library.get_end_sections()
                if ends:
                    sections["end"] = ends[0]
                elif "middle" in sections:
                    sections["end"] = sections["middle"]
            return sections if "middle" in sections else None

        # Автоматический выбор — берём первые доступные
        middles = self.library.get_middle_sections()
        ends = self.library.get_end_sections()
        corners = self.library.get_corner_sections()

        if not middles:
            return None

        result: dict[str, SectionType] = {"middle": middles[0]}

        if ends:
            result["end"] = ends[0]
        else:
            result["end"] = middles[0]

        if corners:
            result["corner"] = corners[0]

        return result

    def _compute_row_positions(
        self,
        buildable: Polygon,
        angle: float,
        row_spacing: float,
    ) -> list[LineString]:
        """Вычислить центральные линии рядов для размещения зданий.

        Создаёт параллельные линии с заданным шагом, обрезая их
        по границе зоны застройки.

        Args:
            buildable: Полигон зоны допустимой застройки.
            angle: Угол направления рядов в градусах.
            row_spacing: Расстояние между рядами в метрах.

        Returns:
            Список линий (центральные оси рядов).
        """
        # Получаем габариты зоны застройки
        length, width, _ = get_obb_dimensions(buildable)

        # Центр зоны застройки
        centroid = buildable.centroid
        cx, cy = centroid.x, centroid.y

        # Перпендикулярное направление (вдоль которого раскладываем ряды)
        perp_angle_rad = math.radians(angle + 90)

        # Направление ряда (вдоль которого размещаем секции)
        row_angle_rad = math.radians(angle)

        # Количество рядов
        max_rows = int(width / row_spacing) + 1

        # Смещение от центра для симметричного размещения
        total_width = (max_rows - 1) * row_spacing
        start_offset = -total_width / 2.0

        row_lines: list[LineString] = []

        for i in range(max_rows):
            offset = start_offset + i * row_spacing

            # Точка центра ряда
            row_cx = cx + offset * math.cos(perp_angle_rad)
            row_cy = cy + offset * math.sin(perp_angle_rad)

            # Создаём длинную линию вдоль направления ряда
            half_len = length
            x1 = row_cx - half_len * math.cos(row_angle_rad)
            y1 = row_cy - half_len * math.sin(row_angle_rad)
            x2 = row_cx + half_len * math.cos(row_angle_rad)
            y2 = row_cy + half_len * math.sin(row_angle_rad)

            full_line = LineString([(x1, y1), (x2, y2)])

            # Обрезаем по зоне застройки
            clipped = full_line.intersection(buildable)

            if clipped.is_empty:
                continue

            # Может вернуться MultiLineString — берём все сегменты
            if isinstance(clipped, LineString):
                if clipped.length > 0:
                    row_lines.append(clipped)
            elif isinstance(clipped, MultiLineString):
                for geom in clipped.geoms:
                    if isinstance(geom, LineString) and geom.length > 0:
                        row_lines.append(geom)

        return row_lines

    def _place_building_along_line(
        self,
        center_line: LineString,
        middle: SectionType,
        end: SectionType,
        floors: int,
        angle: float,
        placement_config: PlacementConfig,
    ) -> Building | None:
        """Разместить здание (цепочку секций) вдоль линии.

        Args:
            center_line: Центральная линия ряда.
            middle: Тип рядовой секции.
            end: Тип торцевой секции.
            floors: Количество этажей.
            angle: Угол поворота в градусах.
            placement_config: Параметры расстановки.

        Returns:
            Объект Building или None, если не помещается.
        """
        line_length = center_line.length

        # Минимальная длина здания: 2 торцевых секции
        min_length = end.width * 2
        if line_length < min_length:
            return None

        # Определяем количество рядовых секций
        available_length = line_length - end.width * 2
        num_middle = int(available_length / middle.width)

        # Ограничение по кол-ву секций
        total_sections = num_middle + 2  # + 2 торцевых
        if total_sections < placement_config.min_sections_per_building:
            return None
        if total_sections > placement_config.max_sections_per_building:
            num_middle = placement_config.max_sections_per_building - 2

        # Фактическая длина здания
        building_length = end.width + num_middle * middle.width + end.width

        # Центрируем здание на линии
        line_start = center_line.interpolate(0)
        line_mid = center_line.length / 2.0
        building_start = line_mid - building_length / 2.0

        if building_start < 0:
            building_start = 0

        # Направление вдоль линии
        angle_rad = math.radians(angle)
        dx = math.cos(angle_rad)
        dy = math.sin(angle_rad)

        # Начальная точка
        start_point = center_line.interpolate(building_start)
        sx, sy = start_point.x, start_point.y

        building = Building()
        cursor = 0.0  # Текущая позиция вдоль здания

        # Первая торцевая секция
        pos_x = sx + (cursor + end.width / 2) * dx
        pos_y = sy + (cursor + end.width / 2) * dy
        building.add_section(
            PlacedSection(
                section_type=end,
                x=pos_x,
                y=pos_y,
                angle=angle,
                floors=floors,
            )
        )
        cursor += end.width

        # Рядовые секции
        for _ in range(num_middle):
            pos_x = sx + (cursor + middle.width / 2) * dx
            pos_y = sy + (cursor + middle.width / 2) * dy
            building.add_section(
                PlacedSection(
                    section_type=middle,
                    x=pos_x,
                    y=pos_y,
                    angle=angle,
                    floors=floors,
                )
            )
            cursor += middle.width

        # Последняя торцевая секция
        pos_x = sx + (cursor + end.width / 2) * dx
        pos_y = sy + (cursor + end.width / 2) * dy
        building.add_section(
            PlacedSection(
                section_type=end,
                x=pos_x,
                y=pos_y,
                angle=angle,
                floors=floors,
            )
        )

        # Проверяем, что здание помещается в зону застройки
        if not self._fits_in_buildable(building):
            # Пробуем убрать секции с конца
            while len(building.sections) > placement_config.min_sections_per_building:
                building.sections.pop(-2)  # Убираем предпоследнюю (рядовую)
                # Пересчитываем позицию последней торцевой
                if len(building.sections) >= 2:
                    prev = building.sections[-2]
                    prev_half = prev.section_type.width / 2
                    end_half = end.width / 2
                    new_x = prev.x + (prev_half + end_half) * dx
                    new_y = prev.y + (prev_half + end_half) * dy
                    building.sections[-1] = PlacedSection(
                        section_type=end,
                        x=new_x,
                        y=new_y,
                        angle=angle,
                        floors=floors,
                    )

                if self._fits_in_buildable(building):
                    break
            else:
                return None

        return building

    def _fits_in_buildable(self, building: Building) -> bool:
        """Проверить, что здание помещается в зону застройки.

        Args:
            building: Проверяемое здание.

        Returns:
            True если здание полностью внутри зоны.
        """
        try:
            footprint = building.footprint
            buildable = self.site.buildable_area
            # Допускаем небольшой выход (0.5 м) из-за погрешностей
            return buildable.buffer(0.5).contains(footprint)
        except Exception:
            return False

    def _check_constraints(
        self,
        new_building: Building,
        existing_buildings: list[Building],
    ) -> bool:
        """Проверить нормативные ограничения для нового здания.

        Args:
            new_building: Новое здание для проверки.
            existing_buildings: Список уже размещённых зданий.

        Returns:
            True если все ограничения соблюдены.
        """
        new_footprint = new_building.footprint

        for existing in existing_buildings:
            existing_footprint = existing.footprint

            # Проверка пересечения пятен застройки
            if new_footprint.intersects(existing_footprint):
                return False

            # Расстояние между зданиями
            distance = new_footprint.distance(existing_footprint)

            # Пожарный разрыв
            max_floors = max(new_building.floors, existing.floors)
            fire_gap = self._get_fire_gap(max_floors)
            if distance < fire_gap:
                return False

            # Инсоляционный разрыв
            max_height = max(new_building.height, existing.height)
            insol_factor = self.config.get("insolation_factor", 0.5)
            insol_gap = max_height * insol_factor
            if distance < insol_gap:
                return False

        return True

    def _get_fire_gap(self, floors: int) -> float:
        """Получить требуемый пожарный разрыв по этажности.

        Args:
            floors: Количество этажей здания.

        Returns:
            Минимальный пожарный разрыв в метрах.
        """
        if floors > 10:
            return self.config.get("fire_gap_high_rise", 15.0)
        return self.config.get("fire_gap_min", 6.0)

    def _get_insolation_gap(self, floors: int, section: SectionType) -> float:
        """Вычислить инсоляционный разрыв.

        Args:
            floors: Количество этажей.
            section: Тип секции (для высоты).

        Returns:
            Минимальный инсоляционный разрыв в метрах.
        """
        floor_height = self.config.get("floor_height", 3.0)
        building_height = floors * floor_height
        insol_factor = self.config.get("insolation_factor", 0.5)
        return building_height * insol_factor
