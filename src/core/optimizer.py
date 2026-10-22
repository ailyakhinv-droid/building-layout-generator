"""Оптимизатор расстановки застройки.

Два режима работы:
1. Подбор параметров под целевые ТЭП.
2. Максимизация жилой площади при соблюдении нормативов.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.core.placement import PlacementConfig, PlacementEngine
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
    """
    buildings: list[Building]
    tep: TEP
    floors: int
    normative_ok: bool
    score: float = 0.0
    typology: str = "AUTO"
    note: str = ""


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
    ) -> OptimizationResult:
        """Максимизировать жилую площадь.

        Args:
            respect_normatives: Если True — строго соблюдать нормативы (FAR <= max_far, BCR <= max_bcr).
                               Если False — абсолютная максимизация площади без отсечения по плотности.
            explore_typologies: Если True — перебрать все типологии (AUTO, U_SHAPE, L_SHAPE, LINEAR).

        Returns:
            Лучший найденный результат.
        """
        variants = self.generate_variants(explore_typologies=explore_typologies)

        if not variants:
            raise ValueError("Не удалось сгенерировать ни одного варианта.")

        max_far_limit = float(self.config.get("max_far", 2.50))

        if respect_normatives:
            # Фильтруем допустимые нормативами варианты
            valid = [v for v in variants if v.normative_ok]
            if valid:
                best = max(valid, key=lambda v: v.tep.residential_area)
                best.note = (
                    f"Оптимальный максимум по нормативам: {best.floors} эт. ({best.typology}), "
                    f"FAR={best.tep.far:.2f} (лимит {max_far_limit:.2f})."
                )
                return best
            else:
                # Если ни один не уложился в нормативы — берем с минимальными отклонениями
                best = max(variants, key=lambda v: v.score)
                best.note = (
                    f"Все варианты превышают предельный FAR {max_far_limit:.2f}. "
                    f"Выбран вариант с мин. нарушениями ({best.floors} эт.)."
                )
                return best
        else:
            best = max(variants, key=lambda v: v.tep.residential_area)
            best.note = (
                f"Абсолютный физический максимум (без лимитов FAR): {best.floors} эт. ({best.typology}), "
                f"FAR={best.tep.far:.2f}."
            )
            return best

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
        if max_h and max_h > 0:
            extra_first = max(0.0, float(ground_h) - float(floor_h))
            max_f_from_h = max(1, int((float(max_h) - extra_first) // float(floor_h)))
            max_f = min(max_f, max_f_from_h)

        if min_f > max_f:
            min_f = max_f

        return range(min_f, max_f + 1)

    def generate_variants(
        self,
        floors_range: range | None = None,
        explore_typologies: bool = False,
    ) -> list[OptimizationResult]:
        """Сгенерировать варианты застройки с шагом в 1 этаж.

        Args:
            floors_range: Диапазон этажности. Если None — определяется автоматически.
            explore_typologies: Если True — перебрать все типологии застройки.

        Returns:
            Список вариантов с ТЭП.
        """
        typs_to_check = (
            ["AUTO", "PERIMETER", "TOWER", "U_SHAPE", "L_SHAPE", "LINEAR"]
            if explore_typologies
            else [self.base_placement_config.typology]
        )

        variants: list[OptimizationResult] = []

        for typ in typs_to_check:
            cur_range = floors_range or self._get_floors_range(typ)
            for floors in cur_range:
                result = self._try_placement(floors, typology=typ)
                if result is not None:
                    variants.append(result)

        # Сортируем по жилой площади (убывание)
        variants.sort(key=lambda v: v.tep.residential_area, reverse=True)

        return variants

    def _try_placement(
        self,
        floors: int,
        typology: str | None = None,
    ) -> OptimizationResult | None:
        """Попытка расстановки с заданной этажностью и типологией.

        Args:
            floors: Количество этажей.
            typology: Типология (если None — из base_placement_config).

        Returns:
            Результат или None при неудаче.
        """
        typ = typology or self.base_placement_config.typology
        try:
            engine = PlacementEngine(self.site, self.library, self.config)
            placement_config = PlacementConfig(
                target_floors=floors,
                placement_angle=self.base_placement_config.placement_angle,
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
            )
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

            return OptimizationResult(
                buildings=buildings,
                tep=tep,
                floors=floors,
                normative_ok=normative_ok,
                score=score,
                typology=typ,
            )

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
