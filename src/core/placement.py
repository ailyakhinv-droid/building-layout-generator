"""Движок расстановки зданий на участке.

Реализует современные градостроительные алгоритмы размещения типовых секций:
- Линейная застройка (пластины / рядовые корпуса)
- Г-образные корпуса (уголки)
- П-образные корпуса (скобы с комфортными зелеными дворами)
- Смешанная / квартальная компоновка (AUTO) с переменным шагом инсоляции.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
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
class PlacementResult:
    """Результат расстановки зданий на участке."""

    buildings: list[Building] = field(default_factory=list)
    site_area: float = 0.0
    footprint_area: float = 0.0
    bcr: float = 0.0
    gfa: float = 0.0
    far: float = 0.0

    def __iter__(self):
        return iter(self.buildings)

    def __len__(self):
        return len(self.buildings)

    def __getitem__(self, idx):
        return self.buildings[idx]


# Свойства-алиасы для Building для совместимости с API анализа и тестов
if not hasattr(Building, "footprint_area"):
    Building.footprint_area = property(lambda self: self.total_building_area if self.sections else 0.0)
if not hasattr(Building, "gfa"):
    Building.gfa = property(lambda self: self.total_gfa if self.sections else 0.0)


@dataclass
class PlacementConfig:
    """Параметры для алгоритма расстановки.

    Attributes:
        target_floors: Целевая этажность (None = default из секции).
        placement_angle: Угол размещения в градусах (None = авто по длинной оси).
        preferred_section_ids: Список предпочтительных ID секций.
        min_sections_per_building: Мин. кол-во секций в здании.
        max_sections_per_building: Макс. кол-во секций в здании.
        typology: Типология застройки ("AUTO", "TOWER", "U_SHAPE", "L_SHAPE", "LINEAR").
        courtyard_orientation: Раскрытие дворов ("SOUTH", "NORTH", "EAST", "WEST", "AUTO").
        variable_insolation: Переменный шаг инсоляции (уменьшенный разрыв с торцов).
        cascade_floors: Каскадное понижение этажности к югу (дворам).
        asymmetric_wings: Асимметричная длина крыльев (живой силуэт, раскрытие к свету).
        min_wing_floors: Минимальная этажность южных торцов/крыльев.
        allow_towers_in_mixed: Разрешить башни-акценты на свободных пятнах в AUTO/смешанном режиме.
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
    allow_towers_in_mixed: bool = True
    urban_block_size: float = 100.0
    internal_road_width: float = 16.0
    perimeter_layout_style: str = "U_SHAPE"
    max_bcr: float | None = None
    max_far: float | None = None


