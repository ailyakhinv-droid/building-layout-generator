"""Тесты автоматической трассировки пожарных проездов по СП 4.13130.2020."""

import unittest
from shapely.geometry import box, Polygon

from src.core.fire_safety import FireAccessEngine, FireAccessNorms, FireAccessResult
from src.core.site_parser import create_rectangular_site
from src.library.section_library import SectionLibrary
from src.models.building import Building, PlacedSection


class TestFireAccessRoutes(unittest.TestCase):
    """Набор тестов для трассировки пожарных проездов."""

    @classmethod
    def setUpClass(cls):
        cls.library = SectionLibrary()
        cls.sec_mid = cls.library.get_by_id("mid_m8_9")   # 31.15 x 17.0 m
        cls.sec_tower = cls.library.get_by_id("tower_b1") # 29.7 x 23.9 m
        cls.engine = FireAccessEngine()

    def test_low_rise_parameters(self):
        """Для здания H <= 28 м отступ стены 5 м, ширина проезда 4.2 м."""
        # 8 этажей * 3.0 м = 24 м (<= 28 м)
        b = Building([PlacedSection(self.sec_mid, 100, 100, floors=8)])
        height = self.engine.get_building_height_m(b)
        self.assertLessEqual(height, 28.0)

        setback, width = self.engine.get_lane_parameters(height)
        self.assertEqual(setback, 5.0)
        self.assertEqual(width, 4.2)

    def test_high_rise_parameters(self):
        """Для здания H > 28 м (от 10 этажей) отступ стены 8 м, ширина проезда 4.2 м."""
        # 14 этажей * 3.0 м = 42 м (> 28 м, <= 46 м)
        b = Building([PlacedSection(self.sec_mid, 100, 100, floors=14)])
        height = self.engine.get_building_height_m(b)
        self.assertGreater(height, 28.0)
        self.assertLessEqual(height, 46.0)

        setback, width = self.engine.get_lane_parameters(height)
        self.assertEqual(setback, 8.0)
        self.assertEqual(width, 4.2)

    def test_tall_tower_parameters(self):
        """Для высотного здания H > 46 м (17+ этажей) ширина проезда увеличивается до 6.0 м."""
        # 24 этажа * 3.0 м = 72 м (> 46 м)
        b = Building([PlacedSection(self.sec_tower, 100, 100, floors=24)])
        height = self.engine.get_building_height_m(b)
        self.assertGreater(height, 46.0)

        setback, width = self.engine.get_lane_parameters(height)
        self.assertEqual(setback, 8.0)
        self.assertEqual(width, 6.0)

    def test_fire_lane_geometry_and_area(self):
        """Геометрия пожарного проезда вокруг дома формирует непрерывное кольцо."""
        site = create_rectangular_site(200, 200)
        b = Building([PlacedSection(self.sec_mid, 100, 100, floors=9)])

        res = self.engine.generate_fire_routes(site, [b], include_turnarounds=True)
        self.assertIsInstance(res, FireAccessResult)
        self.assertTrue(res.is_compliant)
        self.assertGreater(res.total_area_sqm, 500.0)
        self.assertGreater(res.total_length_m, 100.0)
        self.assertIsNotNone(res.all_fire_infrastructure)

    def test_turnaround_pad_size_15x15m(self):
        """Разворотные площадки имеют площадь не менее 15х15 = 225 м²."""
        site = create_rectangular_site(200, 200)
        b = Building([PlacedSection(self.sec_mid, 100, 100, floors=9)])

        res = self.engine.generate_fire_routes(site, [b], include_turnarounds=True)
        self.assertIsNotNone(res.turnarounds_polygon)
        self.assertGreaterEqual(res.turnarounds_area_sqm, 220.0)

    def test_detects_out_of_boundary_violation(self):
        """Если здание стоит в 2 метрах от забора, фиксируется нарушение СП 4.13130."""
        # Участок 100 x 100 м (границы x: 0..100, y: 0..100)
        site = create_rectangular_site(100, 100)
        # Здание посажено почти вплотную к правой границе x=100 (центр x=85, ширина 31.15 => правый край x=100.57)
        b_too_close = Building([PlacedSection(self.sec_mid, 82, 50, floors=12)])

        res = self.engine.generate_fire_routes(site, [b_too_close])
        self.assertFalse(res.is_compliant)
        self.assertGreater(len(res.issues), 0)
        self.assertTrue(any("выходит за границу участка" in issue for issue in res.issues))

    def test_geojson_features_structure(self):
        """GeoJSON экспортирует слои FIRE_ROADS и FIRE_CENTERLINE."""
        site = create_rectangular_site(150, 150)
        b = Building([PlacedSection(self.sec_mid, 75, 75, floors=8)])

        res = self.engine.generate_fire_routes(site, [b])
        gj = res.geojson
        self.assertEqual(gj.get("type"), "FeatureCollection")
        features = gj.get("features", [])
        self.assertGreater(len(features), 0)
        layers = [f["properties"].get("layer") for f in features]
        self.assertIn("FIRE_ROADS", layers)
        self.assertIn("FIRE_CENTERLINE", layers)


if __name__ == "__main__":
    unittest.main()
