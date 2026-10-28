"""Квартально-периметральный генератор застройки (R2-style).

Реализует формирование улично-дорожного каркаса, деление территории на урбан-блоки
и гибкую периметральную посадку секций с поддержкой различных конфигураций дворов
(П-образные с ориентацией на любую сторону света, замкнутые с арками, двухсторонние).
"""

from __future__ import annotations

import math
from typing import Any

from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union

from src.core.buildable_area import get_oriented_bbox
from src.library.section_library import SectionLibrary
from src.models.building import Building, PlacedSection
from src.models.section import SectionType
from src.models.site import Site


class PerimeterPlacementEngine:
    """Движок квартально-периметральной расстановки зданий в урбан-блоках."""

    def __init__(
        self,
        site: Site,
        library: SectionLibrary,
        config: dict[str, Any],
    ) -> None:
        """Инициализировать движок периметральной расстановки."""
        self.site = site
        self.library = library
        self.config = config

    def split_into_urban_blocks(
        self,
        buildable_area: Polygon,
        angle: float,
        target_block_size: float = 100.0,
        road_width: float = 16.0,
        min_block_area: float = 2000.0,
    ) -> list[Polygon]:
        """Разбить допустимую зону застройки на кварталы (урбан-блоки) через дорожную сеть."""
        poly_rot = rotate(buildable_area, -angle, origin=(0, 0))
        minx, miny, maxx, maxy = poly_rot.bounds
        len_x = maxx - minx
        len_y = maxy - miny

        # Адаптивное число делений в зависимости от заданного размера блока
        threshold_ratio = 1.20
        nx = max(1, math.floor(len_x / target_block_size + 0.35)) if len_x >= (target_block_size * threshold_ratio) else 1
        ny = max(1, math.floor(len_y / target_block_size + 0.35)) if len_y >= (target_block_size * threshold_ratio) else 1

        if nx == 1 and ny == 1:
            return [buildable_area]

        cuts = []
        if nx > 1:
            step_x = len_x / nx
            for i in range(1, nx):
                cx = minx + i * step_x
                r_box = box(
                    cx - road_width / 2.0,
                    miny - 100.0,
                    cx + road_width / 2.0,
                    maxy + 100.0,
                )
                cuts.append(r_box)

        if ny > 1:
            step_y = len_y / ny
            for j in range(1, ny):
                cy = miny + j * step_y
                r_box = box(
                    minx - 100.0,
                    cy - road_width / 2.0,
                    maxx + 100.0,
                    cy + road_width / 2.0,
                )
                cuts.append(r_box)

        roads_union = unary_union(cuts)
        diff = poly_rot.difference(roads_union)

        blocks_rot: list[Polygon] = []
        if diff.geom_type == "Polygon":
            if diff.area >= min_block_area:
                blocks_rot.append(diff)
        elif diff.geom_type == "MultiPolygon":
            for p in diff.geoms:
                if p.area >= min_block_area:
                    blocks_rot.append(p)

        if not blocks_rot:
            return [buildable_area]

        # Возвращаем блоки в исходную систему координат участка
        blocks = [rotate(p, angle, origin=(0, 0)) for p in blocks_rot]
        return blocks

    def _get_interior_box(
        self, poly: Polygon, margin: float = 1.0
    ) -> tuple[float, float, float, float]:
        """Найти максимальный внутренний прямоугольник для надежной посадки контура."""
        p = poly.buffer(-margin)
        if p.is_empty:
            p = poly
        minx, miny, maxx, maxy = p.bounds
        step = 1.0
        for _ in range(60):
            b = box(minx, miny, maxx, maxy)
            diff = b.difference(p)
            if diff.area < 10.0:
                break
            reductions = []
            if maxy - miny > 35:
                reductions.append(('top', box(minx, miny, maxx, maxy - step).difference(p).area))
                reductions.append(('bot', box(minx, miny + step, maxx, maxy).difference(p).area))
            if maxx - minx > 35:
                reductions.append(('left', box(minx + step, miny, maxx, maxy).difference(p).area))
                reductions.append(('right', box(minx, miny, maxx - step, maxy).difference(p).area))
            if not reductions:
                break
            best_side, _ = min(reductions, key=lambda x: x[1])
            if best_side == 'top':
                maxy -= step
            elif best_side == 'bot':
                miny += step
            elif best_side == 'left':
                minx += step
            elif best_side == 'right':
                maxx -= step
        return minx, miny, maxx, maxy

    def _find_best_combo(
        self,
        candidates: list[SectionType],
        target_len: float,
    ) -> list[SectionType]:
        """Жадный подбор комбинации секций под заданную длину фасада."""
        if not candidates or target_len < min(s.width for s in candidates):
            return []

        cand_sorted = sorted(candidates, key=lambda s: s.width, reverse=True)
        res: list[SectionType] = []
        rem = target_len
        min_w = min(s.width for s in candidates)

        while rem >= min_w:
            best_s = None
            for s in cand_sorted:
                if s.width <= rem + 1.5:
                    best_s = s
                    break
            if best_s is None:
                break
            res.append(best_s)
            rem -= best_s.width

        return res

    def _build_block_buildings(
        self,
        block_rot: Polygon,
        angle: float,
        middle_pool: list[SectionType],
        corner_sec: SectionType,
        end_sec: SectionType,
        target_floors: int,
        cascade_floors: bool = True,
        min_wing_floors: int = 8,
        courtyard_orientation: str = "SOUTH",
        courtyard_layout_type: str = "U_SHAPE",
        floor_height: float = 3.0,
        ground_floor_height: float | None = None,
    ) -> list[Building]:
        """Сформировать здания квартала по периметру урбан-блока с учетом выбранной конфигурации."""
        minx, miny, maxx, maxy = self._get_interior_box(block_rot)
        len_x = maxx - minx
        len_y = maxy - miny

        wc, dc = corner_sec.width, corner_sec.depth
        we = end_sec.width

        # Минимальные габариты для формирования периметра
        if len_x < (2 * wc + 5.0) or len_y < (dc + we + 5.0):
            return []

        sections: list[PlacedSection] = []
        fl_high = target_floors
        drop = min(4, max(2, fl_high - min_wing_floors)) if fl_high > min_wing_floors else min(2, max(0, fl_high - 1))
        fl_low = max(1, fl_high - drop)

        orient = courtyard_orientation.upper()
        layout_mode = courtyard_layout_type.upper()

        # =====================================================================
        # ВАРИАНТ 1: ДВУХСТОРОННИЙ ФРОНТ (LINEAR_WINGS - две параллельные пластины)
        # =====================================================================
        if layout_mode == "LINEAR_WINGS":
            # Две параллельные пластины вдоль длинной оси блока
            if len_y >= len_x:
                # Западная и Восточная пластины
                space_y = len_y - 2 * we
                mids_y = self._find_best_combo(middle_pool, space_y)
                
                # Западная
                curr_y = maxy
                sections.append(PlacedSection(end_sec, minx + end_sec.depth/2, curr_y - we/2, 90.0, fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))
                curr_y -= we
                for s in mids_y:
                    sections.append(PlacedSection(s, minx + s.depth/2, curr_y - s.width/2, 90.0, fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))
                    curr_y -= s.width
                sections.append(PlacedSection(end_sec, minx + end_sec.depth/2, curr_y - we/2, 90.0, fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))

                # Восточная
                curr_y2 = maxy
                sections.append(PlacedSection(end_sec, maxx - end_sec.depth/2, curr_y2 - we/2, 90.0, fl_low if cascade_floors else fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))
                curr_y2 -= we
                for s in mids_y:
                    sections.append(PlacedSection(s, maxx - s.depth/2, curr_y2 - s.width/2, 90.0, fl_low if cascade_floors else fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))
                    curr_y2 -= s.width
                sections.append(PlacedSection(end_sec, maxx - end_sec.depth/2, curr_y2 - we/2, 90.0, fl_low if cascade_floors else fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))
            else:
                # Северная и Южная пластины
                space_x = len_x - 2 * we
                mids_x = self._find_best_combo(middle_pool, space_x)
                
                # Северная (высокая)
                curr_x = minx
                sections.append(PlacedSection(end_sec, curr_x + we/2, maxy - end_sec.depth/2, 0.0, fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))
                curr_x += we
                for s in mids_x:
                    sections.append(PlacedSection(s, curr_x + s.width/2, maxy - s.depth/2, 0.0, fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))
                    curr_x += s.width
                sections.append(PlacedSection(end_sec, curr_x + we/2, maxy - end_sec.depth/2, 0.0, fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))

                # Южная (низкая для инсоляции)
                curr_x2 = minx
                sections.append(PlacedSection(end_sec, curr_x2 + we/2, miny + end_sec.depth/2, 0.0, fl_low if cascade_floors else fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))
                curr_x2 += we
                for s in mids_x:
                    sections.append(PlacedSection(s, curr_x2 + s.width/2, miny + s.depth/2, 0.0, fl_low if cascade_floors else fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))
                    curr_x2 += s.width
                sections.append(PlacedSection(end_sec, curr_x2 + we/2, miny + end_sec.depth/2, 0.0, fl_low if cascade_floors else fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))

        # =====================================================================
        # ВАРИАНТ 2: ЗАМКНУТЫЙ ПЕРИМЕТРАЛЬНЫЙ КВАРТАЛ (CLOSED)
        # =====================================================================
        elif layout_mode == "CLOSED":
            # Полноценный 4-сторонний замкнутый периметральный урбан-блок
            # 4 угла: NW (0°), NE (0°, flipped), SE (180°), SW (180°, flipped)
            space_x = len_x - 2 * wc
            space_y = len_y - 2 * dc
            mid_x_n = self._find_best_combo(middle_pool, space_x) if space_x >= 20.0 else []
            mid_y = self._find_best_combo(middle_pool, space_y) if space_y >= 20.0 else []

            north_total_w = 2 * wc + sum(s.width for s in mid_x_n)
            x_start = minx + max(0.0, (len_x - north_total_w) / 2.0)
            x_right_outer = x_start + north_total_w
            y_top = maxy
            y_bot = miny

            # 1. NW угол
            sections.append(
                PlacedSection(
                    corner_sec,
                    x_start + wc / 2.0,
                    y_top - dc / 2.0,
                    0.0,
                    fl_high,
                    floor_height=floor_height,
                    ground_floor_height=ground_floor_height,
                )
            )
            # 2. Северный фронт
            curr_x = x_start + wc
            for sec in mid_x_n:
                sections.append(
                    PlacedSection(
                        sec,
                        curr_x + sec.width / 2.0,
                        y_top - sec.depth / 2.0,
                        0.0,
                        fl_high,
                        floor_height=floor_height,
                        ground_floor_height=ground_floor_height,
                    )
                )
                curr_x += sec.width
            # 3. NE угол
            sections.append(
                PlacedSection(
                    corner_sec,
                    x_right_outer - wc / 2.0,
                    y_top - dc / 2.0,
                    0.0,
                    fl_high,
                    is_flipped=True,
                    floor_height=floor_height,
                    ground_floor_height=ground_floor_height,
                )
            )

            # 4. Восточное крыло
            curr_y = y_top - dc
            for sec in mid_y:
                sections.append(
                    PlacedSection(
                        sec,
                        x_right_outer - sec.depth / 2.0,
                        curr_y - sec.width / 2.0,
                        90.0,
                        fl_low if cascade_floors else fl_high,
                        floor_height=floor_height,
                        ground_floor_height=ground_floor_height,
                    )
                )
                curr_y -= sec.width

            # 5. SE угол
            sections.append(
                PlacedSection(
                    corner_sec,
                    x_right_outer - wc / 2.0,
                    y_bot + dc / 2.0,
                    180.0,
                    fl_low,
                    is_flipped=False,
                    floor_height=floor_height,
                    ground_floor_height=ground_floor_height,
                )
            )

            # 6. Южный фронт
            space_south = (x_right_outer - wc) - (x_start + wc)
            mid_x_s = self._find_best_combo(middle_pool, space_south) if space_south >= 20.0 else []
            curr_xs = x_start + wc
            for sec in mid_x_s:
                sections.append(
                    PlacedSection(
                        sec,
                        curr_xs + sec.width / 2.0,
                        y_bot + sec.depth / 2.0,
                        0.0,
                        fl_low,
                        floor_height=floor_height,
                        ground_floor_height=ground_floor_height,
                    )
                )
                curr_xs += sec.width

            # 7. SW угол
            sections.append(
                PlacedSection(
                    corner_sec,
                    x_start + wc / 2.0,
                    y_bot + dc / 2.0,
                    180.0,
                    fl_low,
                    is_flipped=True,
                    floor_height=floor_height,
                    ground_floor_height=ground_floor_height,
                )
            )

            # 8. Западное крыло
            curr_yw = y_top - dc
            for sec in mid_y:
                sections.append(
                    PlacedSection(
                        sec,
                        x_start + sec.depth / 2.0,
                        curr_yw - sec.width / 2.0,
                        90.0,
                        fl_high,
                        floor_height=floor_height,
                        ground_floor_height=ground_floor_height,
                    )
                )
                curr_yw -= sec.width

        # =====================================================================
        # ВАРИАНТ 3: П-ОБРАЗНЫЙ ДВОР (U_SHAPE) С ЧЕЛОВЕКО-СОРАЗМЕРНЫМИ ПРОПОРЦИЯМИ
        # =====================================================================
        else:
            if orient in ("NORTH",):
                # Раскрытие на Север (закрыт южный фронт)
                space_x = len_x - 2 * wc
                mid_x_secs = self._find_best_combo(middle_pool, space_x) if space_x >= 20.0 else []
                north_total_w = 2 * wc + sum(s.width for s in mid_x_secs)
                x_start = minx + max(0.0, (len_x - north_total_w) / 2.0)
                y_bot = miny

                w_court = north_total_w - 2 * end_sec.depth
                max_wing_depth = min((maxy - we) - (y_bot + dc), max(35.0, min(75.0, w_court * 1.0)))

                # SW угол
                sections.append(PlacedSection(corner_sec, x_start + wc / 2.0, y_bot + dc / 2.0, 180.0, fl_low, floor_height=floor_height, ground_floor_height=ground_floor_height))
                curr_x = x_start + wc
                for sec in mid_x_secs:
                    sections.append(PlacedSection(sec, curr_x + sec.width / 2.0, y_bot + sec.depth / 2.0, 0.0, fl_low, floor_height=floor_height, ground_floor_height=ground_floor_height))
                    curr_x += sec.width
                # SE угол
                sections.append(PlacedSection(corner_sec, curr_x + wc / 2.0, y_bot + dc / 2.0, 180.0, fl_low, is_flipped=True, floor_height=floor_height, ground_floor_height=ground_floor_height))

                # Западное крыло (идет на север)
                mid_y_l = self._find_best_combo(middle_pool, max_wing_depth) if max_wing_depth >= 20.0 else []
                curr_y = y_bot + dc
                for idx, sec in enumerate(mid_y_l):
                    fl_cur = min(fl_high, fl_low + (idx + 1) * 2) if cascade_floors else fl_high
                    sections.append(PlacedSection(sec, x_start + sec.depth / 2.0, curr_y + sec.width / 2.0, 90.0, fl_cur, floor_height=floor_height, ground_floor_height=ground_floor_height))
                    curr_y += sec.width
                sections.append(PlacedSection(end_sec, x_start + end_sec.depth / 2.0, curr_y + we / 2.0, 90.0, fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))

                # Восточное крыло (идет на север)
                x_right_outer = curr_x + wc
                curr_y_r = y_bot + dc
                for idx, sec in enumerate(mid_y_l):
                    fl_cur = min(fl_high, fl_low + (idx + 1) * 2) if cascade_floors else fl_high
                    sections.append(PlacedSection(sec, x_right_outer - sec.depth / 2.0, curr_y_r + sec.width / 2.0, 90.0, fl_cur, floor_height=floor_height, ground_floor_height=ground_floor_height))
                    curr_y_r += sec.width
                sections.append(PlacedSection(end_sec, x_right_outer - end_sec.depth / 2.0, curr_y_r + we / 2.0, 90.0, fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))

            elif orient in ("EAST", "WEST"):
                # Боковое раскрытие двора (Восток или Запад)
                is_open_east = (orient == "EAST")
                fl_back = fl_high

                space_y = len_y - 2 * wc
                mids_y = self._find_best_combo(middle_pool, space_y) if space_y >= 20.0 else []
                y_total = 2 * wc + sum(s.width for s in mids_y)
                y_start = miny + max(0.0, (len_y - y_total) / 2.0)

                w_court = y_total - 2 * end_sec.depth
                max_wing_x = min(len_x - dc - we, max(35.0, min(75.0, w_court * 1.0)))
                mids_top = self._find_best_combo(middle_pool, max_wing_x) if max_wing_x >= 20.0 else []

                # Углы и несущая стена
                xb = minx + dc / 2.0 if is_open_east else maxx - dc / 2.0
                sections.append(PlacedSection(corner_sec, minx + wc / 2.0 if is_open_east else maxx - wc / 2.0, y_start + wc / 2.0, 90.0, fl_back, floor_height=floor_height, ground_floor_height=ground_floor_height))
                curr_y = y_start + wc
                for s in mids_y:
                    sections.append(PlacedSection(s, xb, curr_y + s.width / 2.0, 90.0, fl_back, floor_height=floor_height, ground_floor_height=ground_floor_height))
                    curr_y += s.width
                sections.append(PlacedSection(corner_sec, minx + wc / 2.0 if is_open_east else maxx - wc / 2.0, curr_y + wc / 2.0, 90.0, fl_back, is_flipped=True, floor_height=floor_height, ground_floor_height=ground_floor_height))

                # Верхнее крыло
                curr_x = minx + dc if is_open_east else maxx - dc
                for s in mids_top:
                    cx = curr_x + s.width / 2.0 if is_open_east else curr_x - s.width / 2.0
                    sections.append(PlacedSection(s, cx, maxy - s.depth / 2.0, 0.0, fl_high, floor_height=floor_height, ground_floor_height=ground_floor_height))
                    curr_x = curr_x + s.width if is_open_east else curr_x - s.width
                cx_end = curr_x + we / 2.0 if is_open_east else curr_x - we / 2.0
                sections.append(PlacedSection(end_sec, cx_end, maxy - end_sec.depth / 2.0, 0.0, fl_low, floor_height=floor_height, ground_floor_height=ground_floor_height))

                # Нижнее крыло
                curr_x_bot = minx + dc if is_open_east else maxx - dc
                for s in mids_top:
                    cx = curr_x_bot + s.width / 2.0 if is_open_east else curr_x_bot - s.width / 2.0
                    sections.append(PlacedSection(s, cx, miny + s.depth / 2.0, 0.0, fl_low, floor_height=floor_height, ground_floor_height=ground_floor_height))
                    curr_x_bot = curr_x_bot + s.width if is_open_east else curr_x_bot - s.width
                cx_end2 = curr_x_bot + we / 2.0 if is_open_east else curr_x_bot - we / 2.0
                sections.append(PlacedSection(end_sec, cx_end2, miny + end_sec.depth / 2.0, 0.0, fl_low, floor_height=floor_height, ground_floor_height=ground_floor_height))

            else:
                # По умолчанию: РАСКРЫТИЕ НА ЮГ (макс. инсоляция)
                space_x = len_x - 2 * wc

                # Если блок слишком узкий для двух параллельных крыльев (< 24 м чистого двора),
                # строим просторный Г-образный корпус (L-Shape), чтобы секции не смотрели "окна в окна":
                if space_x < 24.0:
                    mid_x_secs = self._find_best_combo(middle_pool, len_x - wc - we)
                    north_total_w = wc + we + sum(s.width for s in mid_x_secs)
                    x_start = minx + max(0.0, (len_x - north_total_w) / 2.0)
                    y_top = maxy

                    # NW угол
                    sections.append(
                        PlacedSection(
                            corner_sec,
                            x_start + wc / 2.0,
                            y_top - dc / 2.0,
                            0.0,
                            fl_high,
                            floor_height=floor_height,
                            ground_floor_height=ground_floor_height,
                        )
                    )
                    curr_x = x_start + wc
                    for sec in mid_x_secs:
                        sections.append(
                            PlacedSection(
                                sec,
                                curr_x + sec.width / 2.0,
                                y_top - sec.depth / 2.0,
                                0.0,
                                fl_high,
                                floor_height=floor_height,
                                ground_floor_height=ground_floor_height,
                            )
                        )
                        curr_x += sec.width
                    sections.append(
                        PlacedSection(
                            end_sec,
                            curr_x + we / 2.0,
                            y_top - end_sec.depth / 2.0,
                            0.0,
                            fl_high,
                            floor_height=floor_height,
                            ground_floor_height=ground_floor_height,
                        )
                    )

                    # Только Западное крыло (соразмерной глубины)
                    max_wing = min((y_top - dc) - (miny + we), 65.0)
                    mid_y_l = self._find_best_combo(middle_pool, max_wing) if max_wing >= 20.0 else []
                    curr_y = y_top - dc
                    for idx, sec in enumerate(mid_y_l):
                        fl_cur = min_wing_floors if cascade_floors else fl_high
                        sections.append(
                            PlacedSection(
                                sec,
                                x_start + sec.depth / 2.0,
                                curr_y - sec.width / 2.0,
                                90.0,
                                fl_cur,
                                floor_height=floor_height,
                                ground_floor_height=ground_floor_height,
                            )
                        )
                        curr_y -= sec.width
                    sections.append(
                        PlacedSection(
                            end_sec,
                            x_start + end_sec.depth / 2.0,
                            curr_y - we / 2.0,
                            90.0,
                            min_wing_floors,
                            floor_height=floor_height,
                            ground_floor_height=ground_floor_height,
                        )
                    )

                else:
                    # Полноценная П-образная скоба с широким пропорциональным двором
                    mid_x_secs = self._find_best_combo(middle_pool, space_x)
                    north_total_w = 2 * wc + sum(s.width for s in mid_x_secs)
                    x_offset = max(0.0, (len_x - north_total_w) / 2.0)
                    x_start = minx + x_offset
                    y_top = maxy
                    x_right_outer = x_start + north_total_w

                    w_court = north_total_w - 2 * end_sec.depth
                    # Глубина крыльев соразмерна ширине двора (не более 1.05 * w_court, максимум 75 м)
                    max_wing_depth = min((y_top - dc) - (miny + we), max(35.0, min(75.0, w_court * 1.0)))
                    mid_y_l = self._find_best_combo(middle_pool, max_wing_depth) if max_wing_depth >= 20.0 else []

                    # NW угол
                    sections.append(
                        PlacedSection(
                            corner_sec,
                            x_start + wc / 2.0,
                            y_top - dc / 2.0,
                            0.0,
                            fl_high,
                            floor_height=floor_height,
                            ground_floor_height=ground_floor_height,
                        )
                    )
                    curr_x = x_start + wc
                    for sec in mid_x_secs:
                        sections.append(
                            PlacedSection(
                                sec,
                                curr_x + sec.width / 2.0,
                                y_top - sec.depth / 2.0,
                                0.0,
                                fl_high,
                                floor_height=floor_height,
                                ground_floor_height=ground_floor_height,
                            )
                        )
                        curr_x += sec.width
                    # NE угол
                    sections.append(
                        PlacedSection(
                            corner_sec,
                            curr_x + wc / 2.0,
                            y_top - dc / 2.0,
                            0.0,
                            fl_high,
                            is_flipped=True,
                            floor_height=floor_height,
                            ground_floor_height=ground_floor_height,
                        )
                    )

                    # Западное крыло
                    curr_y = y_top - dc
                    n_mid_l = len(mid_y_l)
                    for idx, sec in enumerate(mid_y_l):
                        if cascade_floors and fl_high > min_wing_floors:
                            ratio = (idx + 1) / (n_mid_l + 1)
                            fl_cur = round(fl_high - ratio * (fl_high - min_wing_floors))
                        else:
                            fl_cur = fl_high
                        fl_cur = max(min_wing_floors, min(sec.max_floors, fl_cur))
                        sections.append(
                            PlacedSection(
                                sec,
                                x_start + sec.depth / 2.0,
                                curr_y - sec.width / 2.0,
                                90.0,
                                fl_cur,
                                floor_height=floor_height,
                                ground_floor_height=ground_floor_height,
                            )
                        )
                        curr_y -= sec.width

                    fl_end_l = min_wing_floors if cascade_floors else fl_high
                    sections.append(
                        PlacedSection(
                            end_sec,
                            x_start + end_sec.depth / 2.0,
                            curr_y - we / 2.0,
                            90.0,
                            fl_end_l,
                            floor_height=floor_height,
                            ground_floor_height=ground_floor_height,
                        )
                    )

                    # Восточное крыло
                    curr_y_r = y_top - dc
                    n_mid_r = len(mid_y_l)
                    for idx, sec in enumerate(mid_y_l):
                        if cascade_floors and fl_high > min_wing_floors:
                            ratio = (idx + 1) / (n_mid_r + 1)
                            fl_cur = round(fl_high - ratio * (fl_high - min_wing_floors))
                        else:
                            fl_cur = fl_high
                        fl_cur = max(min_wing_floors, min(sec.max_floors, fl_cur))
                        sections.append(
                            PlacedSection(
                                sec,
                                x_right_outer - sec.depth / 2.0,
                                curr_y_r - sec.width / 2.0,
                                90.0,
                                fl_cur,
                                floor_height=floor_height,
                                ground_floor_height=ground_floor_height,
                            )
                        )
                        curr_y_r -= sec.width

                    fl_end_r = min_wing_floors if cascade_floors else fl_high
                    sections.append(
                        PlacedSection(
                            end_sec,
                            x_right_outer - end_sec.depth / 2.0,
                            curr_y_r - we / 2.0,
                            90.0,
                            fl_end_r,
                            floor_height=floor_height,
                            ground_floor_height=ground_floor_height,
                        )
                    )

        # Возвращаем секции с обратным поворотом на угол участка
        rotated_sections: list[PlacedSection] = []
        rad = math.radians(angle)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        for s in sections:
            rx = s.x * cos_a - s.y * sin_a
            ry = s.x * sin_a + s.y * cos_a
            total_angle = (s.angle + angle) % 360.0
            rotated_sections.append(
                PlacedSection(
                    s.section_type,
                    rx,
                    ry,
                    total_angle,
                    s.floors,
                    is_flipped=s.is_flipped,
                    floor_height=s.floor_height,
                    ground_floor_height=s.ground_floor_height,
                )
            )

        if not rotated_sections:
            return []

        building = Building(sections=rotated_sections, typology="COURTYARD")
        return [building]

    def generate(
        self,
        buildable_area: Polygon,
        angle: float,
        middle_pool: list[SectionType],
        corner_pool: list[SectionType],
        end_pool: list[SectionType],
        target_floors: int,
        config: Any,
    ) -> list[Building]:
        """Главный метод генерации застройки в режиме урбан-блоков."""
        def _get_val(key: str, default: Any = None) -> Any:
            if isinstance(config, dict):
                return config.get(key, default)
            return getattr(config, key, default)

        target_size = _get_val("urban_block_size", 100.0) or 100.0
        road_width = _get_val("internal_road_width", 16.0) or 16.0
        cascade = _get_val("cascade_floors", True)
        min_wing_fl = _get_val("min_wing_floors", 8) or 8
        court_orient = _get_val("courtyard_orientation", "SOUTH") or "SOUTH"
        layout_style = _get_val("perimeter_layout_style", "U_SHAPE") or "U_SHAPE"

        fl_h = float(_get_val("floor_height", 3.0) or 3.0)
        gr_h = _get_val("ground_floor_height", None)

        raw_bcr = _get_val("max_bcr", None)
        if raw_bcr is None and isinstance(self.config, dict):
            raw_bcr = self.config.get("max_bcr")
        max_bcr = float(raw_bcr) if raw_bcr is not None and float(raw_bcr) > 0 else None
        site_area = getattr(self.site, "area", 0.0) or 0.0
        allowed_fp = site_area * max_bcr if max_bcr and site_area > 0 else None

        corner_sec = corner_pool[0] if corner_pool else self.library.get_corner_sections()[0]
        end_sec = end_pool[0] if end_pool else self.library.get_end_sections()[0]

        # 1. Деление на урбан-блоки с учетом целевого размера
        blocks = self.split_into_urban_blocks(
            buildable_area,
            angle=angle,
            target_block_size=target_size,
            road_width=road_width,
        )

        all_buildings: list[Building] = []

        # 2. Посадка зданий в каждый блок
        for block in blocks:
            if allowed_fp is not None:
                cur_fp = sum(b.footprint.area for b in all_buildings)
                if cur_fp >= allowed_fp * 0.999:
                    break

            block_rot = rotate(block, -angle, origin=(0, 0))
            block_buildings = self._build_block_buildings(
                block_rot=block_rot,
                angle=angle,
                middle_pool=middle_pool,
                corner_sec=corner_sec,
                end_sec=end_sec,
                target_floors=target_floors,
                cascade_floors=cascade,
                min_wing_floors=min_wing_fl,
                courtyard_orientation=court_orient,
                courtyard_layout_type=layout_style,
                floor_height=fl_h,
                ground_floor_height=gr_h,
            )

            for bldg in block_buildings:
                if allowed_fp is not None:
                    cur_fp = sum(b.footprint.area for b in all_buildings)
                    if cur_fp + bldg.footprint.area > allowed_fp * 1.005:
                        continue

                if buildable_area.buffer(0.5).contains(bldg.footprint):
                    all_buildings.append(bldg)
                else:
                    inter = buildable_area.intersection(bldg.footprint)
                    if inter.area / bldg.footprint.area > 0.95:
                        all_buildings.append(bldg)

        return all_buildings
