"""Unit-тесты для генератора естественной УДС (Natural Road Network).

Проверяет:
1. Построение естественной УДС для 1, 2, 3, 4 и 5 въездов.
2. Противоположные и смежные въезды (транзит и L-поворот).
3. Т-образное примыкание (T-Junction) для 3 въездов без острых клиньев.
4. Ортогональный перекресток (2x2 Grid) для 4 въездов.
5. Нарезку через RoadSlicer.build_from_graph на жизнеспособные прямоугольные урбан-блоки.
6. Вычисление фронтов кварталов (block_fronts).
"""

from __future__ import annotations

import unittest
from shapely.geometry import Point, Polygon, box

from src.core.natural_road_network import NaturalRoadGenerator
from src.core.road_graph import RoadGraph
from src.core.road_slicer import RoadSlicer


class TestNaturalRoadNetwork(unittest.TestCase):
    """Тестирование генерации естественной УДС по принципам мастер-планирования."""

    def setUp(self) -> None:
        self.site_boundary = Polygon([(0, 0), (120, 0), (120, 100), (0, 100)])
        self.buildable_area = self.site_boundary

    def test_single_entry_dead_end_turnaround(self) -> None:
        """1 въезд формирует створ и проезд внутрь к тупиковой разворотной точке."""
        entries = [{"id": "ep_1", "x": 0.0, "y": 50.0, "category": "district"}]
        rg = NaturalRoadGenerator.build_network(self.site_boundary, self.buildable_area, entries)
        rep = rg.validate()

        self.assertTrue(rep["is_valid"])
        self.assertTrue(rep["connectivity"]["is_connected"])
        self.assertTrue(rep["planarity"]["is_planar"])
        self.assertEqual(len(rg.nodes), 3)  # entry, portal, turnaround
        self.assertEqual(len(rg.edges), 2)  # stem, main street

    def test_two_opposite_entries_through_spine(self) -> None:
        """2 противоположных въезда образуют сквозную магистраль и 2 аккуратных квартала."""
        entries = [
            {"id": "ep_w", "x": 0.0, "y": 50.0, "category": "district", "width": 14.0, "setback": 3.0},
            {"id": "ep_e", "x": 120.0, "y": 50.0, "category": "district", "width": 14.0, "setback": 3.0},
        ]
        rg = NaturalRoadGenerator.build_network(self.site_boundary, self.buildable_area, entries)
        rep = rg.validate()

        self.assertTrue(rep["is_valid"])
        self.assertTrue(rep["connectivity"]["is_connected"])
        self.assertTrue(rep["planarity"]["is_planar"])

        res = RoadSlicer.build_from_graph(rg, buildable_area=self.buildable_area, site_boundary=self.site_boundary)
        self.assertEqual(len(res.sub_blocks), 2)
        for b_idx in range(2):
            self.assertGreater(len(res.block_fronts[b_idx]), 0)
            self.assertGreater(res.sub_blocks[b_idx].area, 3000.0)

    def test_two_adjacent_entries_l_turn(self) -> None:
        """2 смежных (угловых) въезда образуют ортогональный L-поворот."""
        entries = [
            {"id": "ep_w", "x": 0.0, "y": 50.0, "category": "district"},
            {"id": "ep_n", "x": 60.0, "y": 100.0, "category": "district"},
        ]
        rg = NaturalRoadGenerator.build_network(self.site_boundary, self.buildable_area, entries)
        rep = rg.validate()

        self.assertTrue(rep["is_valid"])
        self.assertTrue(rep["connectivity"]["is_connected"])
        self.assertTrue(rep["planarity"]["is_planar"])

        res = RoadSlicer.build_from_graph(rg, buildable_area=self.buildable_area, site_boundary=self.site_boundary)
        self.assertEqual(len(res.sub_blocks), 2)

    def test_three_entries_t_junction_slices_into_three_blocks(self) -> None:
        """3 въезда образуют Т-образное примыкание и делят участок ровно на 3 прямоугольных квартала."""
        entries = [
            {"id": "ep_w", "x": 0.0, "y": 50.0, "category": "district"},
            {"id": "ep_e", "x": 120.0, "y": 50.0, "category": "district"},
            {"id": "ep_n", "x": 60.0, "y": 100.0, "category": "district"},
        ]
        rg = NaturalRoadGenerator.build_network(self.site_boundary, self.buildable_area, entries)
        rep = rg.validate()

        self.assertTrue(rep["is_valid"])
        self.assertTrue(rep["connectivity"]["is_connected"])
        self.assertTrue(rep["planarity"]["is_planar"])

        res = RoadSlicer.build_from_graph(rg, buildable_area=self.buildable_area, site_boundary=self.site_boundary)
        self.assertEqual(len(res.sub_blocks), 3)
        self.assertEqual(len(res.block_fronts), 3)
        for b in res.sub_blocks:
            self.assertGreater(b.area, 1500.0)

    def test_four_entries_orthogonal_cross_slices_into_four_quadrants(self) -> None:
        """4 въезда образуют ортогональный перекресток 2x2 и делят участок на 4 квартала."""
        entries = [
            {"id": "ep_w", "x": 0.0, "y": 50.0, "category": "district"},
            {"id": "ep_e", "x": 120.0, "y": 50.0, "category": "district"},
            {"id": "ep_n", "x": 60.0, "y": 100.0, "category": "district"},
            {"id": "ep_s", "x": 60.0, "y": 0.0, "category": "district"},
        ]
        rg = NaturalRoadGenerator.build_network(self.site_boundary, self.buildable_area, entries)
        rep = rg.validate()

        self.assertTrue(rep["is_valid"])
        self.assertTrue(rep["connectivity"]["is_connected"])
        self.assertTrue(rep["planarity"]["is_planar"])

        res = RoadSlicer.build_from_graph(rg, buildable_area=self.buildable_area, site_boundary=self.site_boundary)
        self.assertEqual(len(res.sub_blocks), 4)
        self.assertEqual(len(res.block_fronts), 4)
        for b in res.sub_blocks:
            self.assertGreater(b.area, 1500.0)

    def test_five_entries_spine_and_ribs(self) -> None:
        """5 въездов образуют центральную магистраль (Spine) и ортогональные ребра (Ribs)."""
        entries = [
            {"id": "ep_w", "x": 0.0, "y": 50.0, "category": "district"},
            {"id": "ep_e", "x": 120.0, "y": 50.0, "category": "district"},
            {"id": "ep_n1", "x": 40.0, "y": 100.0, "category": "local"},
            {"id": "ep_n2", "x": 80.0, "y": 100.0, "category": "local"},
            {"id": "ep_s", "x": 60.0, "y": 0.0, "category": "local"},
        ]
        rg = NaturalRoadGenerator.build_network(self.site_boundary, self.buildable_area, entries)
        rep = rg.validate()

        self.assertTrue(rep["is_valid"])
        self.assertTrue(rep["connectivity"]["is_connected"])
        self.assertTrue(rep["planarity"]["is_planar"])

        res = RoadSlicer.build_from_graph(rg, buildable_area=self.buildable_area, site_boundary=self.site_boundary)
        self.assertGreaterEqual(len(res.sub_blocks), 3)

    def test_road_graph_class_method_delegation(self) -> None:
        """Проверка метода RoadGraph.build_natural_network."""
        entries = [
            {"id": "ep_1", "x": 0.0, "y": 50.0},
            {"id": "ep_2", "x": 120.0, "y": 50.0},
        ]
        rg = RoadGraph.build_natural_network(self.site_boundary, self.buildable_area, entries)
        rep = rg.validate()
        self.assertTrue(rep["is_valid"])


    def test_intersection_fillets_and_block_rounding(self) -> None:
        """Проверка скругления перекрестков и углов кварталов по СП 42.13330 п. 11.14."""
        entries = [
            {"id": "ep_w", "x": 0.0, "y": 50.0, "category": "district"},
            {"id": "ep_e", "x": 120.0, "y": 50.0, "category": "district"},
            {"id": "ep_n", "x": 60.0, "y": 100.0, "category": "district"},
        ]
        rg = NaturalRoadGenerator.build_network(self.site_boundary, self.buildable_area, entries)
        
        # 1. Без скругления (fillet_radius = 0)
        res_sharp = RoadSlicer.build_from_graph(
            rg,
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
            fillet_radius=0.0,
        )
        # 2. Со скруглением перекрестков (fillet_radius = 8.0)
        res_filleted = RoadSlicer.build_from_graph(
            rg,
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
            fillet_radius=8.0,
        )

        self.assertEqual(len(res_filleted.sub_blocks), 3)
        # Проверяем, что полигон дорог получил дополнительные сглаживающие вершины на сопряжениях
        self.assertGreater(
            len(res_filleted.roads_polygon.exterior.coords),
            len(res_sharp.roads_polygon.exterior.coords),
        )
        # Проверяем, что суб-блоки у Т-образного примыкания имеют скругленные углы (число вершин > 10)
        filleted_blocks_with_curves = [b for b in res_filleted.sub_blocks if len(b.exterior.coords) > 10]
        self.assertGreaterEqual(len(filleted_blocks_with_curves), 2)


if __name__ == "__main__":
    unittest.main()
