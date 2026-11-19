"""Тесты посадки высотных башен-акцентов (Б1 >= 12 эт.) и соблюдения инсоляционных разрывов (Этап Б).

Нормативная база:
- СанПиН 1.2.3685-21 (п. 164): обязательная инсоляция обоих продольных фасадов секций М (меридиональных).
- СП 42.13330 (п. 7.1) и СП 4.13130: инсоляционные и противопожарные разрывы башен от жилых корпусов.
"""

from __future__ import annotations

import unittest
from shapely.geometry import Polygon, box

from src.models.site import Site
from src.models.building import Building, PlacedSection
from src.library.section_library import SectionLibrary
from src.core.placement import PlacementEngine, PlacementConfig


class TestStageBTowerAccentPlacement(unittest.TestCase):
    def setUp(self):
        # Большой участок 160 x 140 м (2.24 га)
        poly = box(0, 0, 160, 140)
        self.site = Site(boundary=poly)
        self.site.buildable_area = poly.buffer(-5.0)
        self.library = SectionLibrary()
        self.tower_sec = self.library.get_by_id("tower_b1")
        self.sec_m2 = self.library.get_by_id("mid_m2_24")
        self.sec_sh1 = self.library.get_by_id("end_sh1_9")

    def test_tower_south_shadow_gap_rejection(self):
        """Башня, расположенная строго к югу от жилого корпуса ближе 1.15*H, должна отклоняться."""
        engine = PlacementEngine(self.site, self.library)
        cfg = PlacementConfig(fire_gap_parallel=18.0, fire_gap_end_to_end=10.0, min_sections_per_building=1)

        # 1. Жилой корпус 9 этажей (высота 28 м) в центре y = 100
        sec = self.sec_sh1 or self.library.get_middle_sections()[0]
        linear_b = Building([PlacedSection(sec, 80, 100, angle=0, floors=9)])

        # 2. Высокая башня Б1 16 этажей (высота ~50 м) к югу на y = 60
        # Дистанция между ними = 100 - 8.5 - (60 + 11.95) = 19.55 м.
        # Требуемый инсоляционный разрыв с юга: max(18.0, 50 * 1.15) = 57.5 м!
        tower_south_close = Building([PlacedSection(self.tower_sec, 80, 60, angle=0, floors=16)], typology="TOWER")

        # Должна быть отклонена из-за падения полуденной тени башни на жилой дом
        self.assertFalse(engine._check_constraints(tower_south_close, [linear_b], cfg))

        # 3. Башня на нормативном инсоляционном расстоянии (y = 20, разрыв ~59.5 м >= 57.5 м)
        tower_south_ok = Building([PlacedSection(self.tower_sec, 80, 20, angle=0, floors=16)], typology="TOWER")
        self.assertTrue(engine._check_constraints(tower_south_ok, [linear_b], cfg))

    def test_meridian_m2_lateral_shadow_protection(self):
        """Меридиональная секция М2 не может ставиться в зоне боковой тени высокой башни."""
        engine = PlacementEngine(self.site, self.library)
        cfg = PlacementConfig(fire_gap_parallel=18.0, fire_gap_end_to_end=10.0, min_sections_per_building=1)

        # Башня Б1 16 этажей (высота 50м) на x = 50, y = 80
        tower = Building([PlacedSection(self.tower_sec, 50, 80, angle=0, floors=16)], typology="TOWER")

        # Меридиональный корпус М2 (требует инсоляции с запада и востока) к востоку от башни на x = 80 (разрыв ~15 м)
        m2_b_close = Building([PlacedSection(self.sec_m2, 80, 80, angle=90, floors=10)])

        # Секция М2 отклоняется, так как башня перекрывает ей западное солнце
        self.assertFalse(engine._check_constraints(m2_b_close, [tower], cfg))

    def test_large_block_mixed_typology_unlock(self):
        """Крупный квартал (> 5500 кв.м) в AUTO автоматически получает MIXED с доминантой/башней."""
        large_block = box(0, 0, 180, 120)  # 180 x 120 м = 2.16 га
        sub_site = Site(boundary=large_block)
        sub_site.buildable_area = large_block.buffer(-3.0)
        engine = PlacementEngine(sub_site, self.library)

        cfg = PlacementConfig(typology="AUTO", target_floors=9, allow_towers_in_mixed=True)
        buildings = engine.generate(cfg)

        self.assertGreater(len(buildings), 1)
        typologies = {getattr(b, "typology", "LINEAR") for b in buildings}
        # Проверяем появление гибридного ансамбля "двор + башня/доминанта"
        self.assertTrue("U_SHAPE" in typologies or "L_SHAPE" in typologies)
        self.assertTrue("TOWER" in typologies)


if __name__ == "__main__":
    unittest.main()
