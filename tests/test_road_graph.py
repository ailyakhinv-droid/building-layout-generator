"""Unit-тесты для графового слоя улично-дорожной сети (RoadGraph) и интеграции с RoadSlicer.

Проверяет:
1. Связность графа (nx.is_connected, доступность въездов entry, выявление isolated_nodes).
2. Планарность графа (nx.check_planarity, отсутствие геометрических самопересечений вне узлов).
3. Иерархию категорий дорог (матрица СП 42.13330, контроль подключения въездов).
4. Контроль категорий (custom по умолчанию, обязательность entry_category).
5. Построение геометрии и нарезку кварталов через RoadSlicer.build_from_graph.
6. Вычисление фронтов урбан-блоков (block_fronts).
7. Защиту от рассечения контуров зданий (check_building_intersections).
"""

from __future__ import annotations

import unittest
from shapely.geometry import Point, Polygon, box

from src.core.road_graph import Edge, Node, RoadGraph
from src.core.road_slicer import RoadSliceResult, RoadSlicer


class TestRoadGraphConnectivity(unittest.TestCase):
    """Тестирование правил связности графа УДС."""

    def test_valid_connected_graph_with_entry(self) -> None:
        """Связный граф с одним въездом и перекрестком валиден."""
        n_entry = Node(id="entry_1", position=Point(0, 50), kind="entry", entry_category="arterial")
        n_inter = Node(id="inter_1", position=Point(50, 50), kind="intersection")
        n_end = Node(id="end_1", position=Point(100, 50), kind="endpoint")

        e1 = Edge(id="e1", from_node=n_entry, to_node=n_inter, category="arterial", width=22.0, setback=6.0)
        e2 = Edge(id="e2", from_node=n_inter, to_node=n_end, category="district", width=15.0, setback=4.0)

        graph = RoadGraph([n_entry, n_inter, n_end], [e1, e2])
        report = graph.validate()

        self.assertTrue(report["is_valid"])
        self.assertTrue(report["connectivity"]["is_connected"])
        self.assertTrue(report["connectivity"]["has_entry"])
        self.assertEqual(len(report["connectivity"]["isolated_nodes"]), 0)
        self.assertEqual(len(report["errors"]), 0)

    def test_graph_without_entry_node_fails(self) -> None:
        """Граф без узла kind='entry' отклоняется с ошибкой."""
        n1 = Node(id="n1", position=Point(0, 0), kind="intersection")
        n2 = Node(id="n2", position=Point(50, 0), kind="endpoint")
        e1 = Edge(id="e1", from_node=n1, to_node=n2, category="district")

        graph = RoadGraph([n1, n2], [e1])
        report = graph.validate()

        self.assertFalse(report["is_valid"])
        self.assertFalse(report["connectivity"]["has_entry"])
        self.assertIn("отсутствует хотя бы один въезд", report["errors"][0])

    def test_disconnected_components_detected(self) -> None:
        """Несвязный граф или изолированный узел выявляется валидатором."""
        n_entry = Node(id="entry_1", position=Point(0, 50), kind="entry", entry_category="district")
        n1 = Node(id="n1", position=Point(50, 50), kind="endpoint")
        e1 = Edge(id="e1", from_node=n_entry, to_node=n1, category="district")

        # Изолированный узел без ребер
        n_isolated = Node(id="isolated_node", position=Point(80, 80), kind="intersection")

        graph = RoadGraph([n_entry, n1, n_isolated], [e1])
        report = graph.validate()

        self.assertFalse(report["is_valid"])
        self.assertFalse(report["connectivity"]["is_connected"])
        self.assertIn("isolated_node", report["connectivity"]["isolated_nodes"])


