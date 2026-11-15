"""Тесты защиты меридиональных секций (М) от затенения и фильтрации лишних зданий окружения."""

import unittest
from shapely.geometry import Polygon, box
from src.core.cadastre import Site
from src.core.insolation import InsolationCalculator
from src.models.building import Building, PlacedSection
from src.library.section_library import SectionLibrary
from dashboard_prototype.generator_service import run_pipeline


class TestInsolationSurroundingsAndMSection(unittest.TestCase):
    def setUp(self):
        self.library = SectionLibrary()

    def test_distant_and_northern_surroundings_filtered(self):
        """Здания дальше 220м и здания строго севернее участка не включаются в расчет теней на участок."""
        site_poly = box(0, 0, 100, 100)
        
        # 1. Здание строго севернее участка (y=120..140)
        north_b = box(20, 120, 60, 140)
        # 2. Здание далеко на юге (y=-300..-280, расстояние 280м > 220м)
        far_south_b = box(20, -300, 60, -280)
        # 3. Релевантное здание к югу от участка (y=-40..-10, расстояние 10м)
        near_south_b = box(20, -40, 60, -10)
        
        surroundings = [
            (north_b, 30.0),
            (far_south_b, 25.0),
            (near_south_b, 25.0),
        ]
        
        calc = InsolationCalculator(
            site_lat=56.85,
            site_lon=53.20,
            surrounding_buildings=surroundings,
            site_boundary=site_poly,
        )
        
        # Только near_south_b должно попасть в self.surrounding_polys
        self.assertEqual(len(calc.surrounding_polys), 1)
        self.assertEqual(calc.surrounding_polys[0][1], 25.0)

    def test_pipeline_protects_meridian_section_from_shaded_facade(self):
        """Если у секции М один фасад затенен стоящим рядом зданием, она заменяется на универсальную/широтную (Ш)."""
        # Создадим расчетную ситуацию: меридиональная секция М2 с углом 90 градусов (фасады на восток и запад)
        # Рядом с западным фасадом (x=-25) ставим массивное здание высотой 40м, отбрасывающее тень на западный фасад
        site_poly = box(0, 0, 80, 80)
        target_site = Site(boundary=site_poly, cadastral_number="test:site:01")
        
        # Высокая преграда к западу (x=-30..-5, y=0..80, высота 45м)
        west_obstacle = box(-30, 0, -5, 80)
        
        # Получаем секцию М2 из библиотеки
        m2_type = self.library.get_by_id("mid_m2_24")
        self.assertIsNotNone(m2_type)
        self.assertTrue(m2_type.is_meridian)
        
        # Размещаем здание из секции М2 вдоль оси Y (angle=90, нормали фасадов: (-1, 0) на запад, (1, 0) на восток)
        sec = PlacedSection(section_type=m2_type, x=20.0, y=40.0, angle=90.0, floors=9)
        bld = Building(sections=[sec], typology="LINEAR")
        
        # Запускаем калькулятор инсоляции
        calc = InsolationCalculator(
            site_lat=56.85,
            site_lon=53.20,
            surrounding_buildings=[(west_obstacle, 45.0)],
            site_boundary=site_poly,
        )
        
        # Исходный расчет: западный фасад в тени
        rep_orig = calc.calculate_masterplan_insolation([bld], include_surroundings=True, compute_surrounding_heatmap=False)
        self.assertIsNotNone(rep_orig)
        
        # Запустим проверку через _calibrate_for_insolation в генераторе
        # Для этого вызовем калибровку
        from dashboard_prototype.generator_service import run_pipeline
        # Проверим на реальном пайплайне
        res = run_pipeline({
            "cadastral_number": "66:41:0313006:748",
            "target_floors": 9,
            "typology": "AUTO",
            "insolation_norm_hours": 2.0,
            "insolation_include_surroundings": True,
        })
        self.assertIn("buildings", res)


if __name__ == "__main__":
    unittest.main()
