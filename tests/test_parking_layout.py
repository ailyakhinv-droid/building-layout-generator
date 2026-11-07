"""Тесты генерации парковочных пространств и концепции «Двор без машин»."""

import unittest
from shapely.geometry import box
from shapely.ops import unary_union

from src.core.parking_layout import generate_parking_layout, ParkingLayoutResult
from src.core.site_parser import create_rectangular_site
from src.library.section_library import SectionLibrary
from src.models.building import Building, PlacedSection


class TestParkingLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = SectionLibrary()
        cls.sec_mid = cls.library.get_by_id("mid_m8_9")  # 31.15 x 17.0 m
        cls.site = create_rectangular_site(160, 140)     # 22,400 m²

        # Две секции образуют двор между ними
        cls.b1 = Building([PlacedSection(cls.sec_mid, 50, 70, floors=8)])
        cls.b2 = Building([PlacedSection(cls.sec_mid, 110, 70, floors=8)])
        cls.buildings = [cls.b1, cls.b2]

    def test_car_free_courtyard_places_slots_on_perimeter(self):
        """Концепция «Двор без машин» размещает места только на внешнем периметре."""
        res = generate_parking_layout(
            site=self.site,
            buildings=self.buildings,
            target_spaces=80,
            car_free_courtyard=True,
        )
        self.assertIsInstance(res, ParkingLayoutResult)
        self.assertGreater(res.slots_count, 20)
        self.assertTrue(res.car_free_courtyard)
        self.assertEqual(res.courtyard_slots_count, 0)
        self.assertEqual(res.perimeter_slots_count, res.slots_count)

        # Проверяем, что ни один слот не попал в центральную зону двора
        b_union = unary_union([self.b1.footprint, self.b2.footprint])
        courtyard_center = b_union.convex_hull.centroid
        for slot in res.slots:
            dist = slot.polygon.distance(courtyard_center)
            self.assertGreater(dist, 10.0, "Парковочное место обнаружено внутри двора!")

    def test_zero_target_spaces(self):
        """Если target_spaces == 0, возвращается пустой результат без ошибок."""
        res = generate_parking_layout(
            site=self.site,
            buildings=self.buildings,
            target_spaces=0,
            car_free_courtyard=True,
        )
        self.assertEqual(res.slots_count, 0)
        self.assertIsNone(res.bays_polygon)

    def test_zouit_exclusion_by_default(self):
        """По умолчанию парковки не размещаются в охранных зонах ЗОУИТ."""
        # Добавляем охранную зону в южной части (y: 0..30)
        from shapely.geometry import box
        zouit_box = box(0, 0, 160, 30)
        self.site.zouit_polygons = [zouit_box]
        self.site.zouit_info = [{"name": "Охранная зона ЛЭП 110 кВ"}]

        try:
            res_strict = generate_parking_layout(
                site=self.site,
                buildings=self.buildings,
                target_spaces=60,
                car_free_courtyard=True,
                allow_parking_in_zouit=False,
            )
            # В строгом режиме ни один слот не должен пересекать ЗОУИТ
            self.assertEqual(res_strict.zouit_slots_count, 0)
            for s in res_strict.slots:
                self.assertFalse(s.polygon.intersection(zouit_box).area > 0.1, "Слот размещен в охранной зоне!")
        finally:
            self.site.zouit_polygons = []
            self.site.zouit_info = []

    def test_roads_exclusion_and_gate_clearance(self):
        """Парковки строго не залезают на проезжую часть дорог и не перекрывают въездные створы."""
        from shapely.geometry import LineString
        road_centerline = LineString([(80, -20), (80, 160)])
        road_poly = road_centerline.buffer(8.0).intersection(self.site.boundary)

        res = generate_parking_layout(
            site=self.site,
            buildings=self.buildings,
            target_spaces=60,
            car_free_courtyard=True,
            roads_poly=road_poly,
            road_centerlines=[road_centerline],
        )

        self.assertGreater(res.slots_count, 0)
        # 1. Ни один слот не должен пересекать проезжую часть дороги
        for slot in res.slots:
            inter_area = slot.polygon.intersection(road_poly).area
            self.assertEqual(inter_area, 0.0, f"Слот пересекает проезжую часть дороги: area={inter_area}")

        # 2. Объединенный полигон стоянок не пересекает дорогу
        if res.bays_polygon:
            bays_inter = res.bays_polygon.intersection(road_poly).area
            self.assertLess(bays_inter, 0.01, f"Полигон стоянок пересекает дорогу: area={bays_inter}")

    def test_geojson_export(self):
        """Формируется корректная коллекция фич GeoJSON."""
        res = generate_parking_layout(
            site=self.site,
            buildings=self.buildings,
            target_spaces=40,
            car_free_courtyard=True,
        )
        gj = res.geojson
        self.assertEqual(gj.get("type"), "FeatureCollection")
        self.assertGreater(len(gj.get("features", [])), 0)

    def test_narrow_tail_exclusion(self):
        """В узком клиновидном хвосте участка (< 12 м) машиноместа не размещаются."""
        from shapely.geometry import Polygon
        from src.models.site import Site

        # Участок с сужающимся клином (хвостом) до 4 метров
        wedge_site = Site(boundary=Polygon([(0, 0), (200, 0), (200, 5), (100, 30), (0, 80), (0, 0)]))
        res = generate_parking_layout(
            site=wedge_site,
            buildings=self.buildings,
            target_spaces=60,
            car_free_courtyard=True,
        )
        # Все размещенные слоты должны находиться в широкой части участка (x < 150)
        for s in res.slots:
            self.assertLess(s.polygon.centroid.x, 160.0, "Слот размещен в узком хвосте участка!")

    def test_driveway_cannot_overlap_zouit(self):
        """Ни машиноместо, ни зона маневрирования перед ним не могут заходить в ЗОУИТ."""
        from shapely.geometry import box
        # ЗОУИТ примыкает к южной части участка (y: 10..40)
        zouit_poly = box(0, 10.0, 160, 40)
        self.site.zouit_polygons = [zouit_poly]
        self.site.zouit_info = [{"name": "Охранная зона водопровода"}]

        try:
            res = generate_parking_layout(
                site=self.site,
                buildings=self.buildings,
                target_spaces=50,
                car_free_courtyard=True,
                allow_parking_in_zouit=False,
            )
            self.assertGreater(res.slots_count, 0)
            for s in res.slots:
                # Машиноместо категорически не должно пересекать ЗОУИТ
                self.assertFalse(s.polygon.intersects(zouit_poly), "Слот пересекает ЗОУИТ!")
        finally:
            self.site.zouit_polygons = []
            self.site.zouit_info = []


if __name__ == "__main__":
    unittest.main()