class TestRoadGraphPlanarity(unittest.TestCase):
    """Тестирование планарности графа УДС (геометрия + топология)."""

    def test_clean_t_junction_is_planar(self) -> None:
        """Т-образное примыкание с общим узлом планарно."""
        n_entry = Node(id="entry_1", position=Point(0, 50), kind="entry", entry_category="district")
        n_center = Node(id="center", position=Point(50, 50), kind="intersection")
        n_east = Node(id="east", position=Point(100, 50), kind="endpoint")
        n_north = Node(id="north", position=Point(50, 100), kind="endpoint")

        e_main_1 = Edge(id="e1", from_node=n_entry, to_node=n_center, category="district")
        e_main_2 = Edge(id="e2", from_node=n_center, to_node=n_east, category="district")
        e_branch = Edge(id="e3", from_node=n_center, to_node=n_north, category="local")

        graph = RoadGraph([n_entry, n_center, n_east, n_north], [e_main_1, e_main_2, e_branch])
        report = graph.validate()

        self.assertTrue(report["is_valid"])
        self.assertTrue(report["planarity"]["is_planar"])
        self.assertEqual(len(report["planarity"]["crossings"]), 0)

    def test_intersecting_edges_without_shared_node_detected(self) -> None:
        """Пересечение двух дорог крест-накрест без общего узла фиксируется как непланарность."""
        n_entry = Node(id="entry_1", position=Point(0, 50), kind="entry", entry_category="district")
        n_east = Node(id="east", position=Point(100, 50), kind="endpoint")
        e_horiz = Edge(id="e_horiz", from_node=n_entry, to_node=n_east, category="district")

        n_south = Node(id="south", position=Point(50, 0), kind="endpoint")
        n_north = Node(id="north", position=Point(50, 100), kind="endpoint")
        e_vert = Edge(id="e_vert", from_node=n_south, to_node=n_north, category="district")

        graph = RoadGraph([n_entry, n_east, n_south, n_north], [e_horiz, e_vert])
        report = graph.validate()

        self.assertFalse(report["is_valid"])
        self.assertFalse(report["planarity"]["is_planar"])
        self.assertGreaterEqual(len(report["planarity"]["crossings"]), 1)
        crossing = report["planarity"]["crossings"][0]
        self.assertEqual(crossing["type"], "cross_outside_nodes")
        self.assertEqual(crossing["intersection"], (50.0, 50.0))


class TestRoadGraphHierarchy(unittest.TestCase):
    """Тестирование матрицы разрешенных примыканий СП 42.13330."""

    def test_forbidden_arterial_to_local_junction(self) -> None:
        """Прямое примыкание arterial к local запрещено нормами СП 42.13330."""
        n_entry = Node(id="entry_1", position=Point(0, 50), kind="entry", entry_category="arterial")
        n_inter = Node(id="inter", position=Point(50, 50), kind="intersection")
        n_local_end = Node(id="end_local", position=Point(50, 100), kind="endpoint")

        e_art = Edge(id="e_art", from_node=n_entry, to_node=n_inter, category="arterial")
        # Прямое примыкание local к arterial в узле inter:
        e_loc = Edge(id="e_loc", from_node=n_inter, to_node=n_local_end, category="local")

        graph = RoadGraph([n_entry, n_inter, n_local_end], [e_art, e_loc])
        report = graph.validate()

        self.assertFalse(report["is_valid"])
        self.assertFalse(report["hierarchy"]["is_valid"])
        violations = report["hierarchy"]["violations"]
        self.assertTrue(any(v.get("category_1") in ("arterial", "local") for v in violations))

    def test_valid_hierarchy_arterial_district_local(self) -> None:
        """Правильная иерархия (arterial -> district -> local) полностью валидна."""
        n_entry = Node(id="entry_1", position=Point(0, 50), kind="entry", entry_category="arterial")
        n_int1 = Node(id="int1", position=Point(40, 50), kind="intersection")
        n_int2 = Node(id="int2", position=Point(80, 50), kind="intersection")
        n_end = Node(id="end", position=Point(80, 80), kind="endpoint")

        e1 = Edge(id="e1", from_node=n_entry, to_node=n_int1, category="arterial")
        e2 = Edge(id="e2", from_node=n_int1, to_node=n_int2, category="district")
        e3 = Edge(id="e3", from_node=n_int2, to_node=n_end, category="local")

        graph = RoadGraph([n_entry, n_int1, n_int2, n_end], [e1, e2, e3])
        report = graph.validate()

        self.assertTrue(report["is_valid"])
        self.assertTrue(report["hierarchy"]["is_valid"])

    def test_entry_without_entry_category_fails(self) -> None:
        """Въездной узел kind='entry' без указания entry_category отклоняется."""
        n_entry = Node(id="entry_1", position=Point(0, 50), kind="entry", entry_category=None)
        n_end = Node(id="end_1", position=Point(50, 50), kind="endpoint")
        e1 = Edge(id="e1", from_node=n_entry, to_node=n_end, category="district")

        graph = RoadGraph([n_entry, n_end], [e1])
        report = graph.validate()

        self.assertFalse(report["is_valid"])
        self.assertTrue(any("entry_category" in err for err in report["errors"]))


