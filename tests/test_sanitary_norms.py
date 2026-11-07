"""Unit-тесты для модуля санитарных норм и разрывов (СанПиН 2.2.1/2.1.1.1200-03 и СанПиН 2.1.3684-21)."""

import unittest
from shapely.geometry import Polygon, Point, box

from src.core.sanitary_norms import (
    SanitaryNormsEngine,
    SanitaryParkingNorms,
    WasteCollectionNorms,
)
from src.models.building import Building, PlacedSection
from src.models.section import SectionType
from src.models.site import Site


class TestSanitaryNorms(unittest.TestCase):
    def setUp(self):
        # Тестовый участок 200 x 200 м (4 га)
        self.site_poly = box(0, 0, 200, 200)
        self.site = Site(boundary=self.site_poly)

        # Тестовая типовая секция (30 x 15 м, 9 этажей)
        self.sec_type = SectionType(
            id="mid_test",
            name="Тестовая секция",
            category="MIDDLE",
            width=30.0,
            depth=15.0,
            min_floors=5,
            max_floors=16,
            default_floors=9,
            floor_area=450.0,
        )

        # Размещаем 2 жилых корпуса в центре участка
        sec1 = PlacedSection(self.sec_type, x=80, y=100, floors=9)
        sec2 = PlacedSection(self.sec_type, x=130, y=100, floors=9)
        self.b1 = Building(sections=[sec1])
        self.b2 = Building(sections=[sec2])
        self.buildings = [self.b1, self.b2]

        self.engine = SanitaryNormsEngine()

    def test_parking_sanitary_buffers(self):
        """Проверка построения санитарных буферов открытых парковок (10м, 15м, 25м)."""
        res = self.engine.analyze_sanitary_parking(self.site, self.buildings)

        # Буфер 10м должен существовать и покрывать окрестность домов
        self.assertIsNotNone(res["buf_10m"])
        self.assertFalse(res["buf_10m"].is_empty)

        # Буфер 15м должен быть больше 10м
        self.assertGreater(res["buf_15m"].area, res["buf_10m"].area)

        # Допустимый конверт для размещения парковок должен быть внутри ЗУ
        self.assertTrue(self.site_poly.contains(res["allowed_envelope"]))
        self.assertGreater(res["allowed_envelope"].area, 1000.0)

    def test_waste_site_distance_to_windows_gte_20m(self):
        """Проверка правила: площадки ТКО располагаются не ближе 20м от окон жилья (СанПиН 2.1.3684-21)."""
        waste_sites = self.engine.generate_waste_collection_sites(
            self.site, self.buildings, population=1200
        )
        self.assertGreater(len(waste_sites), 0)

        b_union = self.engine.get_building_union(self.buildings)
        for ws in waste_sites:
            dist = ws.centroid.distance(b_union)
            # Должно быть не менее 20м (с учетом допустимой погрешности 0.5м)
            self.assertGreaterEqual(
                dist, 19.5,
                f"Площадка ТКО {ws.id} расположена слишком близко к дому ({dist:.1f}м < 20м)"
            )
            self.assertTrue(ws.is_compliant)

    def test_waste_site_walking_radius_100m(self):
        """Проверка правила: радиус доступности ТКО от подъездов не более 100м."""
        waste_sites = self.engine.generate_waste_collection_sites(
            self.site, self.buildings, population=1200
        )
        self.assertGreater(len(waste_sites), 0)

        # Проверяем, что хотя бы одна площадка находится в пределах 100м от каждой секции
        entrances = self.engine.get_building_entrances_or_centroids(self.buildings)
        for ep in entrances:
            min_dist = min(ws.centroid.distance(ep) for ws in waste_sites)
            self.assertLessEqual(
                min_dist, 100.0,
                f"Подъезд на удалении {min_dist:.1f}м превышает норматив доступности ТКО 100м"
            )

    def test_containers_count_scaling_with_population(self):
        """Проверка расчета контейнеров в зависимости от населения."""
        res_small = self.engine.analyze_site(self.site, self.buildings, population=300)
        res_large = self.engine.analyze_site(self.site, self.buildings, population=2400)

        # Для большего населения требуется больше контейнеров
        self.assertGreater(res_large.total_containers_count, res_small.total_containers_count)
        self.assertGreaterEqual(res_large.total_containers_count, 10)

    def test_playgrounds_sanitary_buffer_exclusion(self):
        """Проверка исключения детских площадок из зоны размещения стоянок (разрыв 25м)."""
        play_poly = box(70, 70, 90, 90)
        res = self.engine.analyze_sanitary_parking(
            self.site, self.buildings, playgrounds_polygon=play_poly
        )
        # Допустимый конверт для стоянок не должен пересекаться с детской площадкой
        self.assertFalse(res["allowed_envelope"].intersects(play_poly))

    def test_full_sanitary_analysis_summary(self):
        """Проверка комплексного результата анализа ЗУ."""
        full_res = self.engine.analyze_site(self.site, self.buildings, population=1500)
        self.assertTrue(full_res.waste_is_compliant)
        self.assertEqual(full_res.waste_coverage_pct, 100.0)
        self.assertGreater(len(full_res.summary_notes), 0)


if __name__ == "__main__":
    unittest.main()
