"""Тесты модуля расчета инсоляции жилой застройки (СанПиН 1.2.3685-21 и СП 42.13330)."""

import math
import unittest
from shapely.geometry import Polygon, box

from src.core.insolation import (
    FacadeFacet,
    FacadePointResult,
    InsolationCalculator,
    InsolationConfig,
    InsolationReport,
    SolarPosition,
    calculate_solar_position,
    get_sun_path,
)
from src.models.building import Building, PlacedSection
from src.models.section import SectionType


class TestInsolationSolarPosition(unittest.TestCase):
    """Тестирование астрономического алгоритма положения солнца."""

    def test_solar_position_at_noon(self):
        """В истинный полдень (12:00) азимут солнца строго на юг (180°)."""
        pos = calculate_solar_position(lat_deg=56.85, time_hour=12.0, day_of_year=112)
        self.assertAlmostEqual(pos.azimuth_deg, 180.0, delta=1.5)
        self.assertGreater(pos.elevation_deg, 40.0)
        self.assertLess(pos.elevation_deg, 50.0)

        # Единичный вектор
        vx, vy, vz = pos.sun_vector
        mag = math.sqrt(vx * vx + vy * vy + vz * vz)
        self.assertAlmostEqual(mag, 1.0, places=3)
        # В полдень вектор солнца направлен с юга на север (-Y)
        self.assertAlmostEqual(vx, 0.0, delta=0.05)
        self.assertLess(vy, 0.0)
        self.assertGreater(vz, 0.0)

    def test_solar_position_diurnal_cycle(self):
        """Утром солнце на востоке (азимут < 180°), вечером на западе (> 180°)."""
        pos_morning = calculate_solar_position(lat_deg=55.75, time_hour=9.0, day_of_year=112)
        pos_evening = calculate_solar_position(lat_deg=55.75, time_hour=15.0, day_of_year=112)

        self.assertLess(pos_morning.azimuth_deg, 180.0)
        self.assertGreater(pos_evening.azimuth_deg, 180.0)
        self.assertGreater(pos_morning.elevation_deg, 8.0)
        self.assertGreater(pos_evening.elevation_deg, 8.0)

    def test_sun_path_elevation_filter(self):
        """get_sun_path отсекает солнце ниже 8 градусов по СанПиН."""
        path = get_sun_path(lat_deg=56.85, day_of_year=112, start_hour=6.0, end_hour=20.0)
        self.assertGreater(len(path), 0)
        for p in path:
            self.assertGreaterEqual(p.elevation_deg, 8.0)


