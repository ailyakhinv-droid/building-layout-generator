"""Тесты для многомерного оптимизатора «Выжать максимум по закону».

Проверяет:
1. Перебор сетки углов (0°, ±15°, ±25°).
2. Соблюдение 100% законодательных нормативов (FAR, BCR, пожарные разрывы 10м/18м, инсоляция).
3. Работу метода optimize_maximize() и find_absolute_maximum().
4. Корректность формирования аудиторской записки и подсчета протестированных конфигураций.
"""

from __future__ import annotations

import unittest
from shapely.geometry import Polygon

from src.core.optimizer import Optimizer
from src.core.placement import (
    PlacementConfig,
    PlacementEngine,
    angle_to_horizontal,
    MIN_MERIDIAN_INSOLATION_ANGLE_DEG,
)
from src.library.section_library import SectionLibrary
from src.core.site_parser import create_rectangular_site
from src.models.site import Site


class TestMaximizerOptimizer(unittest.TestCase):
    """Тестирование поиска абсолютного максимума по закону."""

    def setUp(self) -> None:
        self.library = SectionLibrary()
        # Прямоугольный участок 220м x 140м (~3.08 га)
        self.site = create_rectangular_site(220, 140)
        self.config = {
            "boundary_setback": 6.0,
            "red_line_setback": 5.0,
            "max_far": 2.50,
            "max_bcr": 0.40,
            "min_green_ratio": 0.25,
            "floor_height": 3.0,
            "fire_gap_end_to_end": 10.0,
            "fire_gap_parallel": 18.0,
        }
        self.site.compute_buildable_area(
            boundary_setback=self.config["boundary_setback"],
            red_line_setback=self.config["red_line_setback"],
        )

    def test_angle_exploration_finds_superior_or_equal_gfa(self) -> None:
        """Перебор углов поворота должен давать жилую площадь не меньше базового угла."""
        base_cfg = PlacementConfig(typology="AUTO", target_floors=14)
        opt = Optimizer(self.site, self.library, self.config, base_placement_config=base_cfg)

        # 1. Без перебора углов (только базовый)
        res_baseline = opt.optimize_maximize(
            respect_normatives=True,
            explore_typologies=False,
            explore_angles=False,
        )

        # 2. С перебором углов
        res_angles = opt.optimize_maximize(
            respect_normatives=True,
            explore_typologies=False,
            explore_angles=True,
            angles=[0.0, 15.0, 25.0],
        )

        self.assertGreaterEqual(
            res_angles.tep.residential_area,
            res_baseline.tep.residential_area,
            "Оптимизатор с углами не должен ухудшать базовый результат"
        )
        self.assertGreater(res_angles.configs_tested, 1, "Должно быть протестировано несколько угловых конфигураций")
        self.assertTrue(res_angles.normative_ok, "Победитель должен быть на 100% нормативным")

    def test_normatives_are_strictly_respected(self) -> None:
        """Все варианты с respect_normatives=True обязаны укладываться в FAR <= 2.50 и BCR <= 0.40."""
        base_cfg = PlacementConfig(typology="AUTO", target_floors=14)
        opt = Optimizer(self.site, self.library, self.config, base_placement_config=base_cfg)

        best = opt.optimize_maximize(
            respect_normatives=True,
            explore_typologies=False,
            explore_angles=True,
            angles=[0.0, 15.0, 25.0],
        )

        self.assertLessEqual(best.tep.far, 2.50 + 1e-4, f"FAR {best.tep.far:.2f} превысил 2.50")
        self.assertLessEqual(best.tep.bcr, 0.40 + 1e-4, f"BCR {best.tep.bcr:.2f} превысил 0.40")
        self.assertTrue(best.normative_ok)

    def test_find_absolute_maximum_method(self) -> None:
        """Метод find_absolute_maximum() возвращает полностью валидный Top-1 результат."""
        base_cfg = PlacementConfig(typology="AUTO", target_floors=14)
        opt = Optimizer(self.site, self.library, self.config, base_placement_config=base_cfg)

        top1 = opt.find_absolute_maximum(explore_typologies=False, explore_angles=True)

        self.assertIsNotNone(top1)
        self.assertGreater(len(top1.buildings), 0)
        self.assertGreater(top1.tep.residential_area, 0)
        self.assertIn("ВЫЖАТ МАКСИМУМ ПО ЗАКОНУ", top1.note)
        self.assertIn("FAR", top1.note)

    def test_linear_insolation_protection(self) -> None:
        """Для типологии LINEAR углы, нарушающие инсоляцию (<25° к горизонту), корректируются."""
        base_cfg = PlacementConfig(typology="LINEAR")
        opt = Optimizer(self.site, self.library, self.config, base_placement_config=base_cfg)

        variants = opt.generate_variants(
            explore_typologies=False,
            explore_angles=True,
            angles=[0.0, 5.0, 28.0],
        )

        for v in variants:
            # Угол размещения секций должен соответствовать СанПиН
            self.assertGreaterEqual(
                angle_to_horizontal(v.angle),
                MIN_MERIDIAN_INSOLATION_ANGLE_DEG,
                f"Угол {v.angle}° нарушает норматив инсоляции для линейных меридиональных секций"
            )

    def test_fire_safety_distances_in_optimizer_result(self) -> None:
        """В победном варианте оптимизатора расстояния между зданиями должны удовлетворять ПБ."""
        base_cfg = PlacementConfig(
            typology="AUTO",
            fire_gap_end_to_end=10.0,
            fire_gap_parallel=18.0,
        )
        opt = Optimizer(self.site, self.library, self.config, base_placement_config=base_cfg)
        variants = opt.generate_variants(
            floors_range=range(9, 15, 2),
            explore_typologies=False,
            explore_angles=True,
        )
        valid = [v for v in variants if v.normative_ok]
        self.assertTrue(len(valid) > 0, "Должен быть хотя бы один нормативный вариант")
        best = max(valid, key=lambda v: v.tep.residential_area)

        engine = PlacementEngine(self.site, self.library, self.config)
        buildings = best.buildings
        for i in range(len(buildings)):
            for j in range(i + 1, len(buildings)):
                b1 = buildings[i]
                b2 = buildings[j]
                p1 = b1.footprint
                p2 = b2.footprint
                dist = p1.distance(p2)
                req_dist, gap_type = engine.classify_fire_gap(
                    b1, b2, gap_end=10.0, gap_parallel=18.0
                )
                # Разрешаем погрешность округления 0.1м
                self.assertGreaterEqual(
                    dist + 0.1,
                    req_dist,
                    f"Нарушен пожарный разрыв между зданием {i} и {j}: {dist:.1f}м < {req_dist:.1f}м ({gap_type})"
                )


if __name__ == "__main__":
    unittest.main()
