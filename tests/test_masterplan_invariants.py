"""Комплексные тесты градостроительных инвариантов и устойчивости алгоритма (Stress & Invariant Benchmark).

Проверяет 5 ключевых законов мастер-планирования:
1. Отсутствие самопересечений корпусов и секций (0 collisions).
2. Строгое соблюдение зоны допустимого строительства и ЗОУИТ (0 boundary violations).
3. Монотонность плотности (Anti-Collapse: GFA не должен обваливаться при росте этажности).
4. Соблюдение противопожарных разрывов между зданиями (СП 4.13130).
5. Соблюдение каталожных и нормативных пределов высоты секций.
"""

from __future__ import annotations

import unittest
from shapely.geometry import Polygon

from src.models.site import Site
from src.core.buildable_area import compute_buildable_area
from src.core.road_slicer import RoadSlicer
from src.core.placement import PlacementEngine, PlacementConfig
from dashboard_prototype.generator_service import (
    get_config,
    get_library,
    _create_site_from_params,
    run_pipeline,
)


class TestMasterplanInvariants(unittest.TestCase):
    """Стресс-тестирование геометрических и нормативных инвариантов застройки."""

    @classmethod
    def setUpClass(cls):
        cls.config = get_config()
        cls.library = get_library()

    def test_zero_building_intersections_on_dense_site(self):
        """Инвариант 1: Корпуса и секции не должны пересекаться между собой."""
        site = Site(boundary=Polygon([(0, 0), (220, 0), (220, 160), (0, 160)]))
        compute_buildable_area(site, self.config)

        engine = PlacementEngine(site, self.library, self.config)
        for fl in [9, 14, 18]:
            p_cfg = PlacementConfig(target_floors=fl, typology="AUTO", max_sections_per_building=8)
            buildings = engine.generate(p_cfg)
            self.assertGreater(len(buildings), 0, f"Застройка должна сформироваться на {fl} эт.")

            # Проверка попарного пересечения корпусов
            for i in range(len(buildings)):
                for j in range(i + 1, len(buildings)):
                    b1_poly = getattr(buildings[i], "footprint", None) or buildings[i].polygon
                    b2_poly = getattr(buildings[j], "footprint", None) or buildings[j].polygon
                    overlap_area = b1_poly.intersection(b2_poly).area
                    self.assertLess(
                        overlap_area,
                        0.05,
                        f"Корпус {i+1} пересекается с корпусом {j+1} на {fl} эт. (площадь {overlap_area:.2f} м²)",
                    )

    def test_all_buildings_within_buildable_and_outside_zouit(self):
        """Инвариант 2: Застройка строго внутри допустимой зоны и не наступает на ЗОУИТ."""
        # Участок с полосой отчуждения ЗОУИТ в южной части (как ж/д в Ижевске)
        boundary = Polygon([(0, 0), (200, 0), (200, 140), (0, 140)])
        zouit_poly = Polygon([(0, 0), (200, 0), (200, 25), (0, 25)])  # 25 м ЗОУИТ снизу
        buildable = boundary.buffer(-6.0).difference(zouit_poly)

        site = Site(boundary=boundary)
        site.buildable_area = buildable
        site.zouit_polygons = [zouit_poly]

        engine = PlacementEngine(site, self.library, self.config)
        p_cfg = PlacementConfig(target_floors=14, typology="AUTO")
        buildings = engine.generate(p_cfg)

        for idx, b in enumerate(buildings):
            # Проверка: корпус не пересекает ЗОУИТ
            b_poly = getattr(b, "footprint", None) or b.polygon
            zouit_overlap = b_poly.intersection(zouit_poly).area
            self.assertLess(
                zouit_overlap,
                0.05,
                f"Корпус {idx+1} залез на полигон ЗОУИТ (пересечение {zouit_overlap:.2f} м²)",
            )
            # Проверка: корпус полностью внутри допустимой зоны
            outside_area = b_poly.difference(buildable).area
            self.assertLess(
                outside_area,
                0.05,
                f"Корпус {idx+1} выходит за границы допустимой застройки (на {outside_area:.2f} м²)",
            )

    def test_gfa_monotonicity_no_collapse(self):
        """Инвариант 3: Рост этажности не должен приводить к обвалу суммарного GFA (Anti-Collapse)."""
        site = Site(boundary=Polygon([(0, 0), (220, 0), (220, 160), (0, 160)]))
        compute_buildable_area(site, self.config)
        engine = PlacementEngine(site, self.library, self.config)

        prev_gfa = 0.0
        # Проверяем монотонный рост плотности по шкале этажей: 9 -> 11 -> 13 -> 15 -> 17 эт.
        for fl in [9, 11, 13, 15, 17]:
            p_cfg = PlacementConfig(target_floors=fl, typology="AUTO")
            buildings = engine.generate(p_cfg)
            cur_gfa = sum(b.total_gfa for b in buildings)

            self.assertGreater(cur_gfa, 40000.0, f"GFA на {fl} эт. должен быть жизнеспособным (>40 000 м²)")
            if prev_gfa > 0:
                self.assertGreaterEqual(
                    cur_gfa,
                    prev_gfa * 0.98,
                    f"Обвал плотности при переходе на {fl} эт.! Было {prev_gfa:.0f} м², стало {cur_gfa:.0f} м²",
                )
            prev_gfa = cur_gfa

    def test_fire_safety_distances_between_buildings(self):
        """Инвариант 4: Противопожарные расстояния между отдельно стоящими зданиями >= 10.0 м (СП 4.13130)."""
        site = Site(boundary=Polygon([(0, 0), (250, 0), (250, 180), (0, 180)]))
        compute_buildable_area(site, self.config)

        engine = PlacementEngine(site, self.library, self.config)
        p_cfg = PlacementConfig(target_floors=14, typology="AUTO")
        buildings = engine.generate(p_cfg)

        if len(buildings) >= 2:
            for i in range(len(buildings)):
                for j in range(i + 1, len(buildings)):
                    b1_poly = getattr(buildings[i], "footprint", None) or buildings[i].polygon
                    b2_poly = getattr(buildings[j], "footprint", None) or buildings[j].polygon
                    dist = b1_poly.distance(b2_poly)
                    # Минимальный пожарный разрыв I-II степени огнестойкости (СП 4.13130) с допуском 0.1 м
                    self.assertGreaterEqual(
                        dist,
                        9.9,
                        f"Нарушен противопожарный разрыв между корпусами {i+1} и {j+1}: {dist:.2f} м < 10.0 м",
                    )

    def test_section_floors_within_legal_and_catalogue_limits(self):
        """Инвариант 5: Ни одна секция не превышает предельную разрешенную высоту и паспортные лимиты."""
        site = Site(boundary=Polygon([(0, 0), (180, 0), (180, 120), (0, 120)]))
        compute_buildable_area(site, self.config)

        engine = PlacementEngine(site, self.library, self.config)
        # Задаем жесткий предел высоты 45 метров (15 этажей при высоте 3 м)
        max_h = 45.0
        target_fl = 22  # Пользователь запросил 22 этажа
        p_cfg = PlacementConfig(
            target_floors=target_fl,
            max_building_height_m=max_h,
            floor_height=3.0,
            typology="AUTO",
        )
        buildings = engine.generate(p_cfg)

        for b in buildings:
            for s in b.sections:
                # 1. Секция не должна превышать предельный высотный регламент (15 эт.)
                self.assertLessEqual(
                    s.floors,
                    15,
                    f"Секция {s.section_type.id} имеет {s.floors} эт., что превышает лимит по высоте {max_h} м",
                )
                # 2. Секция не должна превышать собственный конструктивный максимум (из каталога)
                self.assertLessEqual(
                    s.floors,
                    s.section_type.max_floors,
                    f"Секция {s.section_type.id} имеет {s.floors} эт. при паспортном максимуме {s.section_type.max_floors}",
                )


if __name__ == "__main__":
    unittest.main()