class PlacementEngine:
    """Движок расстановки типовых секций и зданий."""

    def __init__(
        self,
        site_or_config: Site | PlacementConfig | dict[str, Any] | None = None,
        library: SectionLibrary | None = None,
        config: dict[str, Any] | PlacementConfig | None = None,
    ) -> None:
        """Инициализировать движок. Поддерживает как (site, library, config), так и (PlacementConfig)."""
        if isinstance(site_or_config, PlacementConfig):
            self.placement_config: PlacementConfig | None = site_or_config
            self.site: Site | None = None
            self.library: SectionLibrary = library if library is not None else SectionLibrary()
            self.config: dict[str, Any] = config if isinstance(config, dict) else {}
        elif isinstance(site_or_config, dict):
            self.placement_config = None
            self.site = None
            self.library = library if library is not None else SectionLibrary()
            self.config = site_or_config
        else:
            self.site = site_or_config
            self.library = library if library is not None else SectionLibrary()
            if isinstance(config, PlacementConfig):
                self.placement_config = config
                self.config = {}
            else:
                self.placement_config = None
                self.config = config if config is not None else {}

        # Инициализация параметров высоты
        cfg_dict = self.config
        p_cfg = getattr(self, "placement_config", None)

        floor_h = 3.0
        if p_cfg and p_cfg.floor_height is not None:
            floor_h = float(p_cfg.floor_height)
        elif "floor_height" in cfg_dict:
            floor_h = float(cfg_dict["floor_height"])
        self._current_floor_height: float = floor_h

        ground_h = None
        if p_cfg and p_cfg.ground_floor_height is not None:
            ground_h = float(p_cfg.ground_floor_height)
        elif "ground_floor_height" in cfg_dict:
            ground_h = float(cfg_dict["ground_floor_height"]) if cfg_dict["ground_floor_height"] is not None else None
        self._current_ground_floor_height: float | None = ground_h

        max_h = None
        if p_cfg and p_cfg.max_building_height_m is not None:
            max_h = float(p_cfg.max_building_height_m)
        elif "max_building_height_m" in cfg_dict:
            max_h = float(cfg_dict["max_building_height_m"]) if cfg_dict["max_building_height_m"] is not None else None
        self._max_building_height_m: float | None = max_h

        max_floors_from_h = None
        if self._max_building_height_m and self._max_building_height_m > 0:
            gh = (
                self._current_ground_floor_height
                if self._current_ground_floor_height is not None
                else self._current_floor_height
            )
            extra_first = max(0.0, gh - self._current_floor_height)
            max_floors_from_h = max(
                1,
                int((self._max_building_height_m - extra_first) // self._current_floor_height),
            )
        self._max_floors_from_h = max_floors_from_h

        if self.site is not None and getattr(self.site, "buildable_area", None) is None:
            try:
                b_setback = float(self.config.get("boundary_setback", 6.0))
                r_setback = float(self.config.get("red_line_setback", 5.0))
                self.site.compute_buildable_area(b_setback, r_setback)
            except Exception:
                pass

    def place(
        self,
        site_or_poly: Site | Polygon,
        placement_config: PlacementConfig | None = None,
    ) -> PlacementResult:
        """Разместить секции на участке (Site или Polygon) и вернуть PlacementResult."""
        if placement_config is None:
            placement_config = getattr(self, "placement_config", None) or PlacementConfig()

        if isinstance(site_or_poly, Polygon):
            site = Site(boundary=site_or_poly)
            b_setback = float(self.config.get("boundary_setback", 6.0))
            r_setback = float(self.config.get("red_line_setback", 5.0))
            site.compute_buildable_area(boundary_setback=b_setback, red_line_setback=r_setback)
            self.site = site
        elif isinstance(site_or_poly, Site):
            self.site = site_or_poly
            if self.site.buildable_area is None:
                b_setback = float(self.config.get("boundary_setback", 6.0))
                r_setback = float(self.config.get("red_line_setback", 5.0))
                self.site.compute_buildable_area(boundary_setback=b_setback, red_line_setback=r_setback)
        else:
            raise TypeError(f"Expected Site or Polygon, got {type(site_or_poly)}")

        buildings = self.generate(placement_config)
        site_area = self.site.area if self.site else 0.0
        footprint = sum(b.footprint_area for b in buildings)
        bcr = footprint / site_area if site_area > 0 else 0.0
        gfa = sum(b.gfa for b in buildings)
        far = gfa / site_area if site_area > 0 else 0.0

        return PlacementResult(
            buildings=buildings,
            site_area=site_area,
            footprint_area=footprint,
            bcr=bcr,
            gfa=gfa,
            far=far,
        )

    def _is_bcr_reached(
        self,
        buildings: list[Building],
        placement_config: PlacementConfig | None = None,
    ) -> bool:
        """Проверить, достигнут ли предельный BCR по текущей застройке."""
        if not buildings or not getattr(self.site, "area", None) or self.site.area <= 0:
            return False
        raw_bcr = (
            placement_config.max_bcr
            if (placement_config and placement_config.max_bcr is not None)
            else self.config.get("max_bcr")
        )
        if raw_bcr is None or float(raw_bcr) <= 0:
            return False
        max_bcr = float(raw_bcr)
        cur_footprint = sum(b.total_building_area for b in buildings)
        return cur_footprint >= self.site.area * max_bcr * 0.999

    def generate(
        self,
        placement_config: PlacementConfig | None = None,
    ) -> list[Building]:
        """Сгенерировать расстановку зданий на участке."""
        if placement_config is None:
            placement_config = getattr(self, "placement_config", None) or PlacementConfig()

        if self.site is None or getattr(self.site, "buildable_area", None) is None:
            raise ValueError(
                "Зона допустимой застройки не вычислена. "
                "Вызовите site.compute_buildable_area() перед расстановкой."
            )

        self._placed_building_count: int = 0

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
        tower = sections.get("tower", middle)

        self._middle_pool = sections.get("middle_pool", [middle])
        self._end_pool = sections.get("end_pool", [end])
        self._corner_pool = sections.get("corner_pool", [corner])
        self._tower_pool = sections.get("tower_pool", [tower])
        self._has_preferred_sections = bool(placement_config.preferred_section_ids)

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

        if typology in ("TOWER", "TOWERS", "POINT"):
            tower_sec = sections.get("tower", middle)
            t_floors = placement_config.target_floors or tower_sec.default_floors
            t_floors = self._clamp_floors(tower_sec, t_floors)
            buildings = self._generate_tower_layout(
                buildable, primary_angle, tower_sec, t_floors, placement_config
            )
        elif typology == "LINEAR":
            buildings = self._generate_linear(
                buildable, primary_angle, middle, end, floors, placement_config
            )
        elif typology == "U_SHAPE":
            buildings = self._generate_u_shape_layout(
                buildable, primary_angle, middle, corner, end, floors, placement_config
            )
        elif typology == "L_SHAPE":
            buildings = self._generate_l_shape_layout(
                buildable, primary_angle, middle, corner, end, floors, placement_config
            )
        elif typology in ("PERIMETER", "URBAN_BLOCK", "COURTYARD"):
            from src.core.perimeter_placement import PerimeterPlacementEngine
            engine = PerimeterPlacementEngine(self.site, self.library, self.config)
            buildings = engine.generate(
                buildable,
                primary_angle,
                self._middle_pool,
                self._corner_pool,
                self._end_pool,
                floors,
                placement_config,
            )
        else:  # AUTO / MIXED — естественная квартальная компоновка
            buildings = self._generate_mixed_layout(
                buildable, primary_angle, middle, corner, end, floors, placement_config
            )

        # 5. Строгое соблюдение нормативных ограничений (BCR, FAR, Height)
        return self._enforce_normative_limits(buildings, placement_config)

    def _enforce_normative_limits(
        self,
        buildings: list[Building],
        placement_config: PlacementConfig,
    ) -> list[Building]:
        """Строго скорректировать застройку под предельные нормативы BCR, FAR и Height."""
        if not buildings or not getattr(self.site, "area", None) or self.site.area <= 0:
            return buildings

        site_area = self.site.area
        raw_bcr = placement_config.max_bcr if placement_config.max_bcr is not None else self.config.get("max_bcr")
        raw_far = placement_config.max_far if placement_config.max_far is not None else self.config.get("max_far")

        max_bcr = float(raw_bcr) if raw_bcr is not None and float(raw_bcr) > 0 else None
        max_far = float(raw_far) if raw_far is not None and float(raw_far) > 0 else None

        # 0. Ограничение по предельной высоте/этажности
        if getattr(self, "_max_floors_from_h", None) is not None:
            max_fl = self._max_floors_from_h
            for b in buildings:
                for s in b.sections:
                    if s.floors > max_fl:
                        s.floors = max_fl

        # 1. Ограничение по BCR (процент застройки / пятно подошвы)
        if max_bcr is not None:
            allowed_footprint = site_area * max_bcr
            cur_footprint = sum(b.total_building_area for b in buildings)
            if cur_footprint > allowed_footprint * 1.005:
                kept: list[Building] = []
                acc_footprint = 0.0
                for b in buildings:
                    b_area = b.total_building_area
                    if acc_footprint + b_area <= allowed_footprint * 1.005:
                        kept.append(b)
                        acc_footprint += b_area

                if not kept and buildings:
                    first_b = buildings[0]
                    if first_b.total_building_area > allowed_footprint * 1.005:
                        fitted_secs = []
                        acc_sec = 0.0
                        for s in first_b.sections:
                            s_area = s.footprint.area
                            if acc_sec + s_area <= allowed_footprint * 1.005 or not fitted_secs:
                                fitted_secs.append(s)
                                acc_sec += s_area
                        buildings = [Building(sections=fitted_secs, typology=first_b.typology)]
                    else:
                        buildings = [first_b]
                else:
                    buildings = kept

        # 2. Ограничение по FAR (суммарная общая площадь / GFA)
        if max_far is not None and buildings:
            allowed_gfa = site_area * max_far
            cur_gfa = sum(b.total_gfa for b in buildings)
            if cur_gfa > allowed_gfa * 1.005:
                ratio = allowed_gfa / cur_gfa
                adjusted_buildings: list[Building] = []
                for b in buildings:
                    new_sections: list[PlacedSection] = []
                    for s in b.sections:
                        target_f = max(1, int(math.floor(s.floors * ratio)))
                        if getattr(self, "_max_floors_from_h", None) is not None:
                            target_f = min(target_f, self._max_floors_from_h)
                        new_s = PlacedSection(
                            section_type=s.section_type,
                            x=s.x,
                            y=s.y,
                            angle=s.angle,
                            floors=max(1, target_f),
                            floor_height=s.floor_height,
                            ground_floor_height=s.ground_floor_height,
                        )
                        new_sections.append(new_s)
                    new_b = Building(
                        sections=new_sections,
                        typology=getattr(b, "typology", "LINEAR"),
                    )
                    adjusted_buildings.append(new_b)
                buildings = adjusted_buildings

                # Если даже при уменьшенной этажности секций FAR превышен
                cur_gfa = sum(b.total_gfa for b in buildings)
                if cur_gfa > allowed_gfa * 1.005:
                    kept = []
                    acc_gfa = 0.0
                    for b in buildings:
                        if acc_gfa + b.total_gfa <= allowed_gfa * 1.005:
                            kept.append(b)
                            acc_gfa += b.total_gfa
                    buildings = kept if kept else buildings[:1]

        return buildings

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
        num_middle: int | list[SectionType],
        cascade_floors: bool = False,
        min_wing_floors: int = 8,
    ) -> list[PlacedSection]:
        """Линейный корпус, центрированный в (0, 0) по оси X, без наложений."""
        sections: list[PlacedSection] = []

        if isinstance(num_middle, list):
            target_mid_sections = list(num_middle)
            num_mid = len(target_mid_sections)
        else:
            num_mid = max(0, int(num_middle))
            target_mid_sections = [middle] * num_mid

        num_total = num_mid + 2

        # Расчет этажности по позициям
        floor_list = []
        for idx in range(num_total):
            if cascade_floors:
                # Силуэт: центр на целевой высоте, концы каскадно понижаются на 2-4 этажа
                drop = min(4, max(2, floors - min_wing_floors)) if (floors - min_wing_floors) >= 2 else min(2, max(0, floors - 1))
                dist = abs(idx - (num_total - 1) / 2.0) / max(1.0, (num_total - 1) / 2.0)
                fl = round(floors - dist * drop)
                floor_list.append(max(1, min(floors, fl)))
            else:
                floor_list.append(floors)

        end_candidates = self._end_pool if getattr(self, "_has_preferred_sections", False) else self.library.get_end_sections()
        mid_candidates = self._middle_pool if getattr(self, "_has_preferred_sections", False) else self.library.get_middle_sections()

        # 1. Первая торцевая секция
        fl_end1 = floor_list[0]
        sec_end1 = (
            self._find_best_section(end_candidates, fl_end1)
            if cascade_floors else end
        ) or end
        fl_end1 = self._clamp_floors(sec_end1, fl_end1)

        # 2. Рядовые секции
        mid_secs = []
        for i in range(num_mid):
            fl_m = floor_list[i + 1]
            base_m = target_mid_sections[i]
            sec_m = (
                self._find_best_section(mid_candidates, fl_m)
                if cascade_floors else base_m
            ) or base_m
            fl_m = self._clamp_floors(sec_m, fl_m)
            mid_secs.append((sec_m, fl_m))

        # 3. Вторая торцевая секция
        fl_end2 = floor_list[-1]
        sec_end2 = (
            self._find_best_section(end_candidates, fl_end2)
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
        end_candidates = self._end_pool if getattr(self, "_has_preferred_sections", False) else self.library.get_end_sections()
        mid_candidates = self._middle_pool if getattr(self, "_has_preferred_sections", False) else self.library.get_middle_sections()

        # Угловые секции
        sec_cor_l = corner
        sec_cor_r = corner
        fl_cor_l = self._clamp_floors(sec_cor_l, floors)
        fl_cor_r = self._clamp_floors(sec_cor_r, floors)
        cor_fl = max(fl_cor_l, fl_cor_r)
        wc_l, dc_l = sec_cor_l.width, sec_cor_l.depth
        wc_r, dc_r = sec_cor_r.width, sec_cor_r.depth

        # 1. Заднее крыло (основание скобы, северная часть)
        # Архитектурный переход: шаг высоты между угловой и рядовой секцией сглаживается
        max_step = 6
        back_secs = []
        for i in range(num_back):
            if cascade_floors:
                dist_from_corner = min(i + 1, num_back - i)
                fl_allowed = min(floors, cor_fl + dist_from_corner * max_step)
                fl_i = max(min_wing_floors, fl_allowed)
                sec_i = self._find_best_section(mid_candidates, fl_i) or middle
            else:
                sec_i = middle
                fl_i = floors
            fl_i = self._clamp_floors(sec_i, fl_i)
            back_secs.append((sec_i, fl_i))

        # Координаты основания:
        xc1 = wc_l / 2.0
        yc1 = -dc_l / 2.0
        sections.append(PlacedSection(sec_cor_l, xc1, yc1, 0.0, fl_cor_l, is_flipped=False))

        x_curr = wc_l
        for sec_b, fl_b in back_secs:
            xm = x_curr + sec_b.width / 2.0
            ym = -sec_b.depth / 2.0
            sections.append(PlacedSection(sec_b, xm, ym, 0.0, fl_b))
            x_curr += sec_b.width

        x_back_end = x_curr

        xc2 = x_back_end + wc_r / 2.0
        yc2 = -dc_r / 2.0
        sections.append(PlacedSection(sec_cor_r, xc2, yc2, 0.0, fl_cor_r, is_flipped=True))

        x_right_outer = x_back_end + wc_r

        # 2. Левое крыло (в сторону юга -Y)
        # Каскад понижается плавно, начиная от высоты левого угла на 2-4 этажа
        K_l = num_wing_left + 1
        y_curr_l = -dc_l
        wing_start_l = fl_cor_l
        drop_l = min(4, max(2, wing_start_l - min_wing_floors)) if wing_start_l > min_wing_floors else min(2, max(0, wing_start_l - 1))
        for j in range(num_wing_left):
            if cascade_floors:
                step_ratio = (j + 1) / K_l
                fl_j = round(wing_start_l - step_ratio * drop_l)
                fl_j = max(1, min(wing_start_l, fl_j))
                sec_j = self._find_best_section(mid_candidates, fl_j) or middle
            else:
                sec_j = middle
                fl_j = floors
            fl_j = self._clamp_floors(sec_j, fl_j)

            xj = sec_j.depth / 2.0
            yj = y_curr_l - sec_j.width / 2.0
            sections.append(PlacedSection(sec_j, xj, yj, 90.0, fl_j))
            y_curr_l -= sec_j.width

        # Торец левого крыла
        if cascade_floors:
            fl_end_l = max(1, wing_start_l - drop_l)
            sec_end_l = self._find_best_section(end_candidates, fl_end_l) or end
        else:
            sec_end_l = end
            fl_end_l = floors
        fl_end_l = self._clamp_floors(sec_end_l, fl_end_l)
        xe_l = sec_end_l.depth / 2.0
        ye_l = y_curr_l - sec_end_l.width / 2.0
        sections.append(PlacedSection(sec_end_l, xe_l, ye_l, 90.0, fl_end_l))

        # 3. Правое крыло (в сторону юга -Y)
        # Каскад понижается плавно, начиная от высоты правого угла на 2-4 этажа
        K_r = num_wing_right + 1
        y_curr_r = -dc_r
        wing_start_r = fl_cor_r
        drop_r = min(4, max(2, wing_start_r - min_wing_floors)) if wing_start_r > min_wing_floors else min(2, max(0, wing_start_r - 1))
        for k in range(num_wing_right):
            if cascade_floors:
                step_ratio = (k + 1) / K_r
                fl_k = round(wing_start_r - step_ratio * drop_r)
                fl_k = max(1, min(wing_start_r, fl_k))
                sec_k = self._find_best_section(mid_candidates, fl_k) or middle
            else:
                sec_k = middle
                fl_k = floors
            fl_k = self._clamp_floors(sec_k, fl_k)

            xk = x_right_outer - sec_k.depth / 2.0
            yk = y_curr_r - sec_k.width / 2.0
            sections.append(PlacedSection(sec_k, xk, yk, 90.0, fl_k))
            y_curr_r -= sec_k.width

        # Торец правого крыла
        if cascade_floors:
            fl_end_r = max(1, wing_start_r - drop_r)
            sec_end_r = self._find_best_section(end_candidates, fl_end_r) or end
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
        end_candidates = self._end_pool if getattr(self, "_has_preferred_sections", False) else self.library.get_end_sections()
        mid_candidates = self._middle_pool if getattr(self, "_has_preferred_sections", False) else self.library.get_middle_sections()

        fl_cor = self._clamp_floors(corner, floors)
        wc, dc = corner.width, corner.depth

        # Угловая секция в верхнем правом стыке
        xc = -wc / 2.0
        yc = -dc / 2.0
        sections.append(PlacedSection(corner, xc, yc, 0.0, fl_cor, is_flipped=True))

        # 1. Горизонтальное крыло влево (-X)
        max_step = 6
        x_curr = -wc
        fl_last_x = fl_cor
        for i in range(num_mid_x):
            if cascade_floors:
                fl_xi = min(floors, fl_cor + (i + 1) * max_step)
                sec_x = self._find_best_section(mid_candidates, fl_xi) or middle
            else:
                sec_x = middle
                fl_xi = floors
            fl_xi = self._clamp_floors(sec_x, fl_xi)
            fl_last_x = fl_xi
            wm_x, dm_x = sec_x.width, sec_x.depth
            xm = x_curr - wm_x / 2.0
            ym = -dm_x / 2.0
            sections.append(PlacedSection(sec_x, xm, ym, 0.0, fl_xi))
            x_curr -= wm_x

        fl_end_x = fl_last_x if cascade_floors else floors
        sec_end_x = (self._find_best_section(end_candidates, fl_end_x) if cascade_floors else end) or end
        fl_end_x = self._clamp_floors(sec_end_x, fl_end_x)
        xe = x_curr - sec_end_x.width / 2.0
        ye = -sec_end_x.depth / 2.0
        sections.append(PlacedSection(sec_end_x, xe, ye, 0.0, fl_end_x))

        # 2. Вертикальное крыло вниз (-Y) с каскадным понижением к югу на 2-4 этажа
        K_y = num_mid_y + 1
        y_curr = -dc
        wing_start_y = fl_cor
        drop_ly = min(4, max(2, wing_start_y - min_wing_floors)) if wing_start_y > min_wing_floors else min(2, max(0, wing_start_y - 1))
        for j in range(num_mid_y):
            if cascade_floors:
                step_ratio = (j + 1) / K_y
                fl_j = round(wing_start_y - step_ratio * drop_ly)
                fl_j = max(1, min(wing_start_y, fl_j))
                sec_j = self._find_best_section(mid_candidates, fl_j) or middle
            else:
                sec_j = middle
                fl_j = floors
            fl_j = self._clamp_floors(sec_j, fl_j)

            xv = -sec_j.depth / 2.0
            yv = y_curr - sec_j.width / 2.0
            sections.append(PlacedSection(sec_j, xv, yv, 90.0, fl_j))
            y_curr -= sec_j.width

        if cascade_floors:
            fl_end_y = max(1, wing_start_y - drop_ly)
            sec_end_y = self._find_best_section(end_candidates, fl_end_y) or end
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
            if self._is_bcr_reached(buildings, placement_config):
                break
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
        if not self._is_bcr_reached(buildings, placement_config):
            self._fill_remaining_space(
                buildable, buildings, angle, middle, end, floors, placement_config
            )

        return self._enforce_normative_limits(buildings, placement_config)

    # ─────────────────────────────────────────────────────────────────
    # Стратегии: TOWER, U_SHAPE, L_SHAPE, LINEAR
    # ─────────────────────────────────────────────────────────────────

    def _create_single_tower(
        self,
        x: float,
        y: float,
        angle: float,
        tower_sec: SectionType,
        floors: int,
    ) -> Building:
        """Создать отдельное башенное (точечное) 1-секционное здание."""
        fl = self._clamp_floors(tower_sec, floors)
        placed_sec = PlacedSection(
            section_type=tower_sec,
            x=x,
            y=y,
            angle=angle,
            floors=fl,
            floor_height=self._current_floor_height,
            ground_floor_height=self._current_ground_floor_height,
        )
        return Building(sections=[placed_sec], typology="TOWER")

    def _generate_tower_layout(
        self,
        buildable: Polygon,
        angle: float,
        tower_sec: SectionType,
        floors: int,
        placement_config: PlacementConfig,
    ) -> list[Building]:
        """Генерация регулярной / шахматной точечной (башенной) застройки.

        Размещает отдельно стоящие башни с соблюдением требований инсоляции,
        освещенности и противопожарных разрывов.
        """
        length, width, _ = get_obb_dimensions(buildable)
        centroid = buildable.centroid

        fire_gap = self._get_fire_gap(floors)
        h = floors * self._current_floor_height
        insol_factor = float(self.config.get("insolation_factor", 0.5))
        req_gap = max(fire_gap, h * insol_factor, 24.0)

        step_x = tower_sec.width + req_gap
        step_y = tower_sec.depth + req_gap

        cols = max(1, int((length + req_gap) / step_x))
        rows = max(1, int((width + req_gap) / step_y))

        span_x = (cols - 1) * step_x
        span_y = (rows - 1) * step_y
        start_ox = -span_x / 2.0
        start_oy = -span_y / 2.0

        rad_p = math.radians(angle)
        rad_n = math.radians(angle + 90.0)
        ux = (math.cos(rad_p), math.sin(rad_p))
        uy = (math.cos(rad_n), math.sin(rad_n))

        patterns = ["staggered", "grid"]
        best_buildings: list[Building] = []

        for pattern in patterns:
            cand_buildings: list[Building] = []
            for r in range(rows):
                if self._is_bcr_reached(cand_buildings, placement_config):
                    break
                if placement_config.cascade_floors and rows > 1:
                    row_fl = max(
                        placement_config.min_wing_floors,
                        floors - (rows - 1 - r) * 3,
                    )
                else:
                    row_fl = floors

                x_offset = (step_x * 0.5) if (pattern == "staggered" and r % 2 == 1 and cols > 1) else 0.0

                for c in range(cols):
                    if self._is_bcr_reached(cand_buildings, placement_config):
                        break
                    ox = start_ox + c * step_x + x_offset
                    oy = start_oy + r * step_y
                    px = centroid.x + ox * ux[0] + oy * uy[0]
                    py = centroid.y + ox * ux[1] + oy * uy[1]

                    cand_b = self._create_single_tower(px, py, angle, tower_sec, row_fl)
                    if self._fits_in_buildable(cand_b) and self._check_constraints(
                        cand_b, cand_buildings, placement_config
                    ):
                        cand_buildings.append(cand_b)

            if len(cand_buildings) > len(best_buildings):
                best_buildings = cand_buildings

        if not best_buildings:
            cand_single = self._create_single_tower(centroid.x, centroid.y, angle, tower_sec, floors)
            if self._fits_in_buildable(cand_single):
                best_buildings.append(cand_single)

        return self._enforce_normative_limits(best_buildings, placement_config)

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
            if self._is_bcr_reached(buildings, placement_config):
                break
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

        if not self._is_bcr_reached(buildings, placement_config):
            self._fill_remaining_space(
                buildable, buildings, angle, middle, end, floors, placement_config
            )
        return self._enforce_normative_limits(buildings, placement_config)

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
            if self._is_bcr_reached(buildings, placement_config):
                break
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

        if not self._is_bcr_reached(buildings, placement_config):
            self._fill_remaining_space(
                buildable, buildings, angle, middle, end, floors, placement_config
            )
        return self._enforce_normative_limits(buildings, placement_config)

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

        for r_idx, line in enumerate(row_lines):
            if self._is_bcr_reached(buildings, placement_config):
                break
            cands = self._create_linears_on_line(
                line, middle, end, floors, angle, placement_config, line_index=r_idx
            )
            for b in cands:
                if self._is_bcr_reached(buildings, placement_config):
                    break
                if self._check_constraints(b, buildings, placement_config):
                    buildings.append(b)

        return self._enforce_normative_limits(buildings, placement_config)

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

    def _find_middle_packing(
        self,
        avail_width: float,
        candidate_sections: list[SectionType],
        max_middle_secs: int,
        target_floors: int | None = None,
        preferred_lead: SectionType | None = None,
    ) -> list[SectionType]:
        """Подобрать оптимальный набор рядовых секций, максимально заполняющий доступную ширину."""
        if avail_width <= 0 or max_middle_secs <= 0 or not candidate_sections:
            return []

        # Фильтруем рядовые секции подходящей ширины
        valid = [s for s in candidate_sections if s.width <= avail_width and s.category.upper() == "MIDDLE"]
        if not valid:
            return []

        # Формируем список кандидатов для первой секции (приоритет ведущей секции)
        primaries = list(valid)
        if preferred_lead and preferred_lead in valid:
            primaries = [preferred_lead] + [s for s in valid if s != preferred_lead]

        best_pack: list[SectionType] = []
        best_w = 0.0
        best_fl_diff = float("inf")
        best_has_lead = False

        for primary in primaries:
            pack: list[SectionType] = []
            cur_w = 0.0
            while len(pack) < max_middle_secs and (cur_w + primary.width) <= avail_width:
                pack.append(primary)
                cur_w += primary.width

            for alt in sorted(valid, key=lambda s: s.width, reverse=True):
                while len(pack) < max_middle_secs and (cur_w + alt.width) <= avail_width:
                    pack.append(alt)
                    cur_w += alt.width

            if not pack:
                continue

            has_lead = bool(preferred_lead and preferred_lead in pack)
            if target_floors is not None:
                fl_diff = sum(abs(s.default_floors - target_floors) for s in pack) / len(pack)
            else:
                fl_diff = 0.0

            is_better = False
            if not best_pack:
                is_better = True
            elif cur_w > (best_w + 8.0):
                is_better = True
            elif abs(cur_w - best_w) <= 8.0:
                if has_lead and not best_has_lead:
                    is_better = True
                elif has_lead == best_has_lead:
                    if fl_diff < (best_fl_diff - 1.0):
                        is_better = True
                    elif abs(fl_diff - best_fl_diff) <= 1.0 and cur_w > best_w:
                        is_better = True

            if is_better:
                best_pack = pack
                best_w = cur_w
                best_fl_diff = fl_diff
                best_has_lead = has_lead

        return best_pack

    def _create_single_linear(
        self,
        center_line: LineString,
        middle: SectionType,
        end: SectionType,
        floors: int,
        angle: float,
        placement_config: PlacementConfig,
        preferred_lead: SectionType | None = None,
    ) -> Building | None:
        """Создать один соразмерный линейный корпус на отрезке линии."""
        line_len = center_line.length
        min_len = end.width * 2
        if line_len < min_len:
            return None

        avail = line_len - end.width * 2
        max_mid = max(0, placement_config.max_sections_per_building - 2)

        # Кандидаты в рядовые секции: сначала активный пул, затем библиотека
        pref_pool = getattr(self, "_middle_pool", [middle])
        lead_sec = preferred_lead
        if lead_sec is None:
            lead_sec = (
                pref_pool[getattr(self, "_placed_building_count", 0) % len(pref_pool)]
                if pref_pool
                else middle
            )

        cand_middles = list(pref_pool)
        if not getattr(self, "_has_preferred_sections", False):
            for s in self.library.get_middle_sections():
                if s not in cand_middles:
                    cand_middles.append(s)

        chosen_middles = self._find_middle_packing(
            avail, cand_middles, max_mid, target_floors=floors, preferred_lead=lead_sec
        )

        total_secs = len(chosen_middles) + 2
        if total_secs < placement_config.min_sections_per_building:
            return None

        midpoint = center_line.interpolate(line_len / 2.0)
        local_secs = self._build_linear_local(
            middle, end, floors, chosen_middles,
            cascade_floors=placement_config.cascade_floors,
            min_wing_floors=placement_config.min_wing_floors,
        )
        placed_secs = self._transform_sections(local_secs, midpoint.x, midpoint.y, angle)
        building = Building(sections=placed_secs, typology="LINEAR")

        if not self._fits_in_buildable(building):
            while len(chosen_middles) > 0:
                chosen_middles.pop()
                if (len(chosen_middles) + 2) < placement_config.min_sections_per_building:
                    return None
                local_secs = self._build_linear_local(
                    middle, end, floors, chosen_middles,
                    cascade_floors=placement_config.cascade_floors,
                    min_wing_floors=placement_config.min_wing_floors,
                )
                placed_secs = self._transform_sections(local_secs, midpoint.x, midpoint.y, angle)
                building = Building(sections=placed_secs, typology="LINEAR")
                if self._fits_in_buildable(building):
                    self._placed_building_count = getattr(self, "_placed_building_count", 0) + 1
                    return building
            return None

        self._placed_building_count = getattr(self, "_placed_building_count", 0) + 1
        return building

    def _create_linears_on_line(
        self,
        center_line: LineString,
        middle: SectionType,
        end: SectionType,
        floors: int,
        angle: float,
        placement_config: PlacementConfig,
        line_index: int = 0,
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

        pref_pool = getattr(self, "_middle_pool", [middle])
        pool_len = len(pref_pool) if pref_pool else 1

        # Если линия короче допустимой длины одного дома, ставим один дом
        if line_len <= max_bldg_len:
            lead_idx = line_index % pool_len
            lead_sec = pref_pool[lead_idx] if pref_pool else middle
            b = self._create_single_linear(
                center_line, middle, end, floors, angle, placement_config, preferred_lead=lead_sec
            )
            return [b] if b is not None else []

        # Соразмерное деление длинной линии (<= max_bldg_len) с разрывами для проездов
        buildings: list[Building] = []
        d_curr = 0.0
        bldg_in_line = 0

        while d_curr < (line_len - min_len):
            if self._is_bcr_reached(buildings, placement_config):
                break
            rem_len = line_len - d_curr
            cur_max = min(max_bldg_len, rem_len)
            if cur_max < min_len:
                break

            p_start = center_line.interpolate(d_curr)
            p_end = center_line.interpolate(d_curr + cur_max)
            seg = LineString([p_start, p_end])

            lead_idx = (line_index + bldg_in_line) % pool_len
            lead_sec = pref_pool[lead_idx] if pref_pool else middle

            b = self._create_single_linear(
                seg, middle, end, floors, angle, placement_config, preferred_lead=lead_sec
            )
            if b is None:
                d_curr += passage_gap
                continue

            # Определяем фактическую длину построенного корпуса вдоль линии
            b_coords = list(b.footprint.exterior.coords)
            rad_ang = math.radians(angle)
            dir_vec = (math.cos(rad_ang), math.sin(rad_ang))
            projs = [c[0] * dir_vec[0] + c[1] * dir_vec[1] for c in b_coords]
            actual_len = max(min_len, max(projs) - min(projs))

            buildings.append(b)
            bldg_in_line += 1
            d_curr += actual_len + passage_gap

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
        if self._is_bcr_reached(buildings, placement_config):
            return
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

        # Дополнительно: размещаем башни-акценты на оставшихся свободных пятнах
        if getattr(placement_config, "allow_towers_in_mixed", True) and not self._is_bcr_reached(buildings, placement_config):
            tower_secs = self.library.get_tower_sections()
            if tower_secs:
                tower_sec = self._find_best_section(tower_secs, floors) or tower_secs[0]
                t_parts = remaining.geoms if isinstance(remaining, MultiPolygon) else [remaining]
                for p in t_parts:
                    if p.is_empty or p.area < (tower_sec.width * tower_sec.depth * 1.05):
                        continue
                    pt = p.centroid
                    cand_tower = self._create_single_tower(pt.x, pt.y, angle, tower_sec, floors)
                    if self._fits_in_buildable(cand_tower) and self._check_constraints(
                        cand_tower, buildings, placement_config
                    ):
                        buildings.append(cand_tower)
                        occupied = unary_union([occupied, cand_tower.footprint.buffer(min_clearance)])
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
    ) -> dict[str, Any] | None:
        """Выбрать секции для расстановки с учетом этажности и предпочтений."""
        target_fl = placement_config.target_floors

        if placement_config.preferred_section_ids:
            sections: dict[str, Any] = {}
            pref_middles: list[SectionType] = []
            pref_ends: list[SectionType] = []
            pref_corners: list[SectionType] = []
            pref_towers: list[SectionType] = []

            for sid in placement_config.preferred_section_ids:
                s = self.library.get_by_id(sid)
                if s:
                    cat = s.category.upper()
                    if cat == "MIDDLE":
                        pref_middles.append(s)
                    elif cat == "END":
                        pref_ends.append(s)
                    elif cat == "CORNER":
                        pref_corners.append(s)
                    elif cat == "TOWER" or s.id.lower().startswith("tower"):
                        pref_towers.append(s)

            if pref_middles:
                sections["middle"] = self._find_best_section(pref_middles, target_fl)
                sections["middle_pool"] = pref_middles
            else:
                sections["middle"] = self._find_best_section(self.library.get_middle_sections(), target_fl)
                sections["middle_pool"] = self.library.get_middle_sections()

            if pref_ends:
                sections["end"] = self._find_best_section(pref_ends, target_fl)
                sections["end_pool"] = pref_ends
            else:
                best_end = self._find_best_section(self.library.get_end_sections(), target_fl)
                sections["end"] = best_end if best_end else sections.get("middle")
                sections["end_pool"] = self.library.get_end_sections()

            if pref_corners:
                sections["corner"] = self._find_best_section(pref_corners, target_fl)
                sections["corner_pool"] = pref_corners
            else:
                best_cor = self._find_best_section(self.library.get_corner_sections(), target_fl)
                sections["corner"] = best_cor if best_cor else sections.get("middle")
                sections["corner_pool"] = self.library.get_corner_sections()

            if pref_towers:
                sections["tower"] = self._find_best_section(pref_towers, target_fl)
                sections["tower_pool"] = pref_towers
            else:
                towers = self.library.get_tower_sections()
                best_tower = self._find_best_section(towers, target_fl) if towers else None
                sections["tower"] = best_tower if best_tower else sections.get("middle")
                sections["tower_pool"] = towers

            return sections if ("middle" in sections or "tower" in sections) else None

        middles = self.library.get_middle_sections()
        ends = self.library.get_end_sections()
        corners = self.library.get_corner_sections()
        towers = self.library.get_tower_sections()

        if not middles and not towers:
            return None

        best_middle = self._find_best_section(middles, target_fl) if middles else (towers[0] if towers else None)
        best_end = self._find_best_section(ends, target_fl) if ends else best_middle
        best_corner = self._find_best_section(corners, target_fl) if corners else best_middle
        best_tower = self._find_best_section(towers, target_fl) if towers else best_middle

        result: dict[str, Any] = {
            "middle": best_middle,
            "end": best_end if best_end else best_middle,
            "corner": best_corner if best_corner else best_middle,
            "tower": best_tower if best_tower else best_middle,
            "middle_pool": middles,
            "end_pool": ends,
            "corner_pool": corners,
            "tower_pool": towers,
        }
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
        """Проверить нормативные противопожарные и инсоляционные расстояния, а также лимит BCR."""
        if placement_config is not None:
            if len(new_building.sections) > placement_config.max_sections_per_building:
                return False
            if new_building.typology != "TOWER" and len(new_building.sections) < placement_config.min_sections_per_building:
                return False

            raw_bcr = placement_config.max_bcr if placement_config.max_bcr is not None else self.config.get("max_bcr")
            if raw_bcr is not None and getattr(self.site, "area", None) and self.site.area > 0:
                max_bcr = float(raw_bcr)
                cur_fp = sum(b.total_building_area for b in existing_buildings) + new_building.total_building_area
                if cur_fp > self.site.area * max_bcr * 1.005:
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