class TestInsolationCalculator(unittest.TestCase):
    """Тестирование движка расчета инсоляции и тепловых карт."""

    def setUp(self):
        self.mock_section = SectionType(
            id="test_sec",
            name="Тестовая секция",
            category="MIDDLE",
            width=30.0,
            depth=15.0,
            min_floors=4,
            max_floors=14,
            default_floors=9,
            floor_area=450.0,
            floor_height=3.15,
            ground_floor_height=4.20,
            has_commercial_ground=True,
            apartments_per_floor={"1k": 2, "2k": 2},
        )

    def test_single_building_south_facade_insolated(self):
        """Южный фасад отдельно стоящего корпуса должен получать нормативную инсоляцию."""
        # Размещаем широтный корпус (вытянут с запада на восток)
        # Южный фасад смотрит на -Y (юг)
        sec = PlacedSection(
            section_type=self.mock_section,
            x=50.0,
            y=50.0,
            angle=0.0,
            floors=9,
            floor_height=3.15,
            ground_floor_height=4.20,
        )
        b = Building(sections=[sec], typology="LINEAR")

        calc = InsolationCalculator(site_lat=56.85, site_lon=53.20, required_hours=2.0)
        report = calc.calculate_masterplan_insolation([b], include_surroundings=False)

        self.assertIsInstance(report, InsolationReport)
        self.assertGreater(report.total_facade_points, 0)
        self.assertGreater(report.compliant_points, 0)
        self.assertGreater(report.compliance_rate_percent, 40.0)
        self.assertGreater(len(report.facade_facets), 0)

        # Проверяем, что южные точки (normal_y < -0.8) получают много солнца (>= 2 ч)
        south_points = [p for p in report.facade_points if p.normal_y < -0.8]
        self.assertGreater(len(south_points), 0)
        for sp in south_points:
            self.assertGreaterEqual(sp.continuous_sun_hours, 2.0)
            self.assertEqual(sp.color_hex, "#10b981")

    def test_mutual_shading_between_buildings(self):
        """Южный корпус затеняет нижние этажи северного корпуса при близкой посадке."""
        # Южный корпус: y = 20, высота 40 м (14 эт.)
        sec_south = PlacedSection(
            section_type=self.mock_section,
            x=50.0,
            y=20.0,
            angle=0.0,
            floors=14,
            floor_height=3.15,
            ground_floor_height=4.20,
        )
        b_south = Building(sections=[sec_south], typology="LINEAR")

        # Северный корпус: y = 38 (разрыв всего 3 м между стенами при глубине 15 м)
        sec_north = PlacedSection(
            section_type=self.mock_section,
            x=50.0,
            y=38.0,
            angle=0.0,
            floors=14,
            floor_height=3.15,
            ground_floor_height=4.20,
        )
        b_north = Building(sections=[sec_north], typology="LINEAR")

        calc = InsolationCalculator(site_lat=56.85, site_lon=53.20, required_hours=2.0)
        report = calc.calculate_masterplan_insolation([b_south, b_north], include_surroundings=False)

        # На южном фасаде северного корпуса на 2 этаже должна быть тень
        north_b_pts = [p for p in report.facade_points if p.building_id == "b2" and p.normal_y < -0.8 and p.floor == 2]
        self.assertGreater(len(north_b_pts), 0)
        shaded_count = sum(1 for p in north_b_pts if not p.is_compliant or p.continuous_sun_hours < 2.0)
        self.assertGreater(shaded_count, 0)

    def test_geojson_facets_export(self):
        """Формирование 3D-граней для MapLibre GL JS fill-extrusion."""
        sec = PlacedSection(
            section_type=self.mock_section,
            x=0.0,
            y=0.0,
            angle=0.0,
            floors=6,
            floor_height=3.15,
            ground_floor_height=4.20,
        )
        b = Building(sections=[sec], typology="LINEAR")

        calc = InsolationCalculator(site_lat=56.85, site_lon=53.20, required_hours=2.0)
        report = calc.calculate_masterplan_insolation([b], include_surroundings=False)

        fc = report.to_geojson_facets(center_lat=56.85, center_lon=53.20)
        self.assertEqual(fc.get("type"), "FeatureCollection")
        features = fc.get("features", [])
        self.assertGreater(len(features), 0)

        f0 = features[0]
        self.assertEqual(f0["type"], "Feature")
        self.assertEqual(f0["geometry"]["type"], "Polygon")
        props = f0["properties"]
        self.assertIn("base_z", props)
        self.assertIn("top_z", props)
        self.assertIn("continuous_sun_hours", props)
        self.assertIn("color", props)
        self.assertIn(props["color"], ("#10b981", "#f59e0b", "#ef4444", "#94a3b8"))

    def test_corner_building_no_overlapping_facets_or_z_fighting(self):
        """Фасады угловых секций не должны иметь внутренних швов или пересечений на углах."""
        sec_corner = SectionType(
            id="corner_type",
            name="Угловая секция",
            category="CORNER",
            width=24.0,
            depth=24.0,
            min_floors=4,
            max_floors=12,
            default_floors=6,
            floor_area=400.0,
            floor_height=3.15,
            ground_floor_height=4.20,
            has_commercial_ground=True,
            apartments_per_floor={"1k": 2, "2k": 2},
        )
        s_corner = PlacedSection(sec_corner, x=20.0, y=20.0, angle=0.0, floors=6)
        s_mid = PlacedSection(self.mock_section, x=47.0, y=20.0, angle=0.0, floors=6)
        b = Building(sections=[s_corner, s_mid], typology="L_SHAPE")

        calc = InsolationCalculator(site_lat=56.85, site_lon=53.20, required_hours=2.0)
        report = calc.calculate_masterplan_insolation([b], include_surroundings=False)

        # Проверяем грани 2-го этажа на пересечение
        fl2_facets = [f for f in report.facade_facets if f.floor == 2]
        self.assertGreater(len(fl2_facets), 0)
        overlap_count = 0
        for i in range(len(fl2_facets)):
            for j in range(i + 1, len(fl2_facets)):
                inter = fl2_facets[i].polygon_metric.intersection(fl2_facets[j].polygon_metric)
                if inter.area > 1e-4:
                    overlap_count += 1

        self.assertEqual(overlap_count, 0, "Обнаружены пересекающиеся грани фасадов (рябь на углах)")

    def test_intermittent_insolation_sanpin(self):
        """Проверка прерывистой инсоляции по СанПиН 1.2.3685-21 (п. 164)."""
        sun_path = get_sun_path(lat_deg=56.85, day_of_year=112, start_hour=7.0, end_hour=19.0, step_minutes=30)
        dt_hour = 0.5
        req_hours = 2.0

        # Сценарий 1: Непрерывная инсоляция 2.5 ч (5 слотов подряд по 0.5 ч)
        timeline_cont = [False] * len(sun_path)
        for idx in range(2, 7):
            timeline_cont[idx] = True
        max_c, sum_q, t_type, is_ok, col, intervals = InsolationCalculator._analyze_intervals(
            timeline_cont, sun_path, dt_hour, req_hours, allow_intermittent=True
        )
        self.assertTrue(is_ok)
        self.assertEqual(t_type, "CONTINUOUS")
        self.assertEqual(col, "#10b981")
        self.assertAlmostEqual(max_c, 2.5)

        # Сценарий 2: Прерывистая норма — два интервала по 1.5 ч (3 слота + пауза + 3 слота), сумма 3.0 ч >= 2.5 ч
        timeline_interm = [False] * len(sun_path)
        for idx in (2, 3, 4):  # 1.5 ч утром
            timeline_interm[idx] = True
        # пауза (тень)
        for idx in (10, 11, 12):  # 1.5 ч днем
            timeline_interm[idx] = True

        max_c, sum_q, t_type, is_ok, col, intervals = InsolationCalculator._analyze_intervals(
            timeline_interm, sun_path, dt_hour, req_hours, allow_intermittent=True
        )
        self.assertTrue(is_ok, "Два интервала по 1.5 ч должны соответствовать прерывистой норме СанПиН")
        self.assertEqual(t_type, "INTERMITTENT_OK")
        self.assertEqual(col, "#06b6d4")
        self.assertAlmostEqual(sum_q, 3.0)

        # Сценарий 3: Прерывистый отказ — интервалы меньше 1.0 ч (например, три по 30 мин)
        timeline_fail = [False] * len(sun_path)
        timeline_fail[2] = True   # 30 мин
        timeline_fail[6] = True   # 30 мин
        timeline_fail[10] = True  # 30 мин
        max_c, sum_q, t_type, is_ok, col, intervals = InsolationCalculator._analyze_intervals(
            timeline_fail, sun_path, dt_hour, req_hours, allow_intermittent=True
        )
        self.assertFalse(is_ok, "Интервалы менее 1.0 ч не должны давать соответствие норме")
        self.assertIn(t_type, ("INTERMITTENT_FAIL", "SHADED"))

    def test_surrounding_height_overrides_and_impact(self):
        """Проверка ручного переопределения высот и расчета затенения окружающей застройки."""
        # Создаем окружающее здание на юге (x=50, y=0, габарит 30x15)
        surr_poly = box(35.0, -10.0, 65.0, 5.0)
        surr_feat = {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [list(surr_poly.exterior.coords)]},
            "properties": {
                "id": "osm_test_house_1",
                "name": "Тестовый соседний дом",
                "building_type": "apartments",
                "levels": 5,
                "height": 15.0,
            }
        }

        # Калькулятор с переопределением высоты с 15м на 45м
        calc = InsolationCalculator(
            site_lat=56.85,
            site_lon=53.20,
            required_hours=2.0,
            surrounding_buildings=[surr_feat],
            surrounding_height_overrides={"osm_test_house_1": 45.0},
        )
        # Проверяем, что переопределение применилось
        self.assertEqual(calc.surrounding_polys[0][1], 45.0)
        self.assertEqual(calc.surrounding_raw_items[0]["height_m"], 45.0)

        # Проектируемое здание
        sec = PlacedSection(self.mock_section, x=50.0, y=30.0, angle=0.0, floors=10)
        b = Building(sections=[sec], typology="LINEAR")

        impact = calc.calculate_surrounding_impact([b])
        self.assertIn("total_surrounding_checked", impact)
        self.assertEqual(impact["total_surrounding_checked"], 1)
        self.assertIn("buildings", impact)
        self.assertEqual(len(impact["buildings"]), 1)
        b_info = impact["buildings"][0]
        self.assertEqual(b_info["id"], "osm_test_house_1")
        self.assertTrue(b_info["is_overridden"])
        self.assertEqual(b_info["height_m"], 45.0)


if __name__ == "__main__":
    unittest.main()