class TestRoadSlicerBuildFromGraph(unittest.TestCase):
    """Тестирование RoadSlicer.build_from_graph и генерации кварталов с фронтами."""

    def setUp(self) -> None:
        self.site_boundary = Polygon([(0, 0), (120, 0), (120, 100), (0, 100)])
        self.buildable_area = Polygon([(10, 10), (110, 10), (110, 90), (10, 90)])

    def test_build_from_graph_slices_blocks_and_computes_fronts(self) -> None:
        """Сквозная дорога делит зону на 2 блока, каждый блок получает фронт с категорией."""
        n_entry = Node(id="entry_w", position=Point(0, 50), kind="entry", entry_category="district")
        n_inter = Node(id="center", position=Point(60, 50), kind="intersection")
        n_exit = Node(id="exit_e", position=Point(120, 50), kind="endpoint")

        e1 = Edge(id="e_west", from_node=n_entry, to_node=n_inter, category="district", width=14.0, setback=4.0)
        e2 = Edge(id="e_east", from_node=n_inter, to_node=n_exit, category="district", width=14.0, setback=4.0)

        result = RoadSlicer.build_from_graph(
            nodes=[n_entry, n_inter, n_exit],
            edges=[e1, e2],
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
        )

        self.assertIsInstance(result, RoadSliceResult)
        self.assertIsNotNone(result.road_graph)
        self.assertTrue(result.validation_report.get("is_valid"))

        # Зона застройки должна быть разделена на 2 блока
        self.assertEqual(len(result.sub_blocks), 2)
        total_block_area = sum(b.area for b in result.sub_blocks)
        self.assertLess(total_block_area, self.buildable_area.area)

        # Проверка фронтов: оба блока должны граничить с ребрами e_west и e_east
        self.assertEqual(len(result.block_fronts), 2)
        for b_idx in range(len(result.sub_blocks)):
            front_edge_ids = [e.id for e in result.block_fronts[b_idx]]
            self.assertTrue("e_west" in front_edge_ids or "e_east" in front_edge_ids)
            # Категория фронта должна быть district
            for fe in result.block_fronts[b_idx]:
                self.assertEqual(fe.category, "district")

    def test_strict_mode_raises_on_invalid_graph(self) -> None:
        """При strict=True невалидный граф вызывает ValueError."""
        # Создаем граф с изолированным узлом
        n_entry = Node(id="entry_w", position=Point(0, 50), kind="entry", entry_category="district")
        n_iso = Node(id="iso", position=Point(100, 100), kind="intersection")

        with self.assertRaises(ValueError):
            RoadSlicer.build_from_graph(
                nodes=[n_entry, n_iso],
                edges=[],
                buildable_area=self.buildable_area,
                strict=True,
            )

    def test_non_strict_mode_returns_report_with_errors(self) -> None:
        """При strict=False результат возвращается с отчетом об ошибках без падения."""
        n_entry = Node(id="entry_w", position=Point(0, 50), kind="entry", entry_category="district")
        n_iso = Node(id="iso", position=Point(100, 100), kind="intersection")

        result = RoadSlicer.build_from_graph(
            nodes=[n_entry, n_iso],
            edges=[],
            buildable_area=self.buildable_area,
            strict=False,
        )

        self.assertFalse(result.validation_report["is_valid"])
        self.assertGreaterEqual(len(result.validation_report["errors"]), 1)

    def test_building_collision_detected(self) -> None:
        """Проверка ненарушения контуров: если дорога пересекает здание, фиксируется коллизия."""
        n_entry = Node(id="entry_w", position=Point(0, 50), kind="entry", entry_category="district")
        n_exit = Node(id="exit_e", position=Point(120, 50), kind="endpoint")
        e1 = Edge(id="e1", from_node=n_entry, to_node=n_exit, category="district", width=14.0, setback=4.0)

        # Здание, стоящее прямо на трассе дороги (y от 45 до 55)
        conflicting_building = box(40, 45, 60, 55)

        with self.assertRaises(ValueError):
            RoadSlicer.build_from_graph(
                nodes=[n_entry, n_exit],
                edges=[e1],
                buildable_area=self.buildable_area,
                site_boundary=self.site_boundary,
                buildings=[conflicting_building],
                strict=True,
            )


