"""Тесты для модуля нарезки участка дорожной сетью (RoadSlicer)."""

import unittest
from shapely.geometry import Polygon, LineString, MultiPolygon
from src.core.road_slicer import RoadSlicer, RoadSliceResult


class TestRoadSlicer(unittest.TestCase):
    """Тестирование функциональности нарезки кварталов и автопродления луча."""

    def setUp(self):
        # Квадратный участок 100x100 м
        self.site_boundary = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        # Зона допустимой застройки с отступом 5 м от межи (90x90 м)
        self.buildable_area = Polygon([(5, 5), (95, 5), (95, 95), (5, 95)])

    def test_ray_extension_splits_buildable_area(self):
        """Проверка, что неполная линия внутри участка автоматически продлевается и делит квартал."""
        # Пользователь кликнул отрезок от (20, 50) до (80, 50) внутри участка, не доводя до границ
        short_line = [(20.0, 50.0), (80.0, 50.0)]

        res = RoadSlicer.slice_buildable_area(
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
            road_lines=[short_line],
            road_width=12.0,
            road_setback=3.0,
            extend_to_boundary=True,
        )

        # Должно получиться ровно 2 изолированных урбан-блока (северный и южный)
        self.assertEqual(len(res.sub_blocks), 2)
        # Суммарная площадь блоков должна быть меньше исходной за счет вычета коридора дороги (12 + 2*3 = 18 м)
        total_block_area = sum(b.area for b in res.sub_blocks)
        self.assertLess(total_block_area, self.buildable_area.area)

        # Осевая линия должна быть продлена и обрезана ровно по границе участка (длина = 100 м)
        self.assertEqual(len(res.centerlines), 1)
        self.assertAlmostEqual(res.centerlines[0].length, 100.0, places=1)

    def test_polyline_ray_extension(self):
        """Проверка автопродления для ломаной дороги из 3 точек."""
        polyline = [(30.0, 30.0), (50.0, 50.0), (70.0, 70.0)]

        res = RoadSlicer.slice_buildable_area(
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
            road_lines=[polyline],
            road_width=10.0,
            road_setback=2.0,
            extend_to_boundary=True,
        )

        self.assertGreaterEqual(len(res.sub_blocks), 2)
        # Асфальтовое полотно должно быть строго внутри границы участка
        self.assertTrue(self.site_boundary.contains(res.roads_polygon) or self.site_boundary.covers(res.roads_polygon))

    def test_without_extension_short_line_leaves_single_block(self):
        """Проверка: если автопродление выключено, неполный разрез оставляет 1 блок."""
        short_line = [(30.0, 50.0), (70.0, 50.0)]

        res = RoadSlicer.slice_buildable_area(
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
            road_lines=[short_line],
            road_width=10.0,
            road_setback=2.0,
            extend_to_boundary=False,
        )

        # Не доходящая до краев линия не делит полигон на 2 части
        self.assertEqual(len(res.sub_blocks), 1)

    def test_three_way_intersection(self):
        """Перекресток из 3-х дорог (Y-образный или Т-образный в центре) делит участок ровно на 3 квартала."""
        # 3 дороги, сходящиеся в центральной точке (50, 50)
        r1 = [(50.0, 0.0), (50.0, 50.0)]
        r2 = [(50.0, 50.0), (100.0, 100.0)]
        r3 = [(50.0, 50.0), (0.0, 100.0)]

        res = RoadSlicer.slice_buildable_area(
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
            road_lines=[r1, r2, r3],
            road_width=10.0,
            road_setback=2.0,
        )

        # Ровно 3 квартала без паразитных сквозных разрезов
        self.assertEqual(len(res.sub_blocks), 3)
        self.assertEqual(len(res.centerlines), 3)

    def test_t_junction_does_not_split_opposite_block(self):
        """Т-образный перекресток делит участок на 3 квартала, оставляя противоположную половину цельной."""
        # Дорога 1: сквозная вертикальная от (50, 0) до (50, 100)
        r1 = [(50.0, 0.0), (50.0, 100.0)]
        # Дорога 2: примыкающая горизонтальная от (50, 50) до восточной границы (100, 50)
        r2 = [(50.0, 50.0), (100.0, 50.0)]

        res = RoadSlicer.slice_buildable_area(
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
            road_lines=[r1, r2],
            road_width=10.0,
            road_setback=2.0,
        )

        # Ровно 3 квартала: 1 большой западный (цельный) + 2 восточных (северо-восточный и юго-восточный)
        self.assertEqual(len(res.sub_blocks), 3)
        self.assertEqual(len(res.centerlines), 2)

    def test_three_way_intersection_with_near_boundary_clicks(self):
        """Перекресток из 3-х дорог, где внешние точки кликнуты близко к меже (зазор 2-3 м), чисто режет 3 квартала."""
        # 3 дороги сходятся в (50, 50), а внешние концы находятся в 2 м от границы:
        r1 = [(50.0, 2.0), (50.0, 50.0)]
        r2 = [(50.0, 50.0), (98.0, 98.0)]
        r3 = [(50.0, 50.0), (2.0, 98.0)]

        res = RoadSlicer.slice_buildable_area(
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
            road_lines=[r1, r2, r3],
            road_width=10.0,
            road_setback=2.0,
        )

        self.assertEqual(len(res.sub_blocks), 3)


if __name__ == "__main__":
    unittest.main()
