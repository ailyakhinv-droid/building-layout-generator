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
    """
    buildings: list[Building]
    tep: TEP
    floors: int
    normative_ok: bool
    score: float = 0.0


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
        # Определяем диапазон этажности из библиотеки
        middles = self.library.get_middle_sections()
        if not middles:
            raise ValueError("В библиотеке нет рядовых секций.")

        section = middles[0]
        min_f = section.min_floors
        max_f = section.max_floors

        # Определяем целевой показатель
        target_far = target_tep.get("target_far")
        target_apts = target_tep.get("target_apartments")
        target_gfa = target_tep.get("target_gfa")

        best_result: OptimizationResult | None = None
        best_diff = float("inf")

        # Бинарный поиск по этажности
        low, high = min_f, max_f

        for iteration in range(max_iterations):
            floors = (low + high) // 2

            result = self._try_placement(floors)
            if result is None:
                high = floors - 1
                continue

            # Вычисляем отклонение от цели
            diff = 0.0
            if target_far is not None:
                diff = abs(result.tep.far - target_far)
            elif target_apts is not None:
                diff = abs(result.tep.apartments_total - target_apts)
            elif target_gfa is not None:
                diff = abs(result.tep.total_gfa - target_gfa)

            # Обновляем лучший результат
            if diff < best_diff:
                best_diff = diff
                best_result = result

            # Корректируем диапазон поиска
            if target_far is not None:
                if result.tep.far < target_far:
                    low = floors + 1
                else:
                    high = floors - 1
            elif target_apts is not None:
                if result.tep.apartments_total < target_apts:
                    low = floors + 1
                else:
                    high = floors - 1
            elif target_gfa is not None:
                if result.tep.total_gfa < target_gfa:
                    low = floors + 1
                else:
                    high = floors - 1

            if low > high:
                break

        if best_result is None:
            raise ValueError("Не удалось найти допустимый вариант расстановки.")

        return best_result

    def optimize_maximize(self) -> OptimizationResult:
        """Максимизировать жилую площадь при соблюдении нормативов.

        Перебирает варианты этажности и выбирает вариант
        с максимальной жилой площадью, удовлетворяющий нормативам.

        Returns:
            Лучший найденный результат.
        """
        variants = self.generate_variants()

        # Фильтруем допустимые варианты
        valid = [v for v in variants if v.normative_ok]

        if not valid:
            # Если нет допустимых — берём с минимальным нарушением
            if variants:
                return max(variants, key=lambda v: v.tep.residential_area)
            raise ValueError("Не удалось сгенерировать ни одного варианта.")

        # Из допустимых — выбираем с максимальной жилой площадью
        return max(valid, key=lambda v: v.tep.residential_area)

    def generate_variants(
        self,
        floors_range: range | None = None,
    ) -> list[OptimizationResult]:
        """Сгенерировать несколько вариантов застройки.

        Args:
            floors_range: Диапазон этажности. Если None — полный диапазон.

        Returns:
            Список вариантов с ТЭП.
        """
        if floors_range is None:
            middles = self.library.get_middle_sections()
            if not middles:
                return []
            section = middles[0]
            floors_range = range(section.min_floors, section.max_floors + 1, 2)

        variants: list[OptimizationResult] = []

        for floors in floors_range:
            result = self._try_placement(floors)
            if result is not None:
                variants.append(result)

        # Сортируем по жилой площади (убывание)
        variants.sort(key=lambda v: v.tep.residential_area, reverse=True)

        return variants

    def _try_placement(self, floors: int) -> OptimizationResult | None:
        """Попытка расстановки с заданной этажностью.

        Args:
            floors: Количество этажей.

        Returns:
            Результат или None при неудаче.
        """
        try:
            engine = PlacementEngine(self.site, self.library, self.config)
            placement_config = PlacementConfig(
                target_floors=floors,
                placement_angle=self.base_placement_config.placement_angle,
                preferred_section_ids=self.base_placement_config.preferred_section_ids,
                min_sections_per_building=self.base_placement_config.min_sections_per_building,
                max_sections_per_building=self.base_placement_config.max_sections_per_building,
                typology=self.base_placement_config.typology,
                courtyard_orientation=self.base_placement_config.courtyard_orientation,
                variable_insolation=self.base_placement_config.variable_insolation,
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
            )

        except Exception as e:
            print(f"Ошибка при расстановке ({floors} эт.): {e}")
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
        lines.append("=" * 90)
        lines.append("  СРАВНЕНИЕ ВАРИАНТОВ ЗАСТРОЙКИ")
        lines.append("=" * 90)

        header = (
            f"  {'Вариант':<10} {'Этажн.':<8} {'Зданий':<8} "
            f"{'GFA, м²':<12} {'Жил.пл.':<12} {'Кварт.':<8} "
            f"{'BCR':<8} {'FAR':<8} {'Норм.':<6}"
        )
        lines.append(header)
        lines.append("-" * 90)

        for i, v in enumerate(variants, 1):
            status = "✓" if v.normative_ok else "✗"
            line = (
                f"  {i:<10} {v.floors:<8} {v.tep.building_count:<8} "
                f"{v.tep.total_gfa:<12,.0f} {v.tep.residential_area:<12,.0f} "
                f"{v.tep.apartments_total:<8} "
                f"{v.tep.bcr:<8.1%} {v.tep.far:<8.2f} {status:<6}"
            )
            lines.append(line)

        lines.append("=" * 90)
        return "\n".join(lines)