class TestRoadGraphContourNetwork(unittest.TestCase):
    """Тестирование контурной УДС вокруг застройки (Вариант А)."""

    def setUp(self) -> None:
        self.site_boundary = Polygon([(0, 0), (120, 0), (120, 100), (0, 100)])
        self.buildable_area = Polygon([(15, 15), (105, 15), (105, 85), (15, 85)])

    def test_contour_network_single_entry(self) -> None:
        """1 въезд формирует связный кольцевой проезд по контуру застройки."""
        entries = [{"id": "ep_west", "x": 0.0, "y": 50.0, "category": "district", "width": 14.0}]
        rg = RoadGraph.build_contour_network(
            site_boundary=self.site_boundary,
            buildable_area=self.buildable_area,
            entry_points=entries,
            connect_perimeter=True,
        )

        rep = rg.validate()
        self.assertTrue(rep["is_valid"])
        self.assertTrue(rep["connectivity"]["is_connected"])
        self.assertTrue(rep["planarity"]["is_planar"])
        self.assertEqual(len(rep["errors"]), 0)

    def test_contour_network_multiple_entries(self) -> None:
        """3 въезда с разных сторон связываются в единую контурную сеть."""
        entries = [
            {"id": "ep_w", "x": 0.0, "y": 50.0, "category": "district"},
            {"id": "ep_s", "x": 60.0, "y": 0.0, "category": "district"},
            {"id": "ep_e", "x": 120.0, "y": 50.0, "category": "district"},
        ]
        rg = RoadGraph.build_contour_network(
            site_boundary=self.site_boundary,
            buildable_area=self.buildable_area,
            entry_points=entries,
            connect_perimeter=True,
        )

        rep = rg.validate()
        self.assertTrue(rep["is_valid"])
        self.assertTrue(rep["connectivity"]["is_connected"])
        self.assertEqual(len(rep["connectivity"]["isolated_nodes"]), 0)

    def test_contour_network_preserves_inner_building(self) -> None:
        """Контурная дорога огибает застройку и не пересекает внутренние здания."""
        entries = [
            {"id": "ep_w", "x": 0.0, "y": 50.0, "category": "district"},
            {"id": "ep_s", "x": 60.0, "y": 0.0, "category": "district"},
        ]
        rg = RoadGraph.build_contour_network(
            site_boundary=self.site_boundary,
            buildable_area=self.buildable_area,
            entry_points=entries,
            connect_perimeter=True,
        )

        # Здание в центре двора (x от 30 до 70, y от 30 до 60)
        inner_building = box(30, 30, 70, 60)
        conflicts = rg.check_building_intersections([inner_building])
        self.assertEqual(len(conflicts), 0)

    def test_contour_slicer_builds_sub_block_and_fronts(self) -> None:
        """RoadSlicer успешно нарезает зону застройки с контурным графом и вычисляет фронты."""
        entries = [
            {"id": "ep_w", "x": 0.0, "y": 50.0, "category": "district", "width": 12.0, "setback": 3.0},
            {"id": "ep_e", "x": 120.0, "y": 50.0, "category": "district", "width": 12.0, "setback": 3.0},
        ]
        rg = RoadGraph.build_contour_network(
            site_boundary=self.site_boundary,
            buildable_area=self.buildable_area,
            entry_points=entries,
            connect_perimeter=True,
        )

        res = RoadSlicer.build_from_graph(
            nodes=rg,
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
            strict=True,
        )

        self.assertGreaterEqual(len(res.sub_blocks), 1)
        self.assertIn(0, res.block_fronts)
        self.assertGreater(len(res.block_fronts[0]), 0)


