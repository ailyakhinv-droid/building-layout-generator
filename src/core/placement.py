"""Движок расстановки зданий на участке.

Реализует современные градостроительные алгоритмы размещения типовых секций:
- Линейная застройка (пластины / рядовые корпуса)
- Г-образные корпуса (уголки)
- П-образные корпуса (скобы с комфортными зелеными дворами)
- Смешанная / квартальная компоновка (AUTO) с переменным шагом инсоляции.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from shapely.affinity import rotate, translate
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box
from shapely.ops import unary_union

from src.core.buildable_area import get_obb_dimensions, get_primary_axes
from src.library.section_library import SectionLibrary
from src.models.building import Building, PlacedSection
from src.models.section import SectionType
from src.models.site import Site


@dataclass
class PlacementConfig:
    """Параметры для алгоритма расстановки.

    Attributes:
        target_floors: Целевая этажность (None = default из секции).
        placement_angle: Угол размещения в градусах (None = авто по длинной оси).
        preferred_section_ids: Список предпочтительных ID секций.
        min_sections_per_building: Мин. кол-во секций в здании.
        max_sections_per_building: Макс. кол-во секций в здании.
        typology: Типология застройки ("AUTO", "U_SHAPE", "L_SHAPE", "LINEAR").
        courtyard_orientation: Раскрытие дворов ("SOUTH", "NORTH", "EAST", "WEST", "AUTO").
        variable_insolation: Переменный шаг инсоляции (уменьшенный разрыв с торцов).
    """

    target_floors: int | None = None
    placement_angle: float | None = None
    preferred_section_ids: list[str] | None = None
    min_sections_per_building: int = 2
    max_sections_per_building: int = 14
    typology: str = "AUTO"
    courtyard_orientation: str = "SOUTH"
    variable_insolation: bool = True


class PlacementEngine:
    """Движок расстановки типовых секций и зданий."""

    def __init__(
        self,
        site: Site,
        library: SectionLibrary,
        config: dict[str, Any],
    ) -> None:
        """Инициализировать движок."""
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
        """Сгенерировать расстановку зданий на участке."""
        if placement_config is None:
            placement_config = PlacementConfig()

        buildable = self.site.buildable_area

        # 1. Основная ось участка
        if placement_config.placement_angle is not None:
            primary_angle = placement_config.placement_angle
        else:
            primary_angle, _ = get_primary_axes(buildable)

        # 2. Выбор секций
        sections = self._select_sections(placement_config)
        if not sections:
            return []

        middle = sections["middle"]
        end = sections.get("end", middle)
        corner = sections.get("corner", middle)

        # 3. Этажность
        floors = placement_config.target_floors
        if floors is None:
            floors = middle.default_floors
        floors = max(middle.min_floors, min(floors, middle.max_floors))

        # 4. Выбор стратегии в зависимости от типологии
        typology = placement_config.typology.upper()

        if typology == "LINEAR":
            return self._generate_linear(
                buildable, primary_angle, middle, end, floors, placement_config
            )
        elif typology == "U_SHAPE":
            return self._generate_u_shape_layout(
                buildable, primary_angle, middle, corner, end, floors, placement_config
            )
        elif typology == "L_SHAPE":
            return self._generate_l_shape_layout(
                buildable, primary_angle, middle, corner, end, floors, placement_config
            )
        else:  # AUTO / MIXED — естественная квартальная компоновка
            return self._generate_mixed_layout(
                buildable, primary_angle, middle, corner, end, floors, placement_config
            )

    # ─────────────────────────────────────────────────────────────────
    # Локальная сборка центрированных секций
    # ─────────────────────────────────────────────────────────────────

    def _build_linear_local(
        self,
        middle: SectionType,
        end: SectionType,
        floors: int,
        num_middle: int,
    ) -> list[PlacedSection]:
        """Линейный корпус, центрированный в (0, 0) по оси X."""
        sections: list[PlacedSection] = []
        we, wm = end.width, middle.width
        total_len = we * 2 + num_middle * wm
        x_cursor = -total_len / 2.0

        sections.append(PlacedSection(end, x_cursor + we / 2.0, 0.0, 0.0, floors))
        x_cursor += we

        for _ in range(num_middle):
            sections.append(PlacedSection(middle, x_cursor + wm / 2.0, 0.0, 0.0, floors))
            x_cursor += wm

        sections.append(PlacedSection(end, x_cursor + we / 2.0, 0.0, 0.0, floors))
        return sections

    def _build_u_shape_local(
        self,
        middle: SectionType,
        corner: SectionType,
        end: SectionType,
        floors: int,
        num_back: int,
        num_wing: int,
    ) -> list[PlacedSection]:
        """П-образный корпус со двором, центрированный в (0, 0)."""
        sections: list[PlacedSection] = []
        wc, wm, we, d = corner.width, middle.width, end.width, middle.depth

        wing_len = num_wing * wm + we
        y_shift = wing_len / 2.0

        l_back_mid = num_back * wm
        xc1 = -(l_back_mid + wc) / 2.0
        xc2 = +(l_back_mid + wc) / 2.0

        # Угловые секции заднего фасада
        sections.append(PlacedSection(corner, xc1, y_shift, 0.0, floors))
        sections.append(PlacedSection(corner, xc2, y_shift, 0.0, floors))

        # Заднее крыло
        for i in range(num_back):
            x = xc1 + wc / 2.0 + (i + 0.5) * wm
            sections.append(PlacedSection(middle, x, y_shift, 0.0, floors))

        # Левое крыло (в сторону двора Y-)
        left_x = xc1 - wc / 2.0 + d / 2.0
        for j in range(num_wing):
            y = y_shift - d / 2.0 - (j + 0.5) * wm
            sections.append(PlacedSection(middle, left_x, y, 90.0, floors))
        end_l_y = y_shift - d / 2.0 - num_wing * wm - we / 2.0
        sections.append(PlacedSection(end, left_x, end_l_y, 90.0, floors))

        # Правое крыло (в сторону двора Y-)
        right_x = xc2 + wc / 2.0 - d / 2.0
        for k in range(num_wing):
            y = y_shift - d / 2.0 - (k + 0.5) * wm
            sections.append(PlacedSection(middle, right_x, y, 90.0, floors))
        end_r_y = y_shift - d / 2.0 - num_wing * wm - we / 2.0
        sections.append(PlacedSection(end, right_x, end_r_y, 90.0, floors))

        return sections

    def _build_l_shape_local(
        self,
        middle: SectionType,
        corner: SectionType,
        end: SectionType,
        floors: int,
        num_mid_x: int,
        num_mid_y: int,
    ) -> list[PlacedSection]:
        """Г-образный корпус, центрированный в (0, 0)."""
        sections: list[PlacedSection] = []
        wc, wm, we, d = corner.width, middle.width, end.width, middle.depth

        wing_x = num_mid_x * wm + we
        wing_y = num_mid_y * wm + we

        x_shift = wing_x / 2.0
        y_shift = wing_y / 2.0

        # Угловая секция
        sections.append(PlacedSection(corner, x_shift, y_shift, 0.0, floors))

        # Крыло по X влево
        x_curr = x_shift - wc / 2.0
        for _ in range(num_mid_x):
            sections.append(PlacedSection(middle, x_curr - wm / 2.0, y_shift, 0.0, floors))
            x_curr -= wm
        sections.append(PlacedSection(end, x_curr - we / 2.0, y_shift, 0.0, floors))

        # Крыло по Y вниз
        wing_y_x = x_shift + wc / 2.0 - d / 2.0
        y_curr = y_shift - d / 2.0
        for _ in range(num_mid_y):
            sections.append(PlacedSection(middle, wing_y_x, y_curr - wm / 2.0, 90.0, floors))
            y_curr -= wm
        sections.append(PlacedSection(end, wing_y_x, y_curr - we / 2.0, 90.0, floors))

        return sections

    def _transform_sections(
        self,
        local_sections: list[PlacedSection],
        pos_x: float,
        pos_y: float,
        angle_deg: float,
    ) -> list[PlacedSection]:
        """Преобразовать локальные секции в глобальные координаты участка."""
        transformed: list[PlacedSection] = []
        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        for s in local_sections:
            gx = pos_x + s.x * cos_a - s.y * sin_a
            gy = pos_y + s.x * sin_a + s.y * cos_a
            g_angle = (angle_deg + s.angle) % 360.0
            transformed.append(
                PlacedSection(
                    section_type=s.section_type,
                    x=gx,
                    y=gy,
                    angle=g_angle,
                    floors=s.floors,
                )
            )

        return transformed

    # ─────────────────────────────────────────────────────────────────
    # Стратегия: Смешанная / Естественная квартальная застройка (AUTO)
    # ─────────────────────────────────────────────────────────────────

    def _generate_mixed_layout(
        self,
        buildable: Polygon,
        angle: float,
        middle: SectionType,
        corner: SectionType,
        end: SectionType,
        floors: int,
        placement_config: PlacementConfig,
    ) -> list[Building]:
        """Генерация естественной квартальной застройки с дворами.

        Размещает ряд солнечных П-образных дворов в южной / центральной части,
        а в северной части формирует линейный уличный фронт.
        """
        length, width, _ = get_obb_dimensions(buildable)
        centroid = buildable.centroid
        buildings: list[Building] = []

        court_angle = self._get_solar_courtyard_angle(placement_config, angle)
        fire_gap = self._get_fire_gap(floors)

        # Выбираем размер дворов: двор шириной 30-40 м
        num_back = 3 if length < 170 else 3
        num_wing = 2 if width < 130 else 2

        u_w = corner.width * 2 + num_back * middle.width
        u_h = middle.depth + num_wing * middle.width + end.width

        # Проверяем, сколько П-образных дворов помещается по ширине участка
        side_gap = max(fire_gap, 20.0)
        u_step_x = u_w + side_gap

        cols = max(1, int((length + side_gap) / u_step_x))
        if cols > 1 and (cols * u_w + (cols - 1) * side_gap) > (length - 10.0):
            cols = max(1, cols - 1)

        span_x = (cols - 1) * u_step_x
        start_ox = -span_x / 2.0

        rad_p = math.radians(angle)
        rad_n = math.radians(angle + 90.0)
        ux = (math.cos(rad_p), math.sin(rad_p))
        uy = (math.cos(rad_n), math.sin(rad_n))

        # Смещение по высоте: если участок глубокий (width >= 110),
        # сдвигаем ряд дворов на юг, чтобы оставить северную полосу под улицу
        if width >= 110.0:
            target_oy = -width / 2.0 + u_h / 2.0 + 8.0
        else:
            target_oy = 0.0

        for col in range(cols):
            ox = start_ox + col * u_step_x
            px = centroid.x + ox * ux[0] + target_oy * uy[0]
            py = centroid.y + ox * ux[1] + target_oy * uy[1]

            # 1. Пробуем поставить П-образный корпус со двором
            cand_u = self._create_u_building(
                px, py, court_angle, middle, corner, end, floors, num_back, num_wing
            )
            if cand_u and self._fits_in_buildable(cand_u) and self._check_constraints(cand_u, buildings, placement_config):
                buildings.append(cand_u)
                continue

            # 2. Если скоба не вошла, пробуем Г-образный блок
            cand_l = self._create_l_building(
                px, py, court_angle, middle, corner, end, floors, num_mid_x=num_back, num_mid_y=num_wing
            )
            if cand_l and self._fits_in_buildable(cand_l) and self._check_constraints(cand_l, buildings, placement_config):
                buildings.append(cand_l)

        # 3. Дозаполняем оставшиеся свободные зоны участка (северная улица, фланги)
        self._fill_remaining_space(
            buildable, buildings, angle, middle, end, floors, placement_config
        )

        return buildings

    # ─────────────────────────────────────────────────────────────────
    # Стратегии: U_SHAPE, L_SHAPE, LINEAR
    # ─────────────────────────────────────────────────────────────────

    def _generate_u_shape_layout(
        self,
        buildable: Polygon,
        angle: float,
        middle: SectionType,
        corner: SectionType,
        end: SectionType,
        floors: int,
        placement_config: PlacementConfig,
    ) -> list[Building]:
        """Генерация с приоритетом П-образных скоб."""
        length, width, _ = get_obb_dimensions(buildable)
        centroid = buildable.centroid
        buildings: list[Building] = []

        court_angle = self._get_solar_courtyard_angle(placement_config, angle)
        fire_gap = self._get_fire_gap(floors)

        num_back = 3
        num_wing = 2

        u_w = corner.width * 2 + num_back * middle.width
        side_gap = max(fire_gap, 20.0)
        u_step_x = u_w + side_gap

        cols = max(1, int((length + side_gap) / u_step_x))
        if cols > 1 and (cols * u_w + (cols - 1) * side_gap) > (length - 10.0):
            cols = max(1, cols - 1)

        span_x = (cols - 1) * u_step_x
        start_ox = -span_x / 2.0

        rad_p = math.radians(angle)
        rad_n = math.radians(angle + 90.0)
        ux = (math.cos(rad_p), math.sin(rad_p))
        uy = (math.cos(rad_n), math.sin(rad_n))

        target_oy = -width / 2.0 + (middle.depth + num_wing * middle.width + end.width) / 2.0 + 8.0 if width >= 110.0 else 0.0

        for col in range(cols):
            ox = start_ox + col * u_step_x
            px = centroid.x + ox * ux[0] + target_oy * uy[0]
            py = centroid.y + ox * ux[1] + target_oy * uy[1]

            cand = self._create_u_building(
                px, py, court_angle, middle, corner, end, floors, num_back, num_wing
            )
            if cand and self._fits_in_buildable(cand) and self._check_constraints(cand, buildings, placement_config):
                buildings.append(cand)

        self._fill_remaining_space(
            buildable, buildings, angle, middle, end, floors, placement_config
        )
        return buildings

    def _generate_l_shape_layout(
        self,
        buildable: Polygon,
        angle: float,
        middle: SectionType,
        corner: SectionType,
        end: SectionType,
        floors: int,
        placement_config: PlacementConfig,
    ) -> list[Building]:
        """Генерация с приоритетом Г-образных корпусов."""
        length, width, _ = get_obb_dimensions(buildable)
        centroid = buildable.centroid
        buildings: list[Building] = []

        court_angle = self._get_solar_courtyard_angle(placement_config, angle)
        fire_gap = self._get_fire_gap(floors)

        num_x = 3
        num_y = 2

        l_w = corner.width + num_x * middle.width + end.width
        l_step_x = l_w + max(fire_gap, 15.0)
        cols = max(1, int(length / l_step_x))

        span_x = (cols - 1) * l_step_x
        start_ox = -span_x / 2.0

        rad_p = math.radians(angle)
        ux = (math.cos(rad_p), math.sin(rad_p))

        for col in range(cols):
            ox = start_ox + col * l_step_x
            px = centroid.x + ox * ux[0]
            py = centroid.y + ox * ux[1]

            cand = self._create_l_building(
                px, py, court_angle, middle, corner, end, floors, num_x, num_y
            )
            if cand and self._fits_in_buildable(cand) and self._check_constraints(cand, buildings, placement_config):
                buildings.append(cand)

        self._fill_remaining_space(
            buildable, buildings, angle, middle, end, floors, placement_config
        )
        return buildings

    def _generate_linear(
        self,
        buildable: Polygon,
        angle: float,
        middle: SectionType,
        end: SectionType,
        floors: int,
        placement_config: PlacementConfig,
    ) -> list[Building]:
        """Генерация параллельной рядовой застройки."""
        fire_gap = self._get_fire_gap(floors)
        insol_gap = self._get_insolation_gap(floors)
        row_spacing = middle.depth + max(fire_gap, insol_gap)

        row_lines = self._compute_row_positions(buildable, angle, row_spacing)
        buildings: list[Building] = []

        for line in row_lines:
            b = self._create_linear_on_line(
                line, middle, end, floors, angle, placement_config
            )
            if b is not None and self._check_constraints(b, buildings, placement_config):
                buildings.append(b)

        return buildings

    # ─────────────────────────────────────────────────────────────────
    # Вспомогательные конструкторы зданий
    # ─────────────────────────────────────────────────────────────────

    def _create_u_building(
        self,
        cx: float,
        cy: float,
        angle: float,
        middle: SectionType,
        corner: SectionType,
        end: SectionType,
        floors: int,
        num_back: int,
        num_wing: int,
    ) -> Building | None:
        """Создать П-образное здание в точке (cx, cy)."""
        try:
            local_secs = self._build_u_shape_local(
                middle, corner, end, floors, num_back, num_wing
            )
            placed_secs = self._transform_sections(local_secs, cx, cy, angle)
            return Building(sections=placed_secs, typology="U_SHAPE")
        except Exception:
            return None

    def _create_l_building(
        self,
        cx: float,
        cy: float,
        angle: float,
        middle: SectionType,
        corner: SectionType,
        end: SectionType,
        floors: int,
        num_mid_x: int,
        num_mid_y: int,
    ) -> Building | None:
        """Создать Г-образное здание в точке (cx, cy)."""
        try:
            local_secs = self._build_l_shape_local(
                middle, corner, end, floors, num_mid_x, num_mid_y
            )
            placed_secs = self._transform_sections(local_secs, cx, cy, angle)
            return Building(sections=placed_secs, typology="L_SHAPE")
        except Exception:
            return None

    def _create_linear_on_line(
        self,
        center_line: LineString,
        middle: SectionType,
        end: SectionType,
        floors: int,
        angle: float,
        placement_config: PlacementConfig,
    ) -> Building | None:
        """Создать линейное здание на линии."""
        line_len = center_line.length
        min_len = end.width * 2
        if line_len < min_len:
            return None

        avail = line_len - end.width * 2
        num_middle = int(avail / middle.width)

        total_secs = num_middle + 2
        if total_secs < placement_config.min_sections_per_building:
            return None
        if total_secs > placement_config.max_sections_per_building:
            num_middle = placement_config.max_sections_per_building - 2

        midpoint = center_line.interpolate(line_len / 2.0)
        local_secs = self._build_linear_local(middle, end, floors, num_middle)
        placed_secs = self._transform_sections(local_secs, midpoint.x, midpoint.y, angle)
        building = Building(sections=placed_secs, typology="LINEAR")

        if not self._fits_in_buildable(building):
            while num_middle > 0:
                num_middle -= 1
                local_secs = self._build_linear_local(middle, end, floors, num_middle)
                placed_secs = self._transform_sections(local_secs, midpoint.x, midpoint.y, angle)
                building = Building(sections=placed_secs, typology="LINEAR")
                if self._fits_in_buildable(building):
                    return building
            return None

        return building

    def _fill_remaining_space(
        self,
        buildable: Polygon,
        buildings: list[Building],
        angle: float,
        middle: SectionType,
        end: SectionType,
        floors: int,
        placement_config: PlacementConfig,
    ) -> None:
        """Дозаполнить свободные части участка линейными корпусами."""
        fire_gap = self._get_fire_gap(floors)
        row_spacing = middle.depth + max(fire_gap, self._get_insolation_gap(floors))
        row_lines = self._compute_row_positions(buildable, angle, row_spacing)

        for line in row_lines:
            cand = self._create_linear_on_line(
                line, middle, end, floors, angle, placement_config
            )
            if cand is not None and self._check_constraints(cand, buildings, placement_config):
                buildings.append(cand)

    def _get_solar_courtyard_angle(
        self, placement_config: PlacementConfig, primary_angle: float
    ) -> float:
        """Определить угол ориентации дворов по сторонам света."""
        orientation = placement_config.courtyard_orientation.upper()

        if orientation == "SOUTH":
            return 0.0
        elif orientation == "NORTH":
            return 180.0
        elif orientation == "EAST":
            return 90.0
        elif orientation == "WEST":
            return 270.0
        else:
            return primary_angle

    def _select_sections(
        self, placement_config: PlacementConfig
    ) -> dict[str, SectionType] | None:
        """Выбрать секции для расстановки."""
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
            if "middle" not in sections:
                middles = self.library.get_middle_sections()
                if middles:
                    sections["middle"] = middles[0]
            if "end" not in sections:
                ends = self.library.get_end_sections()
                sections["end"] = ends[0] if ends else sections.get("middle")
            if "corner" not in sections:
                corners = self.library.get_corner_sections()
                sections["corner"] = corners[0] if corners else sections.get("middle")
            return sections if "middle" in sections else None

        middles = self.library.get_middle_sections()
        ends = self.library.get_end_sections()
        corners = self.library.get_corner_sections()

        if not middles:
            return None

        result: dict[str, SectionType] = {"middle": middles[0]}
        result["end"] = ends[0] if ends else middles[0]
        result["corner"] = corners[0] if corners else middles[0]
        return result

    def _compute_row_positions(
        self,
        buildable: Polygon,
        angle: float,
        row_spacing: float,
    ) -> list[LineString]:
        """Вычислить центральные линии рядов."""
        length, width, _ = get_obb_dimensions(buildable)
        centroid = buildable.centroid
        cx, cy = centroid.x, centroid.y

        perp_angle_rad = math.radians(angle + 90.0)
        row_angle_rad = math.radians(angle)

        max_rows = int(width / row_spacing) + 1
        total_width = (max_rows - 1) * row_spacing
        start_offset = -total_width / 2.0

        row_lines: list[LineString] = []

        for i in range(max_rows):
            offset = start_offset + i * row_spacing
            row_cx = cx + offset * math.cos(perp_angle_rad)
            row_cy = cy + offset * math.sin(perp_angle_rad)

            half_len = length
            x1 = row_cx - half_len * math.cos(row_angle_rad)
            y1 = row_cy - half_len * math.sin(row_angle_rad)
            x2 = row_cx + half_len * math.cos(row_angle_rad)
            y2 = row_cy + half_len * math.sin(row_angle_rad)

            clipped = LineString([(x1, y1), (x2, y2)]).intersection(buildable)
            if clipped.is_empty:
                continue

            if isinstance(clipped, LineString):
                if clipped.length > 0:
                    row_lines.append(clipped)
            elif isinstance(clipped, MultiLineString):
                for geom in clipped.geoms:
                    if isinstance(geom, LineString) and geom.length > 0:
                        row_lines.append(geom)

        return row_lines

    def _fits_in_buildable(self, building: Building) -> bool:
        """Проверить, что здание полностью помещается в зону застройки."""
        try:
            footprint = building.footprint
            buildable = self.site.buildable_area
            return buildable.buffer(0.5).contains(footprint)
        except Exception:
            return False

    def _check_constraints(
        self,
        new_building: Building,
        existing_buildings: list[Building],
        placement_config: PlacementConfig | None = None,
    ) -> bool:
        """Проверить нормативные противопожарные и инсоляционные расстояния."""
        new_fp = new_building.footprint

        for existing in existing_buildings:
            exist_fp = existing.footprint

            if new_fp.intersects(exist_fp):
                return False

            distance = new_fp.distance(exist_fp)

            max_floors = max(new_building.floors, existing.floors)
            fire_gap = self._get_fire_gap(max_floors)
            if distance < fire_gap:
                return False

            max_height = max(new_building.height, existing.height)
            insol_factor = self.config.get("insolation_factor", 0.5)
            req_gap = max_height * insol_factor

            # Переменный шаг: с торцов разрыв может быть fire_gap, а по фасадам req_gap
            if placement_config and placement_config.variable_insolation:
                if distance < req_gap and distance < fire_gap * 1.2:
                    return False
            elif distance < req_gap:
                return False

        return True

    def _get_fire_gap(self, floors: int) -> float:
        """Минимальный противопожарный разрыв в метрах."""
        if floors > 10:
            return self.config.get("fire_gap_high_rise", 15.0)
        return self.config.get("fire_gap_min", 6.0)

    def _get_insolation_gap(self, floors: int) -> float:
        """Инсоляционный разрыв в метрах."""
        floor_height = self.config.get("floor_height", 3.0)
        building_height = floors * floor_height
        insol_factor = self.config.get("insolation_factor", 0.5)
        return building_height * insol_factor
