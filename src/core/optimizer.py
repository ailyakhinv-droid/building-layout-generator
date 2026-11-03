"""Оптимизатор расстановки застройки.

Два режима работы:
1. Подбор параметров под целевые ТЭП.
2. Максимизация жилой площади при соблюдении нормативов.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.placement import (
    MIN_MERIDIAN_INSOLATION_ANGLE_DEG,
    PlacementConfig,
    PlacementEngine,
    angle_to_horizontal,
)
from src.core.tep_calculator import calculate_tep, check_normatives
from src.library.section_library import SectionLibrary
from src.models.building import Building
from src.models.site import Site
from src.models.tep import TEP


@dataclass
class OptimizationResult:
    """Результат оптимизации.

    Attributes:
        buildings: Список размещённых зданий.
        tep: Рассчитанные ТЭП.
        floors: Использованная этажность.
        normative_ok: Соблюдены ли все нормативы.
        score: Оценка варианта (для сравнения).
        typology: Использованная типология застройки.
        note: Пояснительное примечание к варианту.
        angle: Использованный угол поворота сетки.
        configs_tested: Количество протестированных конфигураций в оптимизаторе.
    """
    buildings: list[Building]
    tep: TEP
    floors: int
    normative_ok: bool
    score: float = 0.0
    typology: str = "AUTO"
    note: str = ""
    angle: float = 0.0
    configs_tested: int = 1


class Optimizer:
    """Оптимизатор расстановки застройки.

    Подбирает параметры расстановки (этажность, кол-во зданий)
    для достижения целевых ТЭП или максимизации площади.
    """

    def __init__(
        self,
        site: Site,
        library: SectionLibrary,
        config: dict[str, Any],
        base_placement_config: PlacementConfig | None = None,
    ) -> None:
        """Инициализировать оптимизатор.

        Args:
            site: Участок с вычисленной зоной застройки.
            library: Библиотека типовых секций.
            config: Нормативные параметры.
            base_placement_config: Базовые параметры расстановки (типология, ориентация).
        """
        self.site = site
        self.library = library
        self.config = config
        self.base_placement_config = base_placement_config or PlacementConfig()

    def optimize_for_target(
        self,
        target_tep: dict[str, float],
        max_iterations: int = 20,
    ) -> OptimizationResult:
        """Подобрать параметры для достижения целевых ТЭП.

        Поддерживаемые целевые показатели:
        - target_far: Целевая плотность застройки (FAR)
        - target_apartments: Целевое количество квартир
        - target_gfa: Целевая общая площадь (м²)

        Алгоритм:
        1. Начать со средней этажности.
        2. Сгенерировать расстановку.
        3. Сравнить ТЭП с целевыми.
        4. Скорректировать этажность.
        5. Повторять до сходимости.

        Args:
            target_tep: Словарь целевых показателей.
            max_iterations: Максимальное число итераций.

        Returns:
            Лучший найденный результат.
        """
        # Определяем целевой показатель
        target_far = target_tep.get("target_far")
        target_apts = target_tep.get("target_apartments")
        target_gfa = target_tep.get("target_gfa")

        # Генерируем варианты для текущей типологии
        variants = self.generate_variants(explore_typologies=False)
        if not variants:
            raise ValueError("Не удалось найти допустимый вариант расстановки.")

        def calc_diff(v: OptimizationResult) -> float:
            if target_far is not None:
                return abs(v.tep.far - target_far)
            elif target_apts is not None:
                return abs(v.tep.apartments_total - target_apts)
            elif target_gfa is not None:
                return abs(v.tep.total_gfa - target_gfa)
            return 0.0

        # Сортируем: сначала с минимальным отклонением, при близком — с соблюдением нормативов
        best = min(variants, key=lambda v: (calc_diff(v), 0 if v.normative_ok else 1))
        diff = calc_diff(best)

        metric_name = "FAR" if target_far is not None else ("квартир" if target_apts is not None else "GFA")
        target_val = target_far if target_far is not None else (target_apts if target_apts is not None else target_gfa)
        actual_val = best.tep.far if target_far is not None else (best.tep.apartments_total if target_apts is not None else best.tep.total_gfa)
        best.note = (
            f"Подобрано: {best.floors} эт. ({best.typology}), "
            f"{metric_name}={actual_val} "
            f"(цель: {target_val}, отклонение: {diff:.2f})."
        )
        return best

    def optimize_maximize(
        self,
        respect_normatives: bool = True,
        explore_typologies: bool = False,
        explore_angles: bool = True,
        angles: list[float] | None = None,
        progress_callback: Any = None,
    ) -> OptimizationResult:
        """Максимизировать жилую площадь («Выжать максимум по закону»).

        Args:
            respect_normatives: Если True — строго соблюдать нормативы (FAR <= max_far, BCR <= max_bcr,
                               пожарные разрывы, инсоляция, озеленение >= 25%).
                               Если False — абсолютная максимизация площади без отсечения по плотности.
            explore_typologies: Если True — перебрать все доступные типологии (AUTO, PERIMETER, TOWER, U_SHAPE, L_SHAPE, LINEAR).
            explore_angles: Если True — перебрать сетку углов поворота (0°, ±15°, ±25°).
            angles: Пользовательский список углов для перебора (опционально).
            progress_callback: Функция обратного вызова для отслеживания прогресса перебора на лету.

        Returns:
            Лучший найденный результат с подробной аудиторской запиской.
        """
        variants = self.generate_variants(
            explore_typologies=explore_typologies,
            explore_angles=explore_angles,
            angles=angles,
            progress_callback=progress_callback,
        )

        if not variants:
            raise ValueError("Не удалось сгенерировать ни одного варианта.")

        total_tested = len(variants)
        max_far_limit = float(self.config.get("max_far", 2.50))
        max_bcr_limit = float(self.config.get("max_bcr", 0.40))
        fire_e2e = float(self.config.get("fire_gap_end_to_end", 10.0))
        fire_par = float(self.config.get("fire_gap_parallel", 18.0))

        if respect_normatives:
            # Фильтруем строго нормативные варианты
            valid = [v for v in variants if v.normative_ok]
            if valid:
                # Победитель: максимальная жилая площадь при соблюдении 100% норм закона
                best = max(valid, key=lambda v: (v.tep.residential_area, -v.floors))
                best.configs_tested = total_tested
                best.note = (
                    f"⚡ ВЫЖАТ МАКСИМУМ ПО ЗАКОНУ (протестировано {total_tested} конфигураций):\n"
                    f"• Победитель: {best.floors} эт., типология «{best.typology}», угол {best.angle:+.1f}°\n"
                    f"• GFA: {best.tep.total_gfa:,.0f} м² | Жилая площадь: {best.tep.residential_area:,.0f} м² | Квартир: {best.tep.apartments_total}\n"
                    f"• FAR: {best.tep.far:.2f} (лимит ≤ {max_far_limit:.2f}) — 100% законно\n"
                    f"• BCR: {best.tep.bcr:.1%} (лимит ≤ {max_bcr_limit:.1%})\n"
                    f"• Противопожарные расстояния ({fire_e2e:.0f}м торцы, {fire_par:.0f}м фасады), инсоляция и отступы соблюдены."
                )
                return best
            else:
                # Если ни один не уложился в нормативы — берем с минимальными отклонениями
                best = max(variants, key=lambda v: v.score)
                best.configs_tested = total_tested
                best.note = (
                    f"⚠️ Все протестированные {total_tested} конфигураций превышают нормативные лимиты "
                    f"(FAR лимит {max_far_limit:.2f}). Выбран вариант с мин. отклонением: {best.floors} эт. ({best.typology}), "
                    f"FAR={best.tep.far:.2f}."
                )
                return best
        else:
            best = max(variants, key=lambda v: v.tep.residential_area)
            best.configs_tested = total_tested
            best.note = (
                f"⚡ Физический максимум без ограничений FAR/BCR (протестировано {total_tested} конфигураций):\n"
                f"• Выбрано: {best.floors} эт., типология «{best.typology}», угол {best.angle:+.1f}°\n"
                f"• GFA: {best.tep.total_gfa:,.0f} м² (FAR={best.tep.far:.2f})."
            )
            return best

    def find_absolute_maximum(
        self,
        explore_typologies: bool = True,
        explore_angles: bool = True,
    ) -> OptimizationResult:
        """Выжать абсолютный максимум из участка: перебор типологий, углов и этажности с отбором №1 строго по закону.

        Args:
            explore_typologies: Перебирать все типологии застройки.
            explore_angles: Перебирать сетку углов поворота.

        Returns:
            Победный вариант застройки с максимальной жилой площадью в рамках закона.
        """
        return self.optimize_maximize(
            respect_normatives=True,
            explore_typologies=explore_typologies,
            explore_angles=explore_angles,
        )

    def _get_floors_range(self, typology: str | None = None) -> range:
        """Определить допустимый диапазон этажности с учетом секций, типологии и высотных лимитов."""
        typ = (typology or self.base_placement_config.typology).upper()

        sections_to_check = []
        if self.base_placement_config.preferred_section_ids:
            for sid in self.base_placement_config.preferred_section_ids:
                s = self.library.get_by_id(sid)
                if s:
                    sections_to_check.append(s)

        if not sections_to_check:
            if typ in ("TOWER", "TOWERS", "POINT"):
                sections_to_check = self.library.get_tower_sections() or self.library.get_middle_sections()
            else:
                sections_to_check = self.library.get_middle_sections()

        if not sections_to_check:
            sections_to_check = self.library.get_all()

        if not sections_to_check:
            return range(1, 26)

        min_f = min(s.min_floors for s in sections_to_check)
        max_f = max(s.max_floors for s in sections_to_check)

        # Проверяем ограничение максимальной высоты здания (если задано)
        max_h = self.base_placement_config.max_building_height_m or self.config.get("max_building_height_m")
        floor_h = self.base_placement_config.floor_height or self.config.get("floor_height", 3.0)
        ground_h = (
            self.base_placement_config.ground_floor_height
            if self.base_placement_config.ground_floor_height is not None
            else self.config.get("ground_floor_height", floor_h)
        )
        if max_h and float(max_h) > 0:
            extra_first = max(0.0, float(ground_h) - float(floor_h))
            max_f_from_h = max(1, int((float(max_h) - extra_first) // float(floor_h)))
            max_f = min(max_f, max_f_from_h)

        # Ограничение по целевой этажности пользователя (потолок этажности)
        if self.base_placement_config.target_floors and self.base_placement_config.target_floors > 0:
            max_f = min(max_f, int(self.base_placement_config.target_floors))

        if min_f > max_f:
            min_f = max_f

        return range(min_f, max_f + 1)

    def generate_variants(
        self,
        floors_range: range | None = None,
        explore_typologies: bool = False,
        explore_angles: bool = False,
        angles: list[float] | None = None,
        progress_callback: Any = None,
    ) -> list[OptimizationResult]:
        """Сгенерировать варианты застройки с шагом в 1 этаж (и опционально по углам и типологиям).

        Args:
            floors_range: Диапазон этажности. Если None — определяется автоматически.
            explore_typologies: Если True — перебрать все типологии застройки.
            explore_angles: Если True — перебрать сетку углов поворота (0°, ±15°, ±25°).
            angles: Пользовательский список углов (если передан, используется напрямую).
            progress_callback: Функция обратного вызова on_progress(info_dict) для индикатора UI.

        Returns:
            Список вариантов с ТЭП.
        """
        typs_to_check = (
            ["AUTO", "PERIMETER", "TOWER", "U_SHAPE", "L_SHAPE", "LINEAR"]
            if explore_typologies
            else [self.base_placement_config.typology]
        )

        if explore_angles:
            if angles is not None:
                angles_to_check = angles
            else:
                if self.base_placement_config.placement_angle is not None:
                    base_angle = self.base_placement_config.placement_angle
                elif getattr(self.site, "buildable_area", None) is not None:
                    from src.core.buildable_area import get_primary_axes
                    base_angle, _ = get_primary_axes(self.site.buildable_area)
                else:
                    base_angle = getattr(self.site, "rotation_deg", 0.0) or 0.0

                raw_angles = [base_angle, base_angle + 15.0, base_angle - 15.0, base_angle + 25.0, base_angle - 25.0]
                angles_to_check = []
                for a in raw_angles:
                    norm_a = round(((a + 180.0) % 180.0), 1)
                    if norm_a not in angles_to_check:
                        angles_to_check.append(norm_a)
        else:
            angles_to_check = [self.base_placement_config.placement_angle]

        # Оценка общего числа шагов для прогресс-бара
        est_total = 0
        for typ in typs_to_check:
            cr = floors_range or self._get_floors_range(typ)
            n_f = (len(cr) // 2 + 1) if len(cr) > 6 else len(cr)
            est_total += len(angles_to_check) * n_f + (6 if len(cr) > 6 else 0)
        est_total = max(1, est_total)

        current_step = 0
        variants: list[OptimizationResult] = []

        def _notify_progress(fl: int, ang: float | None, typ_name: str, cur_best_cand: OptimizationResult | None):
            if not progress_callback:
                return
            pct = min(96, int((current_step / est_total) * 100))
            bgfa = round(cur_best_cand.tep.total_gfa) if cur_best_cand else 0
            bfl = cur_best_cand.floors if cur_best_cand else 0
            btyp = cur_best_cand.typology if cur_best_cand else typ_name
            ang_str = f"{ang:+.0f}°" if ang is not None else "0°"
            msg = f"Тестирование: {fl} эт., угол {ang_str}, типология «{typ_name}»"
            try:
                progress_callback({
                    "active": True,
                    "step": current_step,
                    "total": est_total,
                    "percent": pct,
                    "current_floors": fl,
                    "current_angle": ang or 0.0,
                    "current_typology": typ_name,
                    "tested_count": len(variants),
                    "best_gfa": bgfa,
                    "best_floors": bfl,
                    "best_typology": btyp,
                    "message": msg,
                })
            except Exception:
                pass

        for typ in typs_to_check:
            cur_range = floors_range or self._get_floors_range(typ)
            if len(cur_range) > 6:
                coarse_floors = list(cur_range)[::2]
                if cur_range[-1] not in coarse_floors:
                    coarse_floors.append(cur_range[-1])
            else:
                coarse_floors = list(cur_range)

            typ_variants: list[OptimizationResult] = []
            tested_keys: set[tuple[str, float | None, int]] = set()

            for ang in angles_to_check:
                effective_angle = ang
                if typ == "LINEAR" and ang is not None and angle_to_horizontal(ang) < MIN_MERIDIAN_INSOLATION_ANGLE_DEG:
                    effective_angle = 28.0

                for floors in coarse_floors:
                    key = (typ, effective_angle, floors)
                    if key in tested_keys:
                        continue
                    tested_keys.add(key)
                    current_step += 1

                    valid_so_far = [v for v in (variants + typ_variants) if v.normative_ok]
                    lead = max(valid_so_far, key=lambda x: x.tep.total_gfa, default=None)
                    _notify_progress(floors, effective_angle, typ, lead)

                    result = self._try_placement(floors, typology=typ, angle=effective_angle)
                    if result is not None:
                        typ_variants.append(result)

            # Точная доводка (fine-tuning): для лучших вариантов проверяем соседние этажи (±1 эт.)
            if len(cur_range) > 6 and typ_variants:
                valid_coarse = [v for v in typ_variants if v.normative_ok]
                top_to_refine = sorted(valid_coarse, key=lambda v: v.tep.residential_area, reverse=True)[:3] if valid_coarse else sorted(typ_variants, key=lambda v: v.score, reverse=True)[:2]
                for best_v in top_to_refine:
                    eff_ang = best_v.angle
                    for neighbor_f in (best_v.floors - 1, best_v.floors + 1):
                        if neighbor_f in cur_range:
                            key = (typ, eff_ang, neighbor_f)
                            if key not in tested_keys:
                                tested_keys.add(key)
                                current_step += 1
                                valid_now = [v for v in (variants + typ_variants) if v.normative_ok]
                                lead = max(valid_now, key=lambda x: x.tep.total_gfa, default=None)
                                _notify_progress(neighbor_f, eff_ang, typ, lead)

                                result = self._try_placement(neighbor_f, typology=typ, angle=eff_ang)
                                if result is not None:
                                    typ_variants.append(result)

            variants.extend(typ_variants)

        # Сортируем по жилой площади (убывание)
        variants.sort(key=lambda v: v.tep.residential_area, reverse=True)

        if progress_callback:
            best_lead = max([v for v in variants if v.normative_ok], key=lambda x: x.tep.total_gfa, default=variants[0] if variants else None)
            try:
                progress_callback({
                    "active": True,
                    "step": est_total,
                    "total": est_total,
                    "percent": 100,
                    "current_floors": best_lead.floors if best_lead else 0,
                    "current_angle": best_lead.angle if best_lead else 0.0,
                    "current_typology": best_lead.typology if best_lead else "",
                    "tested_count": len(variants),
                    "best_gfa": round(best_lead.tep.total_gfa) if best_lead else 0,
                    "best_floors": best_lead.floors if best_lead else 0,
                    "best_typology": best_lead.typology if best_lead else "",
                    "message": f"✓ Оптимальный вариант найден: {best_lead.floors if best_lead else 0} эт. (GFA {round(best_lead.tep.total_gfa):,} м²)",
                })
            except Exception:
                pass

        return variants

    def _try_placement(
        self,
        floors: int,
        typology: str | None = None,
        angle: float | None = None,
    ) -> OptimizationResult | None:
        """Попытка расстановки с заданной этажностью, типологией и углом.

        Args:
            floors: Количество этажей.
            typology: Типология (если None — из base_placement_config).
            angle: Угол посадки (если None — из base_placement_config).

        Returns:
            Результат или None при неудаче.
        """
        typ = typology or self.base_placement_config.typology
        cur_angle = angle if angle is not None else self.base_placement_config.placement_angle
        try:
            placement_config = PlacementConfig(
                target_floors=floors,
                placement_angle=cur_angle,
                preferred_section_ids=self.base_placement_config.preferred_section_ids,
                min_sections_per_building=self.base_placement_config.min_sections_per_building,
                max_sections_per_building=self.base_placement_config.max_sections_per_building,
                typology=typ,
                courtyard_orientation=self.base_placement_config.courtyard_orientation,
                variable_insolation=self.base_placement_config.variable_insolation,
                cascade_floors=self.base_placement_config.cascade_floors,
                asymmetric_wings=self.base_placement_config.asymmetric_wings,
                min_wing_floors=self.base_placement_config.min_wing_floors,
                floor_height=self.base_placement_config.floor_height,
                ground_floor_height=self.base_placement_config.ground_floor_height,
                max_building_height_m=self.base_placement_config.max_building_height_m,
                allow_towers_in_mixed=self.base_placement_config.allow_towers_in_mixed,
                urban_block_size=self.base_placement_config.urban_block_size,
                internal_road_width=self.base_placement_config.internal_road_width,
                perimeter_layout_style=self.base_placement_config.perimeter_layout_style,
                max_bcr=self.base_placement_config.max_bcr,
                max_far=self.base_placement_config.max_far,
                fire_gap_end_to_end=float(self.base_placement_config.fire_gap_end_to_end if self.base_placement_config.fire_gap_end_to_end is not None else self.config.get("fire_gap_end_to_end", 10.0)),
                fire_gap_parallel=float(self.base_placement_config.fire_gap_parallel if self.base_placement_config.fire_gap_parallel is not None else self.config.get("fire_gap_parallel", 18.0)),
            )

            roads_res = getattr(self.site, "roads_result", None)
            if (
                roads_res
                and getattr(roads_res, "roads_polygon", None) is not None
                and getattr(roads_res, "sub_blocks", None)
                and len(roads_res.sub_blocks) >= 1
            ):
                all_b = []
                for s_poly in roads_res.sub_blocks:
                    sub_site = Site(boundary=s_poly)
                    sub_site.buildable_area = s_poly
                    sub_site.address = self.site.address
                    sub_site.cadastral_number = self.site.cadastral_number
                    sub_engine = PlacementEngine(sub_site, self.library, self.config)
                    try:
                        all_b.extend(sub_engine.generate(placement_config))
                    except Exception:
                        pass
                buildings = all_b
                engine = None
            else:
                engine = PlacementEngine(self.site, self.library, self.config)
                buildings = engine.generate(placement_config)

            if not buildings:
                return None

            tep = calculate_tep(self.site, buildings, self.config)
            checks = check_normatives(tep, self.config)
            normative_ok = all(c["ok"] for c in checks.values())

            # Оценка: жилая площадь с штрафом за нарушения
            score = tep.residential_area
            if not normative_ok:
                score *= 0.5

            actual_angle = getattr(engine, "_last_primary_angle", None) if engine else None
            if actual_angle is None:
                actual_angle = cur_angle if cur_angle is not None else getattr(self.site, "rotation_deg", 0.0)

            return OptimizationResult(
                buildings=buildings,
                tep=tep,
                floors=floors,
                normative_ok=normative_ok,
                score=score,
                typology=typ,
                angle=round(float(actual_angle), 1),
            )

        except Exception as e:
            print(f"Ошибка при расстановке ({floors} эт., {typ}, {cur_angle}°): {e}")
            return None

        except Exception as e:
            print(f"Ошибка при расстановке ({floors} эт., {typ}): {e}")
            return None

    def compare_variants(self, variants: list[OptimizationResult]) -> str:
        """Сформировать сравнительную таблицу вариантов.

        Args:
            variants: Список вариантов для сравнения.

        Returns:
            Отформатированная таблица.
        """
        if not variants:
            return "Нет вариантов для сравнения."

        lines: list[str] = []
        lines.append("=" * 102)
        lines.append("  СРАВНЕНИЕ ВАРИАНТОВ ЗАСТРОЙКИ")
        lines.append("=" * 102)

        header = (
            f"  {'Вариант':<9} {'Типология':<10} {'Этажн.':<8} {'Зданий':<8} "
            f"{'GFA, м²':<12} {'Жил.пл.':<12} {'Кварт.':<8} "
            f"{'BCR':<8} {'FAR':<8} {'Норм.':<6}"
        )
        lines.append(header)
        lines.append("-" * 102)

        for i, v in enumerate(variants, 1):
            status = "✓" if v.normative_ok else "✗"
            line = (
                f"  {i:<9} {v.typology:<10} {v.floors:<8} {v.tep.building_count:<8} "
                f"{v.tep.total_gfa:<12,.0f} {v.tep.residential_area:<12,.0f} "
                f"{v.tep.apartments_total:<8} "
                f"{v.tep.bcr:<8.1%} {v.tep.far:<8.2f} {status:<6}"
            )
            lines.append(line)

        lines.append("=" * 102)
        return "\n".join(lines)
