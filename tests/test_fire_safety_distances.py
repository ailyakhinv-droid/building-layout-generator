"""Тесты дифференцированных противопожарных расстояний между зданиями.

Проверяет соблюдение нормативов СП 4.13130 и СП 42.13330:
1. 10 м — минимальный просвет между торцами секций (END_TO_END)
   или между торцом и лицевым/дворовым фасадом (END_TO_FACADE).
2. 15-20 м (по умолчанию 18 м) — минимальный разрыв при параллельной посадке (FACADE_PARALLEL).
3. Для блокируемых корпусов — смотрим противопожарное расстояние по внешним граням
   (внутри здания секции состыкованы).
4. Для башен (точечных домов) — проверяем по всем 4 сторонам (до фасадов 15-20 м, до торцов 10 м).
5. Возможность пользовательской настройки расстояний в PlacementConfig.
"""

import unittest

from src.core.site_parser import create_rectangular_site
from src.library.section_library import SectionLibrary
from src.models.building import Building, PlacedSection
from src.core.placement import PlacementEngine, PlacementConfig


class TestFireSafetyDistances(unittest.TestCase):
    """Набор тестов для противопожарных расстояний."""

    @classmethod
    def setUpClass(cls):
        cls.library = SectionLibrary()
        cls.sec = cls.library.get_by_id("end_sh1_9")     # 19.35 x 17.0 m, широтная
        cls.tower = cls.library.get_by_id("tower_b1")    # 29.7 x 23.9 m, TOWER

        # Создаем большой тестовый участок 200x200 м
        cls.site = create_rectangular_site(200, 200)

    def test_parallel_facades_rejected_below_18m(self):
        """Параллельная посадка двух зданий (фасад к фасаду) должна отклоняться при разрыве < 18 м."""
        engine = PlacementEngine(self.site, self.library)
        cfg = PlacementConfig(fire_gap_parallel=18.0, fire_gap_end_to_end=10.0, min_sections_per_building=1)

        # b1: центр (100, 50), глубина 17м, верхний фасад на y = 58.5
        b1 = Building([PlacedSection(self.sec, 100, 50, angle=0)])
        # b2: центр (100, 70), нижний фасад на y = 61.5, разрыв между фасадами = 3.0 м (< 18 м)
        b2_too_close = Building([PlacedSection(self.sec, 100, 70, angle=0)])
        self.assertFalse(engine._check_constraints(b2_too_close, [b1], cfg))

        # b2: центр (100, 80), нижний фасад на y = 71.5, разрыв = 13.0 м (< 18 м)
        b2_13m = Building([PlacedSection(self.sec, 100, 80, angle=0)])
        self.assertFalse(engine._check_constraints(b2_13m, [b1], cfg))

        # b2: центр (100, 86), нижний фасад на y = 77.5, разрыв = 19.0 м (>= 18 м)
        b2_ok = Building([PlacedSection(self.sec, 100, 86, angle=0)])
        self.assertTrue(engine._check_constraints(b2_ok, [b1], cfg))

    def test_end_to_end_distance_10m(self):
        """Просвет между торцами двух секций должен быть не менее 10 м."""
        engine = PlacementEngine(self.site, self.library)
        cfg = PlacementConfig(fire_gap_end_to_end=10.0, fire_gap_parallel=18.0, min_sections_per_building=1)

        # b1: центр (50, 100), ширина 19.35, правый торец на x = 50 + 9.675 = 59.675
        b1 = Building([PlacedSection(self.sec, 50, 100, angle=0)])

        # b2_too_close: центр (74, 100), левый торец на x = 74 - 9.675 = 64.325 -> разрыв = 4.65 м (< 10 м)
        b2_too_close = Building([PlacedSection(self.sec, 74, 100, angle=0)])
        self.assertFalse(engine._check_constraints(b2_too_close, [b1], cfg))

        # b2_ok: центр (85, 100), левый торец на x = 85 - 9.675 = 75.325 -> разрыв = 15.65 м (>= 10 м)
        b2_ok = Building([PlacedSection(self.sec, 85, 100, angle=0)])
        self.assertTrue(engine._check_constraints(b2_ok, [b1], cfg))

    def test_end_to_facade_distance_10m(self):
        """Просвет между торцом одного здания и фасадом другого должен быть не менее 10 м."""
        engine = PlacementEngine(self.site, self.library)
        cfg = PlacementConfig(fire_gap_end_to_end=10.0, fire_gap_parallel=18.0, min_sections_per_building=1)

        # b1: горизонтальное здание, центр (50, 100), правый торец на x = 59.675
        b1 = Building([PlacedSection(self.sec, 50, 100, angle=0)])

        # b_vert: вертикальное здание (фасад вдоль Y, центр x = 72.0 -> x_min = 72 - 8.5 = 63.5 -> разрыв 3.825 м < 10 м)
        b_vert_close = Building([PlacedSection(self.sec, 72, 100, angle=90)])
        self.assertFalse(engine._check_constraints(b_vert_close, [b1], cfg))

        # b_vert_ok: центр x = 85 -> x_min = 85 - 8.5 = 76.5 -> разрыв с торцом = 16.825 м (>= 10 м)
        b_vert_ok = Building([PlacedSection(self.sec, 85, 100, angle=90)])
        self.assertTrue(engine._check_constraints(b_vert_ok, [b1], cfg))

    def test_tower_inspected_on_all_four_sides(self):
        """Для башен (точечных домов) противопожарные разрывы проверяются по всем 4 сторонам."""
        engine = PlacementEngine(self.site, self.library)
        cfg = PlacementConfig(fire_gap_end_to_end=10.0, fire_gap_parallel=18.0, min_sections_per_building=1)

        tower1 = Building([PlacedSection(self.tower, 100, 100, angle=0, floors=9)], typology="TOWER")

        # 1. Другая башня на расстоянии 6.1 м (< 18 м) -> должна быть отклонена
        # tower1: y in [88.05, 111.95] (глубина 23.9)
        tower_too_close = Building([PlacedSection(self.tower, 100, 130, angle=0, floors=9)], typology="TOWER")
        self.assertFalse(engine._check_constraints(tower_too_close, [tower1], cfg))

        # Башня на расстоянии 21 м (>= 18 м) -> принимается
        tower_ok = Building([PlacedSection(self.tower, 100, 145, angle=0, floors=9)], typology="TOWER")
        self.assertTrue(engine._check_constraints(tower_ok, [tower1], cfg))

        # 2. Башня напротив фасада линейного дома:
        # linear: центр (100, 50), верхний фасад на y = 58.5
        b_linear = Building([PlacedSection(self.sec, 100, 50, angle=0, floors=9)])
        # башня с нижним фасадом на y = 70 (разрыв 11.5 м < 18 м) -> отклоняется
        tower_near_facade_close = Building([PlacedSection(self.tower, 100, 81.95, angle=0, floors=9)], typology="TOWER")
        self.assertFalse(engine._check_constraints(tower_near_facade_close, [b_linear], cfg))

        # башня на расстоянии 21.55 м от фасада (>= 18 м) -> принимается
        tower_near_facade_ok = Building([PlacedSection(self.tower, 100, 92, angle=0, floors=9)], typology="TOWER")
        self.assertTrue(engine._check_constraints(tower_near_facade_ok, [b_linear], cfg))

        # 3. Башня напротив глухого торца линейного дома:
        # b_linear: центр (100, 50), правый торец на x = 100 + 9.675 = 109.675
        # башня на x = 128 (x_min = 128 - 14.85 = 113.15 -> разрыв 3.475 м < 10 м) -> отклоняется
        tower_near_end_close = Building([PlacedSection(self.tower, 128, 50, angle=0, floors=9)], typology="TOWER")
        self.assertFalse(engine._check_constraints(tower_near_end_close, [b_linear], cfg))

        # башня на x = 138 (x_min = 138 - 14.85 = 123.15 -> разрыв 13.475 м >= 10 м) -> принимается
        tower_near_end_ok = Building([PlacedSection(self.tower, 138, 50, angle=0, floors=9)], typology="TOWER")
        self.assertTrue(engine._check_constraints(tower_near_end_ok, [b_linear], cfg))

    def test_custom_user_configured_gaps(self):
        """Пользовательская настройка противопожарных расстояний в PlacementConfig."""
        engine = PlacementEngine(self.site, self.library)

        # Пользователь задал ужесточённые нормы: торец 15 м, параллельная 24 м
        cfg_strict = PlacementConfig(fire_gap_end_to_end=15.0, fire_gap_parallel=24.0, min_sections_per_building=1)

        b1 = Building([PlacedSection(self.sec, 100, 50, angle=0)])
        # Разрыв 20 м (y = 58.5 + 20 + 8.5 = 87) — раньше бы прошёл (>= 18м), но при strict=24м должен отклониться
        b2_20m = Building([PlacedSection(self.sec, 100, 87, angle=0)])
        self.assertFalse(engine._check_constraints(b2_20m, [b1], cfg_strict))

        # Разрыв 26 м (y = 58.5 + 26 + 8.5 = 93) -> принимается
        b2_26m = Building([PlacedSection(self.sec, 100, 93, angle=0)])
        self.assertTrue(engine._check_constraints(b2_26m, [b1], cfg_strict))


if __name__ == "__main__":
    unittest.main()
