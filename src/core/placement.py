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
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, box
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
        cascade_floors: Каскадное понижение этажности к югу (дворам).
        asymmetric_wings: Асимметричная длина крыльев (живой силуэт, раскрытие к свету).
        min_wing_floors: Минимальная этажность южных торцов/крыльев.
    """

    target_floors: int | None = None
    placement_angle: float | None = None
    preferred_section_ids: list[str] | None = None
    min_sections_per_building: int = 2
    max_sections_per_building: int = 14
    typology: str = "AUTO"
    courtyard_orientation: str = "SOUTH"
    variable_insolation: bool = True
    cascade_floors: bool = True
    asymmetric_wings: bool = True
    min_wing_floors: int = 8
    floor_height: float = 3.0
    ground_floor_height: float | None = None
    max_building_height_m: float | None = None


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
        self._current_floor_height: float = float(config.get("floor_height", 3.0))
        self._current_ground_floor_height: float | None = config.get("ground_floor_height")
        self._max_building_height_m: float | None = config.get("max_building_height_m")

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

        if placement_config.floor_height is not None:
            self._current_floor_height = float(placement_config.floor_height)
        else:
            self._current_floor_height = float(self.config.get("floor_height", 3.0))

        if placement_config.ground_floor_height is not None:
            self._current_ground_floor_height = float(placement_config.ground_floor_height)
        else:
            self._current_ground_floor_height = self.config.get("ground_floor_height")

        self._max_building_height_m = (
            placement_config.max_building_height_m
            if placement_config.max_building_height_m is not None
            else self.config.get("max_building_height_m")
        )

        max_floors_from_h = None
        if self._max_building_height_m and self._max_building_height_m > 0:
            ground_h = (
                self._current_ground_floor_height
                if self._current_ground_floor_height is not None
                else float(self.config.get("ground_floor_height", self._current_floor_height))
            )
            extra_first = max(0.0, ground_h - self._current_floor_height)
            max_floors_from_h = max(
                1,
                int((self._max_building_height_m - extra_first) // self._current_floor_height),
            )
        self._max_floors_from_h = max_floors_from_h

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
        if max_floors_from_h is not None:
            floors = min(floors, max_floors_from_h)
        floors = max(middle.min_floors, min(floors, middle.max_floors))
        if max_floors_from_h is not None:
            floors = min(floors, max_floors_from_h)

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

    def _clamp_floors(self, sec: SectionType, req_floors: int) -> int:
        """Ограничить этажность секции с учетом ее диапазона и предельной высоты."""
        fl = max(sec.min_floors, min(req_floors, sec.max_floors))
        max_h_fl = getattr(self, "_max_floors_from_h", None)
        if max_h_fl is not None:
            fl = min(fl, max_h_fl)
        return max(1, fl)

    def _build_linear_local(
        self,
        middle: SectionType,
        end: SectionType,
        floors: int,
        num_middle: int,
        cascade_floors: bool = False,
        min_wing_floors: int = 8,
    ) -> list[PlacedSection]:
        """Линейный корпус, центрированный в (0, 0) по оси X, без наложений."""
        sections: list[PlacedSection] = []
        num_total = num_middle + 2

        # Расчет этажности по позициям
        floor_list = []
        for idx in range(num_total):
            if cascade_floors and floors > min_wing_floors:
                # Силуэт: центр на целевой высоте, концы каскадно понижаются
                dist = abs(idx - (num_total - 1) / 2.0) / max(1.0, (num_total - 1) / 2.0)
                fl = round(floors - dist * (floors - min_wing_floors))
                floor_list.append(max(min_wing_floors, min(floors, fl)))
            else:
                floor_list.append(floors)

        # 1. Первая торцевая секция
        fl_end1 = floor_list[0]
        sec_end1 = (
            self._find_best_section(self.library.get_end_sections(), fl_end1)
            if cascade_floors else end
        ) or end
        fl_end1 = self._clamp_floors(sec_end1, fl_end1)

        # 2. Рядовые секции
        mid_secs = []
        for i in range(num_middle):
            fl_m = floor_list[i + 1]
            sec_m = (
                self._find_best_section(self.library.get_middle_sections(), fl_m)
                if cascade_floors else middle
            ) or middle
            fl_m = self._clamp_floors(sec_m, fl_m)
            mid_secs.append((sec_m, fl_m))

        # 3. Вторая торцевая секция
        fl_end2 = floor_list[-1]
        sec_end2 = (
            self._find_best_section(self.library.get_end_sections(), fl_end2)
            if cascade_floors else end
        ) or end
        fl_end2 = self._clamp_floors(sec_end2, fl_end2)

        # Выстраиваем цепочку вдоль оси X
        x_curr = 0.0
        sections.append(PlacedSection(sec_end1, x_curr + sec_end1.width / 2.0, 0.0, 0.0, fl_end1))
        x_curr += sec_end1.width

        for sec_m, fl_m in mid_secs:
            sections.append(PlacedSection(sec_m, x_curr + sec_m.width / 2.0, 0.0, 0.0, fl_m))
            x_curr += sec_m.width

        sections.append(PlacedSection(sec_end2, x_curr + sec_end2.width / 2.0, 0.0, 0.0, fl_end2))
        x_curr += sec_end2.width

        # Центрирование
        shift_x = x_curr / 2.0
        return [
            PlacedSection(s.section_type, s.x - shift_x, s.y, s.angle, s.floors, is_flipped=s.is_flipped)
            for s in sections
        ]

    def _build_u_shape_local(
        self,
        middle: SectionType,
        corner: SectionType,
        end: SectionType,
        floors: int,
        num_back: int,
        num_wing_left: int,
        num_wing_right: int,
        cascade_floors: bool = True,
        min_wing_floors: int = 8,
    ) -> list[PlacedSection]:
        """П-образный корпус со двором, центрированный в (0, 0), без наложений секций."""
        sections: list[PlacedSection] = []

        # 1. Заднее крыло (основание скобы, северная часть)
        fl_back = floors
        if cascade_floors and floors > min_wing_floors:
            sec_back = self._find_best_section(self.library.get_middle_sections(), fl_back) or middle
        else:
            sec_back = middle
        fl_back = self._clamp_floors(sec_back, fl_back)
        wm_back = sec_back.width
        dm_back = sec_back.depth

        # Угловые секции
        sec_cor_l = corner
        sec_cor_r = corner
        fl_cor_l = self._clamp_floors(sec_cor_l, floors)
        fl_cor_r = self._clamp_floors(sec_cor_r, floors)
        wc_l, dc_l = sec_cor_l.width, sec_cor_l.depth
        wc_r, dc_r = sec_cor_r.width, sec_cor_r.depth

        # Координаты основания:
        xc1 = wc_l / 2.0
        yc1 = -dc_l / 2.0
        sections.append(PlacedSection(sec_cor_l, xc1, yc1, 0.0, fl_cor_l, is_flipped=False))

        x_back_start = wc_l
        for i in range(num_back):
            xm = x_back_start + (i + 0.5) * wm_back
            ym = -dm_back / 2.0
            sections.append(PlacedSection(sec_back, xm, ym, 0.0, fl_back))

        x_back_end = x_back_start + num_back * wm_back

        xc2 = x_back_end + wc_r / 2.0
        yc2 = -dc_r / 2.0
        sections.append(PlacedSection(sec_cor_r, xc2, yc2, 0.0, fl_cor_r, is_flipped=True))

        x_right_outer = x_back_end + wc_r

        # 2. Левое крыло (в сторону юга -Y)
        K_l = num_wing_left + 1
        y_curr_l = -dc_l
        for j in range(num_wing_left):
            if cascade_floors and floors > min_wing_floors:
                step_ratio = (j + 1) / K_l
                fl_j = round(floors - step_ratio * (floors - min_wing_floors))
                sec_j = self._find_best_section(self.library.get_middle_sections(), fl_j) or middle
            else:
                sec_j = middle
                fl_j = floors
            fl_j = self._clamp_floors(sec_j, fl_j)

            xj = sec_j.depth / 2.0
            yj = y_curr_l - sec_j.width / 2.0
            sections.append(PlacedSection(sec_j, xj, yj, 90.0, fl_j))
            y_curr_l -= sec_j.width

        # Торец левого крыла
        if cascade_floors and floors > min_wing_floors:
            sec_end_l = self._find_best_section(self.library.get_end_sections(), min_wing_floors) or end
            fl_end_l = min_wing_floors
        else:
            sec_end_l = end
            fl_end_l = floors
        fl_end_l = self._clamp_floors(sec_end_l, fl_end_l)
        xe_l = sec_end_l.depth / 2.0
        ye_l = y_curr_l - sec_end_l.width / 2.0
        sections.append(PlacedSection(sec_end_l, xe_l, ye_l, 90.0, fl_end_l))

        # 3. Правое крыло (в сторону юга -Y)
        K_r = num_wing_right + 1
        y_curr_r = -dc_r
        for k in range(num_wing_right):
            if cascade_floors and floors > min_wing_floors:
                step_ratio = (k + 1) / K_r
                fl_k = round(floors - step_ratio * (floors - min_wing_floors))
                sec_k = self._find_best_section(self.library.get_middle_sections(), fl_k) or middle
            else:
                sec_k = middle
                fl_k = floors
            fl_k = self._clamp_floors(sec_k, fl_k)

            xk = x_right_outer - sec_k.depth / 2.0
            yk = y_curr_r - sec_k.width / 2.0
            sections.append(PlacedSection(sec_k, xk, yk, 90.0, fl_k))
            y_curr_r -= sec_k.width

        # Торец правого крыла
        if cascade_floors and floors > min_wing_floors:
            sec_end_r = self._find_best_section(self.library.get_end_sections(), min_wing_floors) or end
            fl_end_r = min_wing_floors
        else:
            sec_end_r = end
            fl_end_r = floors
        fl_end_r = self._clamp_floors(sec_end_r, fl_end_r)
        xe_r = x_right_outer - sec_end_r.depth / 2.0
        ye_r = y_curr_r - sec_end_r.width / 2.0
        sections.append(PlacedSection(sec_end_r, xe_r, ye_r, 90.0, fl_end_r))

        # 4. Центрирование в (0, 0)
        fps = [s.footprint for s in sections]
        cx = (min(f.bounds[0] for f in fps) + max(f.bounds[2] for f in fps)) / 2.0
        cy = (min(f.bounds[1] for f in fps) + max(f.bounds[3] for f in fps)) / 2.0

        return [
            PlacedSection(s.section_type, s.x - cx, s.y - cy, s.angle, s.floors, is_flipped=s.is_flipped)
            for s in sections
        ]

    def _build_l_shape_local(
        self,
        middle: SectionType,
        corner: SectionType,
        end: SectionType,
        floors: int,
        num_mid_x: int,
        num_mid_y: int,
        cascade_floors: bool = True,
        min_wing_floors: int = 8,
    ) -> list[PlacedSection]:
        """Г-образный корпус, центрированный в (0, 0), без наложений секций."""
        sections: list[PlacedSection] = []

        fl_cor = self._clamp_floors(corner, floors)
        wc, dc = corner.width, corner.depth

        # Угловая секция в верхнем правом стыке
        xc = -wc / 2.0
        yc = -dc / 2.0
        sections.append(PlacedSection(corner, xc, yc, 0.0, fl_cor, is_flipped=True))

        # 1. Горизонтальное крыло влево (-X)
        fl_x = floors
        if cascade_floors and floors > min_wing_floors:
            sec_x = self._find_best_section(self.library.get_middle_sections(), fl_x) or middle
        else:
            sec_x = middle
        fl_x = self._clamp_floors(sec_x, fl_x)
        wm_x, dm_x = sec_x.width, sec_x.depth

        x_curr = -wc
        for _ in range(num_mid_x):
            xm = x_curr - wm_x / 2.0
            ym = -dm_x / 2.0
            sections.append(PlacedSection(sec_x, xm, ym, 0.0, fl_x))
            x_curr -= wm_x

        sec_end_x = end
        fl_end_x = self._clamp_floors(sec_end_x, fl_x)
        xe = x_curr - sec_end_x.width / 2.0
        ye = -sec_end_x.depth / 2.0
        sections.append(PlacedSection(sec_end_x, xe, ye, 0.0, fl_end_x))

        # 2. Вертикальное крыло вниз (-Y) с каскадным понижением к югу
        K_y = num_mid_y + 1
        y_curr = -dc
        for j in range(num_mid_y):
            if cascade_floors and floors > min_wing_floors:
                step_ratio = (j + 1) / K_y
                fl_j = round(floors - step_ratio * (floors - min_wing_floors))
                sec_j = self._find_best_section(self.library.get_middle_sections(), fl_j) or middle
            else:
                sec_j = middle
                fl_j = floors
            fl_j = self._clamp_floors(sec_j, fl_j)

            xv = -sec_j.depth / 2.0
            yv = y_curr - sec_j.width / 2.0
            sections.append(PlacedSection(sec_j, xv, yv, 90.0, fl_j))
            y_curr -= sec_j.width

        if cascade_floors and floors > min_wing_floors:
            sec_end_y = self._find_best_section(self.library.get_end_sections(), min_wing_floors) or end
            fl_end_y = min_wing_floors
        else:
            sec_end_y = end
            fl_end_y = floors
        fl_end_y = self._clamp_floors(sec_end_y, fl_end_y)
        xev = -sec_end_y.depth / 2.0
        yev = y_curr - sec_end_y.width / 2.0
        sections.append(PlacedSection(sec_end_y, xev, yev, 90.0, fl_end_y))

        # 3. Центрирование
        fps = [s.footprint for s in sections]
        cx = (min(f.bounds[0] for f in fps) + max(f.bounds[2] for f in fps)) / 2.0
        cy = (min(f.bounds[1] for f in fps) + max(f.bounds[3] for f in fps)) / 2.0

        return [
            PlacedSection(s.section_type, s.x - cx, s.y - cy, s.angle, s.floors, is_flipped=s.is_flipped)
            for s in sections
        ]

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
                    is_flipped=s.is_flipped,
                    floor_height=s.floor_height or self._current_floor_height,
                    ground_floor_height=s.ground_floor_height or self._current_ground_floor_height,
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

        # Соразмерный масштаб основания скобы (65–88 м вместо монстров 180 м)
        num_back = 1 if middle.width > 35.0 or placement_config.max_sections_per_building < 7 else 2
        passage_gap = float(self.config.get("passage_gap_min", 18.0))
        side_gap = max(fire_gap, passage_gap)

        # Если при num_back=1 помещается 2 квартала, а при 2 только один — выбираем 1 для естественного ансамбля
        if num_back == 2:
            u_w_1 = corner.width * 2 + middle.width
            u_w_2 = corner.width * 2 + 2 * middle.width
            if (2 * u_w_1 + side_gap <= length) and (2 * u_w_2 + side_gap > length):
                num_back = 1

        # Соразмерная глубина крыльев: при широких секциях (M5=45м) 1 секция дает крыло 95м
        num_wing = 1 if (middle.width > 35.0 or width < 140.0) else 2

        max_sec = placement_config.max_sections_per_building
        min_sec = placement_config.min_sections_per_building
        can_place_u = max_sec >= 5

        u_w = corner.width * 2 + num_back * middle.width
        u_h = middle.depth + num_wing * middle.width + end.width
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

            if can_place_u:
                if placement_config.asymmetric_wings:
                    if middle.width > 35.0:
                        cand_wings = [(1, 1), (1, 0), (0, 1), (0, 0)]
                    elif col % 2 == 0:
                        cand_wings = [(2, 1), (1, 2), (1, 1), (1, 0), (0, 1), (0, 0)]
                    else:
                        cand_wings = [(1, 2), (2, 1), (1, 1), (0, 1), (1, 0), (0, 0)]
                else:
                    cand_wings = [(num_wing, num_wing), (1, 1), (0, 0)]
                # U-корпус: 2 угла + num_back + wl + 1 торец + wr + 1 торец = 4 + num_back + wl + wr
                cand_wings = [
                    (wl, wr) for wl, wr in cand_wings
                    if min_sec <= (4 + num_back + wl + wr) <= max_sec
                ]
            else:
                cand_wings = []

            cand_l_shapes = [(num_back, 1), (num_back, 0), (1, 1), (1, 0), (0, 0)]
            # L-корпус: 1 угол + (nx + 1 торец) + (ny + 1 торец) = 3 + nx + ny
            cand_l_shapes = [
                (nx, ny) for nx, ny in cand_l_shapes
                if min_sec <= (3 + nx + ny) <= max_sec
            ]

            # 1. Пробуем поставить П-образный корпус со двором
            placed = False
            for n_wl, n_wr in cand_wings:
                cand_u = self._create_u_building(
                    px, py, court_angle, middle, corner, end, floors,
                    num_back, n_wl, n_wr,
                    cascade_floors=placement_config.cascade_floors,
                    min_wing_floors=placement_config.min_wing_floors,
                )
                if cand_u and self._fits_in_buildable(cand_u) and self._check_constraints(cand_u, buildings, placement_config):
                    buildings.append(cand_u)
                    placed = True
                    break

            if placed:
                continue

            # 2. Если скоба не вошла, пробуем Г-образный блок
            for nx, ny in cand_l_shapes:
                cand_l = self._create_l_building(
                    px, py, court_angle, middle, corner, end, floors,
                    num_mid_x=nx, num_mid_y=ny,
                    cascade_floors=placement_config.cascade_floors,
                    min_wing_floors=placement_config.min_wing_floors,
                )
                if cand_l and self._fits_in_buildable(cand_l) and self._check_constraints(cand_l, buildings, placement_config):
                    buildings.append(cand_l)
                    break

        # 3. Дозаполняем оставшиеся свободные зоны участка соразмерными корпусами (северная улица, фланги)
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
        if placement_config.max_sections_per_building < 5:
            return self._generate_l_shape_layout(
                buildable, angle, middle, corner, end, floors, placement_config
            )

        length, width, _ = get_obb_dimensions(buildable)
        centroid = buildable.centroid
        buildings: list[Building] = []

        court_angle = self._get_solar_courtyard_angle(placement_config, angle)
        fire_gap = self._get_fire_gap(floors)

        num_back = 1 if middle.width > 35.0 or placement_config.max_sections_per_building < 7 else 2
        passage_gap = float(self.config.get("passage_gap_min", 18.0))
        side_gap = max(fire_gap, passage_gap)

        # Если при num_back=1 помещается 2 квартала, а при 2 только один — выбираем 1 для естественного ансамбля
        if num_back == 2:
            u_w_1 = corner.width * 2 + middle.width
            u_w_2 = corner.width * 2 + 2 * middle.width
            if (2 * u_w_1 + side_gap <= length) and (2 * u_w_2 + side_gap > length):
                num_back = 1

        # Соразмерная глубина крыльев: при широких секциях (M5=45м) 1 секция дает крыло 95м
        num_wing = 1 if (middle.width > 35.0 or width < 140.0) else 2

        max_sec = placement_config.max_sections_per_building
        min_sec = placement_config.min_sections_per_building

        u_w = corner.width * 2 + num_back * middle.width
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

        u_h = middle.depth + num_wing * middle.width + end.width
        target_oy = -width / 2.0 + u_h / 2.0 + 8.0 if width >= 110.0 else 0.0

        for col in range(cols):
            ox = start_ox + col * u_step_x
            px = centroid.x + ox * ux[0] + target_oy * uy[0]
            py = centroid.y + ox * ux[1] + target_oy * uy[1]

            if placement_config.asymmetric_wings:
                if middle.width > 35.0:
                    cand_wings = [(1, 1), (1, 0), (0, 1), (0, 0)]
                elif col % 2 == 0:
                    cand_wings = [(2, 1), (1, 2), (1, 1), (1, 0), (0, 1), (0, 0)]
                else:
                    cand_wings = [(1, 2), (2, 1), (1, 1), (0, 1), (1, 0), (0, 0)]
            else:
                cand_wings = [(num_wing, num_wing), (1, 1), (0, 0)]

            cand_wings = [
                (wl, wr) for wl, wr in cand_wings
                if min_sec <= (4 + num_back + wl + wr) <= max_sec
            ]

            for n_wl, n_wr in cand_wings:
                cand = self._create_u_building(
                    px, py, court_angle, middle, corner, end, floors,
                    num_back, n_wl, n_wr,
                    cascade_floors=placement_config.cascade_floors,
                    min_wing_floors=placement_config.min_wing_floors,
                )
                if cand and self._fits_in_buildable(cand) and self._check_constraints(cand, buildings, placement_config):
                    buildings.append(cand)
                    break

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
        if placement_config.max_sections_per_building < 3:
            return self._generate_linear(
                buildable, angle, middle, end, floors, placement_config
            )

        length, width, _ = get_obb_dimensions(buildable)
        centroid = buildable.centroid
        buildings: list[Building] = []

        court_angle = self._get_solar_courtyard_angle(placement_config, angle)
        fire_gap = self._get_fire_gap(floors)

        max_sec = placement_config.max_sections_per_building
        min_sec = placement_config.min_sections_per_building

        num_x = 1 if middle.width > 35.0 else 2
        num_y = 1 if width < 120.0 else 2

        l_w = corner.width + num_x * middle.width + end.width
        passage_gap = float(self.config.get("passage_gap_min", 18.0))
        l_step_x = l_w + max(fire_gap, passage_gap)
        cols = max(1, int(length / l_step_x))

        span_x = (cols - 1) * l_step_x
        start_ox = -span_x / 2.0

        rad_p = math.radians(angle)
        ux = (math.cos(rad_p), math.sin(rad_p))

        for col in range(cols):
            ox = start_ox + col * l_step_x
            px = centroid.x + ox * ux[0]
            py = centroid.y + ox * ux[1]

            if placement_config.asymmetric_wings:
                cand_l = [(num_x, 2), (num_x, 1), (num_x, 0), (1, 1), (1, 0), (0, 0)]
            else:
                cand_l = [(num_x, num_y), (num_x, 0), (1, 1), (1, 0), (0, 0)]

            # L-корпус: 1 угол + (nx + 1 торец) + (ny + 1 торец) = 3 + nx + ny
            cand_l = [
                (nx, ny) for nx, ny in cand_l
                if min_sec <= (3 + nx + ny) <= max_sec
            ]

            for nx, ny in cand_l:
                cand = self._create_l_building(
                    px, py, court_angle, middle, corner, end, floors,
                    num_mid_x=nx, num_mid_y=ny,
                    cascade_floors=placement_config.cascade_floors,
                    min_wing_floors=placement_config.min_wing_floors,
                )
                if cand and self._fits_in_buildable(cand) and self._check_constraints(cand, buildings, placement_config):
                    buildings.append(cand)
                    break

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
        """Генерация параллельной рядовой застройки соразмерными корпусами (<= 90 м)."""
        fire_gap = self._get_fire_gap(floors)
        insol_gap = self._get_insolation_gap(floors)
        row_spacing = middle.depth + max(fire_gap, insol_gap)

        row_lines = self._compute_row_positions(buildable, angle, row_spacing, middle.depth)
        buildings: list[Building] = []

        for line in row_lines:
            cands = self._create_linears_on_line(
                line, middle, end, floors, angle, placement_config
            )
            for b in cands:
                if self._check_constraints(b, buildings, placement_config):
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
        num_wing_left: int = 2,
        num_wing_right: int = 2,
        cascade_floors: bool = True,
        min_wing_floors: int = 8,
    ) -> Building | None:
        """Создать П-образное здание в точке (cx, cy)."""
        try:
            local_secs = self._build_u_shape_local(
                middle, corner, end, floors, num_back,
                num_wing_left, num_wing_right,
                cascade_floors=cascade_floors,
                min_wing_floors=min_wing_floors,
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
        cascade_floors: bool = True,
        min_wing_floors: int = 8,
    ) -> Building | None:
        """Создать Г-образное здание в точке (cx, cy)."""
        try:
            local_secs = self._build_l_shape_local(
                middle, corner, end, floors, num_mid_x, num_mid_y,
                cascade_floors=cascade_floors,
                min_wing_floors=min_wing_floors,
            )
            placed_secs = self._transform_sections(local_secs, cx, cy, angle)
            return Building(sections=placed_secs, typology="L_SHAPE")
        except Exception:
            return None

    def _create_single_linear(
        self,
        center_line: LineString,
        middle: SectionType,
        end: SectionType,
        floors: int,
        angle: float,
        placement_config: PlacementConfig,
    ) -> Building | None:
        """Создать один соразмерный линейный корпус на отрезке линии."""
        line_len = center_line.length
        min_len = end.width * 2
        if line_len < min_len:
            return None

        avail = line_len - end.width * 2
        num_middle = max(0, int(avail / middle.width))

        total_secs = num_middle + 2
        if total_secs > placement_config.max_sections_per_building:
            num_middle = max(0, placement_config.max_sections_per_building - 2)
            total_secs = num_middle + 2

        if total_secs < placement_config.min_sections_per_building:
            return None

        midpoint = center_line.interpolate(line_len / 2.0)
        local_secs = self._build_linear_local(
            middle, end, floors, num_middle,
            cascade_floors=placement_config.cascade_floors,
            min_wing_floors=placement_config.min_wing_floors,
        )
        placed_secs = self._transform_sections(local_secs, midpoint.x, midpoint.y, angle)
        building = Building(sections=placed_secs, typology="LINEAR")

        if not self._fits_in_buildable(building):
            while num_middle > 0:
                num_middle -= 1
                local_secs = self._build_linear_local(
                    middle, end, floors, num_middle,
                    cascade_floors=placement_config.cascade_floors,
                    min_wing_floors=placement_config.min_wing_floors,
                )
                placed_secs = self._transform_sections(local_secs, midpoint.x, midpoint.y, angle)
                building = Building(sections=placed_secs, typology="LINEAR")
                if self._fits_in_buildable(building):
                    return building
            return None

        return building

    def _create_linears_on_line(
        self,
        center_line: LineString,
        middle: SectionType,
        end: SectionType,
        floors: int,
        angle: float,
        placement_config: PlacementConfig,
    ) -> list[Building]:
        """Создать цепочку соразмерных линейных зданий (<= 90 м) с разрывами для проездов."""
        line_len = center_line.length
        min_len = end.width * 2
        if line_len < min_len:
            return []

        max_secs = placement_config.max_sections_per_building
        max_sec_len = max(end.width * 2, (max_secs - 2) * middle.width + end.width * 2)
        norm_max_len = float(self.config.get("building_max_length", 90.0))
        max_bldg_len = min(norm_max_len, max_sec_len)
        passage_gap = float(self.config.get("passage_gap_min", 18.0))

        # Если линия короче допустимой длины одного дома, ставим один дом
        if line_len <= max_bldg_len:
            b = self._create_single_linear(center_line, middle, end, floors, angle, placement_config)
            return [b] if b is not None else []

        # Иначе делим длинную линию на соразмерные корпуса (<= max_bldg_len) с разрывами для проездов
        num_bldgs = math.ceil((line_len - max_bldg_len) / (max_bldg_len + passage_gap)) + 1
        avail_for_bldgs = line_len - (num_bldgs - 1) * passage_gap
        target_len = avail_for_bldgs / num_bldgs

        buildings: list[Building] = []
        for b_idx in range(num_bldgs):
            d_start = b_idx * (target_len + passage_gap)
            d_end = d_start + target_len
            p_start = center_line.interpolate(d_start)
            p_end = center_line.interpolate(d_end)
            seg = LineString([p_start, p_end])

            b = self._create_single_linear(seg, middle, end, floors, angle, placement_config)
            if b is not None:
                buildings.append(b)

        return buildings

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
        """Дозаполнить свободные части участка (фланги, уличный фронт) соразмерными корпусами."""
        fire_gap = self._get_fire_gap(floors)
        half_d = middle.depth / 2.0
        inner_buildable = buildable.buffer(-half_d)
        if inner_buildable.is_empty:
            return

        min_area = end.width * 2 * middle.depth

        min_clearance = max(fire_gap * 1.2 + 0.5, 18.5)

        # Защита дворовых пространств и пожарных разрывов:
        # Для П-образных и Г-образных корпусов исключаем их выпуклую оболочку (дворовое пространство)
        if buildings:
            exclusion_polys = []
            for b in buildings:
                if b.typology in ("U_SHAPE", "L_SHAPE"):
                    exclusion_polys.append(b.footprint.convex_hull.buffer(min_clearance))
                else:
                    exclusion_polys.append(b.footprint.buffer(min_clearance))
            occupied = unary_union(exclusion_polys)
            angles_to_try = [angle + 90.0, angle]
        else:
            occupied = Polygon()
            angles_to_try = [angle, angle + 90.0]

        remaining = inner_buildable.difference(occupied)

        for cand_ang in angles_to_try:
            parts = remaining.geoms if isinstance(remaining, MultiPolygon) else [remaining]
            for part in parts:
                if part.is_empty or part.area < min_area:
                    continue

                rad = math.radians(cand_ang)
                ux, uy = math.cos(rad), math.sin(rad)
                px, py = -math.sin(rad), math.cos(rad)

                coords = list(part.exterior.coords)
                proj = [x * px + y * py for x, y in coords]
                t_min, t_max = min(proj), max(proj)
                span = t_max - t_min

                step = middle.depth + max(fire_gap, 15.0)
                t_vals = []
                cur_t = t_min
                while cur_t <= t_max:
                    t_vals.append(cur_t)
                    cur_t += step
                if not t_vals or (t_max - t_vals[-1]) > step * 0.5:
                    t_vals.append(t_max)

                ray_len = max(span, 300.0)

                for t in t_vals:
                    lx = t * px
                    ly = t * py

                    p1 = (lx - ray_len * ux, ly - ray_len * uy)
                    p2 = (lx + ray_len * ux, ly + ray_len * uy)
                    raw_line = LineString([p1, p2]).intersection(part)

                    if raw_line.is_empty:
                        continue

                    if isinstance(raw_line, LineString):
                        segs = [raw_line]
                    elif hasattr(raw_line, "geoms"):
                        segs = [g for g in raw_line.geoms if isinstance(g, LineString)]
                    else:
                        segs = []
                    for seg in segs:
                        if seg.length < end.width * 2:
                            continue

                        # На перпендикулярных флангах для живой пластики этажность согласуется с каскадом
                        fl = (
                            max(placement_config.min_wing_floors, floors - 3)
                            if (round(cand_ang % 180) != round(angle % 180))
                            else floors
                        )
                        cands = self._create_linears_on_line(
                            seg, middle, end, fl, cand_ang, placement_config
                        )
                        for cand in cands:
                            if self._fits_in_buildable(cand) and self._check_constraints(
                                cand, buildings, placement_config
                            ):
                                buildings.append(cand)
                                occupied = unary_union([occupied, cand.footprint.convex_hull.buffer(min_clearance)])
                                remaining = inner_buildable.difference(occupied)

    def _get_solar_courtyard_angle(
        self, placement_config: PlacementConfig, primary_angle: float
    ) -> float:
        """Определить угол ориентации дворов по сторонам света с привязкой к сетке участка."""
        orientation = placement_config.courtyard_orientation.upper()
        if orientation == "AUTO":
            orientation = "SOUTH"

        target_angles = {
            "SOUTH": 0.0,
            "EAST": 90.0,
            "NORTH": 180.0,
            "WEST": 270.0,
        }
        target = target_angles.get(orientation, 0.0)

        # 4 направления сетки участка
        candidates = [
            primary_angle % 360,
            (primary_angle + 90.0) % 360,
            (primary_angle + 180.0) % 360,
            (primary_angle + 270.0) % 360,
        ]

        def ang_diff(a1: float, a2: float) -> float:
            d = abs(a1 - a2) % 360
            return min(d, 360 - d)

        return min(candidates, key=lambda c: ang_diff(c, target))

    def _find_best_section(
        self,
        sections: list[SectionType],
        target_floors: int | None,
    ) -> SectionType | None:
        """Подобрать наилучшую секцию с учетом диапазона этажей и лифтовых ограничений."""
        if not sections:
            return None

        # Если задана предельная высота здания, отсекаем секции с завышенной минимальной этажностью
        max_h_fl = getattr(self, "_max_floors_from_h", None)
        if max_h_fl is not None:
            viable = [s for s in sections if s.min_floors <= max_h_fl]
            if viable:
                sections = viable

        if target_floors is None:
            return sections[0]

        # 1. Секции, строго вмещающие заданную этажность
        matching = [s for s in sections if s.min_floors <= target_floors <= s.max_floors]
        if matching:
            return min(matching, key=lambda s: abs(s.default_floors - target_floors))

        # 2. Иначе секция с минимальным расстоянием до допустимого диапазона
        def dist(s: SectionType) -> int:
            if target_floors < s.min_floors:
                return s.min_floors - target_floors
            return target_floors - s.max_floors

        return min(sections, key=dist)

    def _select_sections(
        self, placement_config: PlacementConfig
    ) -> dict[str, SectionType] | None:
        """Выбрать секции для расстановки с учетом этажности и предпочтений."""
        target_fl = placement_config.target_floors

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
                sections["middle"] = self._find_best_section(
                    self.library.get_middle_sections(), target_fl
                )
            if "end" not in sections:
                best_end = self._find_best_section(self.library.get_end_sections(), target_fl)
                sections["end"] = best_end if best_end else sections.get("middle")
            if "corner" not in sections:
                best_cor = self._find_best_section(self.library.get_corner_sections(), target_fl)
                sections["corner"] = best_cor if best_cor else sections.get("middle")
            return sections if "middle" in sections else None

        middles = self.library.get_middle_sections()
        ends = self.library.get_end_sections()
        corners = self.library.get_corner_sections()

        if not middles:
            return None

        best_middle = self._find_best_section(middles, target_fl)
        best_end = self._find_best_section(ends, target_fl)
        best_corner = self._find_best_section(corners, target_fl)

        result: dict[str, SectionType] = {"middle": best_middle}
        result["end"] = best_end if best_end else best_middle
        result["corner"] = best_corner if best_corner else best_middle
        return result

    def _compute_row_positions(
        self,
        buildable: Polygon,
        angle: float,
        row_spacing: float,
        section_depth: float = 17.0,
    ) -> list[LineString]:
        """Вычислить центральные линии рядов с гарантированным отступом от границы зоны застройки."""
        length, width, _ = get_obb_dimensions(buildable)
        centroid = buildable.centroid
        cx, cy = centroid.x, centroid.y

        perp_angle_rad = math.radians(angle + 90.0)
        row_angle_rad = math.radians(angle)

        half_d = section_depth / 2.0 + 1.0
        usable_width = width - 2.0 * half_d

        if usable_width <= 0:
            usable_width = max(10.0, width * 0.5)
            num_rows = 1
            start_offset = 0.0
            actual_spacing = 0.0
        else:
            num_rows = max(1, int(usable_width / row_spacing) + 1)
            actual_spacing = usable_width / (num_rows - 1) if num_rows > 1 else 0.0
            total_w = (num_rows - 1) * actual_spacing
            start_offset = -total_w / 2.0

        row_lines: list[LineString] = []

        clip_poly = buildable.buffer(-0.5)
        if clip_poly.is_empty:
            clip_poly = buildable

        for i in range(num_rows):
            offset = start_offset + (i * actual_spacing if num_rows > 1 else 0.0)
            row_cx = cx + offset * math.cos(perp_angle_rad)
            row_cy = cy + offset * math.sin(perp_angle_rad)

            half_len = length
            x1 = row_cx - half_len * math.cos(row_angle_rad)
            y1 = row_cy - half_len * math.sin(row_angle_rad)
            x2 = row_cx + half_len * math.cos(row_angle_rad)
            y2 = row_cy + half_len * math.sin(row_angle_rad)

            clipped = LineString([(x1, y1), (x2, y2)]).intersection(clip_poly)
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
        """Проверить, что здание строго помещается в зону допустимой застройки."""
        try:
            footprint = building.footprint
            buildable = self.site.buildable_area
            # Строгое вхождение без наезда на нормативный отступ
            return buildable.contains(footprint)
        except Exception:
            return False

    def _check_constraints(
        self,
        new_building: Building,
        existing_buildings: list[Building],
        placement_config: PlacementConfig | None = None,
    ) -> bool:
        """Проверить нормативные противопожарные и инсоляционные расстояния."""
        if placement_config is not None:
            if len(new_building.sections) > placement_config.max_sections_per_building:
                return False
            if len(new_building.sections) < placement_config.min_sections_per_building:
                return False

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
        floor_height = getattr(self, "_current_floor_height", None) or self.config.get("floor_height", 3.0)
        building_height = floors * floor_height
        insol_factor = self.config.get("insolation_factor", 0.5)
        return building_height * insol_factor