class TestRoadGraphSkeletonNetwork(unittest.TestCase):
    """Тестирование скелетной УДС (нарезка на урбан-блоки)."""

    def setUp(self) -> None:
        self.site_boundary = Polygon([(0, 0), (120, 0), (120, 100), (0, 100)])
        self.buildable_area = Polygon([(15, 15), (105, 15), (105, 85), (15, 85)])

    def test_skeleton_2_entries_slices_into_2_blocks(self) -> None:
        """2 противоположных въезда образуют сквозную улицу и делят участок на 2 квартала."""
        entries = [
            {"id": "ep_w", "x": 0.0, "y": 50.0, "category": "district", "width": 14.0, "setback": 3.0},
            {"id": "ep_e", "x": 120.0, "y": 50.0, "category": "district", "width": 14.0, "setback": 3.0},
        ]
        rg = RoadGraph.build_skeleton_network(
            site_boundary=self.site_boundary,
            buildable_area=self.buildable_area,
            entry_points=entries,
        )

        rep = rg.validate()
        self.assertTrue(rep["is_valid"])
        self.assertTrue(rep["connectivity"]["is_connected"])
        self.assertEqual(len(rg.edges), 1)

        res = RoadSlicer.build_from_graph(
            nodes=rg,
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
            strict=True,
        )
        self.assertEqual(len(res.sub_blocks), 2)
        self.assertEqual(len(res.block_fronts), 2)
        for b_idx in range(2):
            self.assertGreater(len(res.block_fronts[b_idx]), 0)

    def test_skeleton_3_entries_slices_into_3_blocks(self) -> None:
        """3 въезда образуют T-образный перекресток в центре и делят участок на 3 квартала."""
        entries = [
            {"id": "ep_w", "x": 0.0, "y": 50.0, "category": "district", "width": 12.0, "setback": 3.0},
            {"id": "ep_e", "x": 120.0, "y": 50.0, "category": "district", "width": 12.0, "setback": 3.0},
            {"id": "ep_n", "x": 60.0, "y": 100.0, "category": "district", "width": 12.0, "setback": 3.0},
        ]
        rg = RoadGraph.build_skeleton_network(
            site_boundary=self.site_boundary,
            buildable_area=self.buildable_area,
            entry_points=entries,
        )

        rep = rg.validate()
        self.assertTrue(rep["is_valid"])
        self.assertTrue(rep["connectivity"]["is_connected"])
        self.assertTrue(rep["planarity"]["is_planar"])
        self.assertEqual(len(rg.edges), 3)

        min_area = min(RoadSlicer.MIN_BLOCK_AREA, self.buildable_area.area * 0.05)
        res = RoadSlicer.build_from_graph(
            nodes=rg,
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
            min_block_area=min_area,
            strict=True,
        )
        self.assertEqual(len(res.sub_blocks), 3)
        self.assertEqual(len(res.block_fronts), 3)

    def test_skeleton_4_entries_slices_into_4_blocks(self) -> None:
        """4 въезда образуют крестообразный X-перекресток и делят участок на 4 квартала 2х2."""
        entries = [
            {"id": "ep_w", "x": 0.0, "y": 50.0, "category": "district", "width": 12.0, "setback": 3.0},
            {"id": "ep_e", "x": 120.0, "y": 50.0, "category": "district", "width": 12.0, "setback": 3.0},
            {"id": "ep_n", "x": 60.0, "y": 100.0, "category": "district", "width": 12.0, "setback": 3.0},
            {"id": "ep_s", "x": 60.0, "y": 0.0, "category": "district", "width": 12.0, "setback": 3.0},
        ]
        rg = RoadGraph.build_skeleton_network(
            site_boundary=self.site_boundary,
            buildable_area=self.buildable_area,
            entry_points=entries,
        )

        rep = rg.validate()
        self.assertTrue(rep["is_valid"])
        self.assertTrue(rep["connectivity"]["is_connected"])
        self.assertTrue(rep["planarity"]["is_planar"])
        self.assertEqual(len(rg.edges), 4)

        min_area = min(RoadSlicer.MIN_BLOCK_AREA, self.buildable_area.area * 0.05)
        res = RoadSlicer.build_from_graph(
            nodes=rg,
            buildable_area=self.buildable_area,
            site_boundary=self.site_boundary,
            min_block_area=min_area,
            strict=True,
        )
        self.assertEqual(len(res.sub_blocks), 4)
        self.assertEqual(len(res.block_fronts), 4)


if __name__ == "__main__":
    unittest.main()
