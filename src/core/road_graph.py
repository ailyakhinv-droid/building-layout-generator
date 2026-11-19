"""Графовый слой улично-дорожной сети (RoadGraph).

Предоставляет типизированную топологическую модель улично-дорожной сети (УДС):
- Узлы (Node): въезды (entry), перекрестки (intersection), тупики (endpoint).
- Ребра (Edge): участки дорог между узлами с категориями (arterial, district, local, custom).
- Граф (RoadGraph): структура на базе NetworkX и Shapely с валидацией связности,
  планарности и иерархии категорий примыканий по СП 42.13330 и СП 4.13130.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Sequence

import networkx as nx
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, mapping
from shapely.ops import nearest_points


# Матрица допустимых примыканий категорий дорог (СП 42.13330 п. 11.4)
# arterial: магистральная улица районного значения (22 м)
# district: внутриквартальная улица (15 м)
# local: местный / пожарный проезд (8 м)
# custom: настраиваемая
ALLOWED_JUNCTIONS: dict[str, set[str]] = {
    "arterial": {"arterial", "district"},
    "district": {"arterial", "district", "local", "custom"},
    "local": {"district", "local", "custom"},
    "custom": {"arterial", "district", "local", "custom"},
}

# Допустимые категории первого внутреннего ребра от внешнего въезда
ENTRY_ALLOWED_INTERNAL_EDGES: dict[str, set[str]] = {
    "arterial": {"arterial", "district"},
    "district": {"arterial", "district", "local", "custom"},
    "local": {"district", "local", "custom"},
    "custom": {"arterial", "district", "local", "custom"},
}

# Нормативные параметры категорий по умолчанию (СП 42.13330 / СП 4.13130)
DEFAULT_CATEGORY_PARAMS: dict[str, dict[str, float]] = {
    "arterial": {"width": 22.0, "setback": 6.0},
    "district": {"width": 15.0, "setback": 4.0},
    "local": {"width": 8.0, "setback": 3.0},
    "custom": {"width": 16.0, "setback": 4.0},
}


@dataclass
class Node:
    """Типизированный узел графа улично-дорожной сети.

    Attributes:
        id: Уникальный строковый идентификатор узла.
        position: Координаты узла (Point в локальной метрической СК участка).
        kind: Роль узла:
            - 'entry': точка подключения к внешней улично-дорожной сети на границе ЗУ;
            - 'intersection': внутренний перекресток дорог;
            - 'endpoint': тупик или разворотная площадка проезда.
        entry_category: Для kind='entry' — категория внешней дороги подключения
            ('arterial', 'district', 'local').
    """

    id: str
    position: Point
    kind: str = "intersection"  # "entry" | "intersection" | "endpoint"
    entry_category: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.position, Point):
            if isinstance(self.position, (tuple, list)) and len(self.position) >= 2:
                self.position = Point(float(self.position[0]), float(self.position[1]))
            else:
                raise TypeError(f"position must be a shapely Point, got {type(self.position)}")

        self.kind = str(self.kind).lower()
        if self.entry_category:
            self.entry_category = str(self.entry_category).lower()

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Node):
            return False
        return self.id == other.id


@dataclass
class Edge:
    """Типизированное ребро (участок дороги) между узлами графа УДС.

    Attributes:
        id: Уникальный строковый идентификатор ребра.
        from_node: Начальный узел.
        to_node: Конечный узел.
        category: Категория дороги ('arterial', 'district', 'local', 'custom').
        width: Ширина проезжей части в метрах.
        setback: Отступ от края проезжей части до линии застройки (road_setback) в метрах.
    """

    id: str
    from_node: Node
    to_node: Node
    category: str = "district"
    width: float = 15.0
    setback: float = 4.0
    geometry: LineString | None = None

    def __post_init__(self) -> None:
        raw_cat = (self.category or "").strip().lower()
        if not raw_cat:
            warnings.warn(f"У ребра '{self.id}' не задана категория. Присвоена категория 'custom'.")
            raw_cat = "custom"
        self.category = raw_cat

        # Автоматическая подстановка нормативных значений, если ширина или отступ не переданы
        if self.category in DEFAULT_CATEGORY_PARAMS:
            defaults = DEFAULT_CATEGORY_PARAMS[self.category]
            if self.width is None or self.width <= 0:
                self.width = defaults["width"]
            if self.setback is None or self.setback < 0:
                self.setback = defaults["setback"]

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Edge):
            return False
        return self.id == other.id

    @property
    def line(self) -> LineString:
        """Осевая линия ребра как Shapely LineString."""
        if self.geometry is not None and not self.geometry.is_empty:
            return self.geometry
        return LineString([
            (self.from_node.position.x, self.from_node.position.y),
            (self.to_node.position.x, self.to_node.position.y),
        ])

    @property
    def length(self) -> float:
        """Длина участка дороги в метрах."""
        return float(self.line.length)

    def poly_asphalt(self) -> Polygon:
        """Полигон асфальтового покрытия (буфер radius = width / 2)."""
        half_w = max(1.5, self.width / 2.0)
        return self.line.buffer(half_w, cap_style="flat", join_style="mitre")

    def poly_cut(self) -> Polygon:
        """Полигон коридора вырезки застройки (буфер radius = width / 2 + setback)."""
        cut_half = max(1.5, self.width / 2.0) + max(0.0, self.setback)
        return self.line.buffer(cut_half, cap_style="flat", join_style="mitre")


class RoadGraph:
    """Топологический граф улично-дорожной сети на базе NetworkX и Shapely.

    Выполняет:
    1. Построение графовой структуры дорог и узлов;
    2. Комплексную валидацию:
       - Связность (nx.is_connected, доступность въездов entry);
       - Планарность (nx.check_planarity, отсутствие геометрических самопересечений вне узлов);
       - Иерархия примыканий (матрица примыканий СП 42.13330 и проверка въездов).
    """

    def __init__(self, nodes: Sequence[Node] | None = None, edges: Sequence[Edge] | None = None) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}
        self.nx_graph: nx.Graph = nx.Graph()

        if nodes:
            for n in nodes:
                self.add_node(n)
        if edges:
            for e in edges:
                self.add_edge(e)

    def add_node(self, node: Node) -> None:
        """Добавить узел в граф."""
        self.nodes[node.id] = node
        self.nx_graph.add_node(
            node.id,
            position=node.position,
            kind=node.kind,
            entry_category=node.entry_category,
        )

    def add_edge(self, edge: Edge) -> None:
        """Добавить ребро в граф (при необходимости добавляет инцидентные узлы)."""
        if edge.from_node.id not in self.nodes:
            self.add_node(edge.from_node)
        if edge.to_node.id not in self.nodes:
            self.add_node(edge.to_node)

        self.edges[edge.id] = edge
        self.nx_graph.add_edge(
            edge.from_node.id,
            edge.to_node.id,
            id=edge.id,
            category=edge.category,
            width=edge.width,
            setback=edge.setback,
            edge_obj=edge,
        )

    def get_incident_edges(self, node_id: str) -> list[Edge]:
        """Получить список всех ребер, инцидентных заданному узлу."""
        incident = []
        for e in self.edges.values():
            if e.from_node.id == node_id or e.to_node.id == node_id:
                incident.append(e)
        return incident

    def validate(self) -> dict[str, Any]:
        """Полная валидация графа УДС на связность, планарность и иерархию категорий.

        Returns:
            Словарь отчета валидации validation_report:
            {
                "is_valid": bool,
                "connectivity": { ... },
                "planarity": { ... },
                "hierarchy": { ... },
                "errors": list[str],
                "warnings": list[str],
            }
        """
        errors: list[str] = []
        warnings_list: list[str] = []

        # -------------------------------------------------------------
        # 1. Валидация контроля категорий и входных данных
        # -------------------------------------------------------------
        for nid, node in self.nodes.items():
            if node.kind == "entry" and not node.entry_category:
                errors.append(
                    f"У въездного узла '{nid}' не задана entry_category. "
                    f"Невозможно выполнить валидацию иерархии подключения к внешней УДС."
                )

        for eid, edge in self.edges.items():
            if not edge.category or edge.category == "custom":
                # Предупреждение, но не критическая ошибка
                warnings_list.append(f"Ребро '{eid}' имеет категорию 'custom' или не задано явно.")

        # -------------------------------------------------------------
        # 2. Валидация связности (Connectivity)
        # -------------------------------------------------------------
        connectivity_report: dict[str, Any] = {
            "is_connected": False,
            "has_entry": False,
            "isolated_nodes": [],
            "error": None,
        }

        if len(self.nodes) == 0:
            connectivity_report["is_connected"] = True
        else:
            is_conn = nx.is_connected(self.nx_graph) if len(self.edges) > 0 else (len(self.nodes) == 1)
            connectivity_report["is_connected"] = is_conn

            entry_nodes = [n for n in self.nodes.values() if n.kind == "entry"]
            connectivity_report["has_entry"] = len(entry_nodes) > 0

            if not entry_nodes:
                err_msg = "В графе УДС отсутствует хотя бы один въезд (узел с kind='entry')."
                connectivity_report["error"] = err_msg
                connectivity_report["isolated_nodes"] = list(self.nodes.keys())
                errors.append(err_msg)
            else:
                # Находим узлы, имеющие путь хотя бы к одному въезду (entry)
                reachable_from_entry: set[str] = set()
                for en in entry_nodes:
                    if en.id in self.nx_graph:
                        reachable_from_entry.update(nx.node_connected_component(self.nx_graph, en.id))

                isolated = [nid for nid in self.nodes if nid not in reachable_from_entry]
                connectivity_report["isolated_nodes"] = isolated

                if not is_conn:
                    err_msg = f"Граф УДС не является связным (содержит {nx.number_connected_components(self.nx_graph)} компоненты связности)."
                    connectivity_report["error"] = err_msg
                    errors.append(err_msg)

                if isolated:
                    err_msg = f"Обнаружены изолированные узлы без доступа к въездам (entry): {isolated}."
                    if not connectivity_report["error"]:
                        connectivity_report["error"] = err_msg
                    errors.append(err_msg)

        # -------------------------------------------------------------
        # 3. Валидация планарности (Planarity)
        # -------------------------------------------------------------
        planarity_report: dict[str, Any] = {
            "is_planar": True,
            "crossings": [],
            "error": None,
        }

        # А. Топологическая планарность NetworkX
        nx_planar, _ = nx.check_planarity(self.nx_graph)
        if not nx_planar:
            planarity_report["is_planar"] = False
            err_msg = "Граф топологически непланарен (содержит непланарный минор K5 или K3,3)."
            planarity_report["error"] = err_msg
            errors.append(err_msg)

        # Б. Геометрическое пересечение 2D-отрезков ребер вне общих узлов
        edge_list = list(self.edges.values())
        crossings = []
        for i in range(len(edge_list)):
            for j in range(i + 1, len(edge_list)):
                e1 = edge_list[i]
                e2 = edge_list[j]
                shared = {e1.from_node.id, e1.to_node.id} & {e2.from_node.id, e2.to_node.id}

                l1 = e1.line
                l2 = e2.line
                if not shared:
                    if l1.intersects(l2):
                        inter = l1.intersection(l2)
                        if not inter.is_empty:
                            pt_coord = None
                            if isinstance(inter, Point):
                                pt_coord = (round(inter.x, 2), round(inter.y, 2))
                            crossings.append({
                                "edge_1": e1.id,
                                "edge_2": e2.id,
                                "intersection": pt_coord,
                                "type": "cross_outside_nodes",
                            })
                else:
                    # Имеют общий узел — проверяем, нет ли наложения отрезков (коллинеарного перекрытия)
                    inter = l1.intersection(l2)
                    if isinstance(inter, (LineString, MultiLineString)) and inter.length > 1e-4:
                        crossings.append({
                            "edge_1": e1.id,
                            "edge_2": e2.id,
                            "type": "collinear_overlap",
                        })

        if crossings:
            planarity_report["is_planar"] = False
            planarity_report["crossings"] = crossings
            err_msg = (
                f"Рёбра графа пересекаются вне узлов (выявлено {len(crossings)} пересечений). "
                f"Необходимо добавить узлы-перекрестки в точках пересечений: "
                f"{[(c['edge_1'], c['edge_2']) for c in crossings]}"
            )
            planarity_report["error"] = err_msg
            errors.append(err_msg)

        # -------------------------------------------------------------
        # 4. Валидация иерархии категорий (Hierarchy)
        # -------------------------------------------------------------
        hierarchy_report: dict[str, Any] = {
            "is_valid": True,
            "violations": [],
            "error": None,
        }

        hierarchy_violations: list[dict[str, Any]] = []

        # А. Проверка парных примыканий в каждом внутреннем узле-перекрестке
        for nid, node in self.nodes.items():
            incident = self.get_incident_edges(nid)
            if len(incident) >= 2:
                for i in range(len(incident)):
                    for j in range(i + 1, len(incident)):
                        ea = incident[i]
                        eb = incident[j]
                        cat_a = ea.category.lower()
                        cat_b = eb.category.lower()

                        allowed_a = ALLOWED_JUNCTIONS.get(cat_a, {"custom"})
                        allowed_b = ALLOWED_JUNCTIONS.get(cat_b, {"custom"})

                        if cat_b not in allowed_a or cat_a not in allowed_b:
                            hierarchy_violations.append({
                                "node_id": nid,
                                "edge_1": ea.id,
                                "edge_2": eb.id,
                                "category_1": cat_a,
                                "category_2": cat_b,
                                "message": (
                                    f"Недопустимое прямое примыкание категории '{cat_a}' (ребро {ea.id}) "
                                    f"к '{cat_b}' (ребро {eb.id}) в узле '{nid}' (СП 42.13330)."
                                ),
                            })

        # Б. Проверка соответствия первого внутреннего ребра внешнему въезду (entry)
        for nid, node in self.nodes.items():
            if node.kind == "entry" and node.entry_category:
                e_cat = node.entry_category.lower()
                allowed_first = ENTRY_ALLOWED_INTERNAL_EDGES.get(e_cat, {"custom"})
                for inc_edge in self.get_incident_edges(nid):
                    edge_cat = inc_edge.category.lower()
                    if edge_cat not in allowed_first:
                        hierarchy_violations.append({
                            "node_id": nid,
                            "entry_category": e_cat,
                            "edge_id": inc_edge.id,
                            "edge_category": edge_cat,
                            "message": (
                                f"Въезд категории '{e_cat}' в узле '{nid}' не допускает "
                                f"подключение ребра категории '{edge_cat}' (ребро {inc_edge.id})."
                            ),
                        })

        if hierarchy_violations:
            hierarchy_report["is_valid"] = False
            hierarchy_report["violations"] = hierarchy_violations
            err_msg = f"Выявлены нарушения иерархии категорий УДС ({len(hierarchy_violations)} нарушений)."
            hierarchy_report["error"] = err_msg
            errors.append(err_msg)

        is_valid = len(errors) == 0

        return {
            "is_valid": is_valid,
            "connectivity": connectivity_report,
            "planarity": planarity_report,
            "hierarchy": hierarchy_report,
            "errors": errors,
            "warnings": warnings_list,
        }

    def check_building_intersections(self, buildings: Sequence[Polygon]) -> list[dict[str, Any]]:
        """Проверить пересечения коридоров дорог (poly_cut) с контурами зданий.

        Гарантирует, что проектируемая УДС не «протыкает» контуры зданий.

        Args:
            buildings: Список полигонов зданий.

        Returns:
            Список словарей с выявленными коллизиями (ребро, индекс здания, площадь наложения).
        """
        conflicts: list[dict[str, Any]] = []
        if not buildings:
            return conflicts

        for eid, edge in self.edges.items():
            cut = edge.poly_cut()
            for b_idx, b_poly in enumerate(buildings):
                if not b_poly or b_poly.is_empty:
                    continue
                if cut.intersects(b_poly):
                    inter = cut.intersection(b_poly)
                    if inter.area > 1e-2:
                        conflicts.append({
                            "edge_id": eid,
                            "building_index": b_idx,
                            "overlap_area_sqm": round(float(inter.area), 2),
                            "message": (
                                f"Коридор дороги '{eid}' (отступ {edge.setback} м) "
                                f"пересекает контур здания #{b_idx} (площадь наложения {round(inter.area, 1)} м²)."
                            ),
                        })
        return conflicts

    def to_geojson(self) -> dict[str, Any]:
        """Преобразовать граф УДС в стандартный GeoJSON FeatureCollection."""
        features = []
        for node in self.nodes.values():
            features.append({
                "type": "Feature",
                "geometry": mapping(node.position),
                "properties": {
                    "element": "node",
                    "id": node.id,
                    "kind": node.kind,
                    "entry_category": node.entry_category,
                },
            })

        for edge in self.edges.values():
            features.append({
                "type": "Feature",
                "geometry": mapping(edge.line),
                "properties": {
                    "element": "edge",
                    "id": edge.id,
                    "category": edge.category,
                    "width": edge.width,
                    "setback": edge.setback,
                    "length_m": round(edge.length, 1),
                    "from_node": edge.from_node.id,
                    "to_node": edge.to_node.id,
                },
            })

        return {
            "type": "FeatureCollection",
            "features": features,
        }

    @classmethod
    def build_natural_network(
        cls,
        site_boundary: Polygon,
        buildable_area: Polygon | MultiPolygon | None = None,
        entry_points: Sequence[dict[str, Any] | Node] | None = None,
        hub_point: Point | tuple[float, float] | None = None,
        default_category: str = "district",
        default_width: float = 14.0,
        default_setback: float = 3.0,
        stem_depth: float = 16.0,
        fillet_radius: float = 10.0,
    ) -> RoadGraph:
        """Построить градостроительно естественную УДС (Natural Urban Road Network).

        Обеспечивает реалистичную структуру мастер-плана:
        - Нормальные (перпендикулярные) створы въездов по нормалям к границе ЗУ;
        - Сквозные распределительные магистрали (Spine) вдоль естественной оси ЗУ;
        - Ортогональные Т-образные примыкания (T-Junctions) вместо 3-лучевых «звезд»;
        - Ортогональные перекрестки 2x2 для 4 въездов;
        - Чистую нарезку на прямоугольные урбан-блоки без острых нежизнеспособных клиньев.
        """
        from src.core.natural_road_network import NaturalRoadGenerator

        return NaturalRoadGenerator.build_network(
            site_boundary=site_boundary,
            buildable_area=buildable_area,
            entry_points=entry_points,
            hub_point=hub_point,
            default_category=default_category,
            default_width=default_width,
            default_setback=default_setback,
            stem_depth=stem_depth,
            fillet_radius=fillet_radius,
        )

    @classmethod
    def build_contour_network(
        cls,
        site_boundary: Polygon,
        buildable_area: Polygon | MultiPolygon,
        entry_points: Sequence[dict[str, Any] | Node],
        connect_perimeter: bool = True,
        default_category: str = "district",
        default_width: float = 14.0,
        default_setback: float = 3.0,
    ) -> RoadGraph:
        """Построить контурную УДС вокруг зоны застройки с подключением въездов (Вариант А).

        Гарантирует:
        - Точки на границе ЗУ служат порталами подключения (связями) к внешней среде;
        - Дороги огибают зону застройки по периметру, формируя фронты улиц и пожарный объезд;
        - Внутреннее пространство квартала, двор и контуры зданий не рассекаются насквозь.

        Args:
            site_boundary: Полигон земельного участка.
            buildable_area: Полигон или MultiPolygon зоны допустимой застройки.
            entry_points: Список точек въезда (словари с координатами или объекты Node).
            connect_perimeter: Соединять ли въезды замкнутым кольцевым проездом по периметру.
            default_category: Категория дороги по умолчанию ('district', 'local', 'arterial').
            default_width: Ширина проезжей части по умолчанию.
            default_setback: Отступ дороги до линии застройки по умолчанию.

        Returns:
            Связный и планарный объект RoadGraph.
        """
        if not entry_points:
            return cls()

        nodes: list[Node] = []
        edges: list[Edge] = []

        if isinstance(buildable_area, MultiPolygon):
            main_poly = max(buildable_area.geoms, key=lambda p: p.area)
        elif isinstance(buildable_area, Polygon) and not buildable_area.is_empty:
            main_poly = buildable_area
        elif site_boundary and not site_boundary.is_empty:
            main_poly = site_boundary
        else:
            return cls()

        ext = main_poly.exterior
        gate_items: list[tuple[float, str, Node]] = []

        for i, ep_item in enumerate(entry_points):
            if isinstance(ep_item, Node):
                ep_id = ep_item.id
                pos = ep_item.position
                cat = ep_item.entry_category or default_category
                w = ep_item.width if hasattr(ep_item, "width") else default_width
                s = ep_item.setback if hasattr(ep_item, "setback") else default_setback
                n_ep = ep_item
            elif isinstance(ep_item, dict):
                ep_id = ep_item.get("id") or f"entry_{i+1}"
                pos = Point(float(ep_item.get("x", 0.0)), float(ep_item.get("y", 0.0)))
                cat = ep_item.get("category") or default_category
                w = float(ep_item.get("width") or default_width)
                s = float(ep_item.get("setback") if ep_item.get("setback") is not None else default_setback)
                n_ep = Node(id=ep_id, position=pos, kind="entry", entry_category=cat)
            else:
                continue

            nodes.append(n_ep)

            # Проекция въезда на внешнюю границу зоны допустимой застройки
            pt_conn = nearest_points(ext, pos)[0]
            gate_id = f"gate_{ep_id}"
            n_gate = Node(id=gate_id, position=pt_conn, kind="intersection" if connect_perimeter else "endpoint")
            nodes.append(n_gate)

            # Ребро створа въезда (от границы ЗУ до фронта застройки)
            edges.append(
                Edge(
                    id=f"spur_{ep_id}",
                    from_node=n_ep,
                    to_node=n_gate,
                    category=cat,
                    width=w,
                    setback=s,
                )
            )

            proj_dist = ext.project(pt_conn)
            gate_items.append((proj_dist, gate_id, n_gate))

        # Если включено контурное кольцо вокруг застройки
        if connect_perimeter and gate_items:
            # Собираем вершины полигона и точки подключения въездов
            perimeter_items: list[tuple[float, str, Node]] = [
                (ext.project(Point(coord)), f"v_corner_{k}", Node(f"v_corner_{k}", Point(coord), kind="intersection"))
                for k, coord in enumerate(list(ext.coords)[:-1])
            ]
            perimeter_items.extend(gate_items)
            perimeter_items.sort(key=lambda x: x[0])

            # Дедупликация точек ближе 0.5 м с приоритетом узлов въездов
            dedup: list[tuple[float, str, Node]] = []
            for item in perimeter_items:
                if not dedup or abs(item[0] - dedup[-1][0]) > 0.5:
                    dedup.append(item)
                else:
                    if "gate" in item[1] and "gate" not in dedup[-1][1]:
                        dedup[-1] = item

            for it in dedup:
                if it[2] not in nodes:
                    nodes.append(it[2])

            # Замыкаем кольцевой проезд по контуру застройки
            for k in range(len(dedup)):
                na = dedup[k][2]
                nb = dedup[(k + 1) % len(dedup)][2]
                edges.append(
                    Edge(
                        id=f"ring_{k+1}",
                        from_node=na,
                        to_node=nb,
                        category="district",
                        width=default_width,
                        setback=default_setback,
                    )
                )

        return cls(nodes=nodes, edges=edges)

    @classmethod
    def build_skeleton_network(
        cls,
        site_boundary: Polygon,
        buildable_area: Polygon | MultiPolygon,
        entry_points: Sequence[dict[str, Any] | Node],
        hub_point: Point | tuple[float, float] | None = None,
        default_category: str = "local",
        default_width: float = 8.0,
        default_setback: float = 3.0,
    ) -> RoadGraph:
        """Построить скелетную УДС, нарезающую участок на кварталы.

        - 2 точки въезда: сквозная улица между ними (или внутренний проезд через центр), рассекающая участок на кварталы;
        - 3 точки въезда: Т/Y-образный перекресток в центре, делящий участок на 3 квартала;
        - 4 точки въезда: крестообразный перекресток, делящий участок на 4 квартала ($2 \times 2$);
        - >4 точек въезда: радиально-узловая схема деления участка.

        Args:
            site_boundary: Полигон земельного участка.
            buildable_area: Полигон или MultiPolygon зоны допустимой застройки.
            entry_points: Список точек въезда (словари с координатами или объекты Node).
            hub_point: Опциональные координаты центрального узла-перекрестка.
            default_category: Категория дороги по умолчанию ('district', 'local', 'arterial').
            default_width: Ширина проезжей части по умолчанию.
            default_setback: Отступ дороги до линии застройки по умолчанию.

        Returns:
            Связный и планарный объект RoadGraph.
        """
        if not entry_points:
            return cls()

        entries: list[Node] = []
        for i, ep_item in enumerate(entry_points):
            if isinstance(ep_item, Node):
                entries.append(ep_item)
            elif isinstance(ep_item, dict):
                ep_id = ep_item.get("id") or f"ep_{i+1}"
                pos = Point(float(ep_item.get("x", 0.0)), float(ep_item.get("y", 0.0)))
                # Привязываем точку въезда строго к меже участка при небольших отклонениях мыши
                if site_boundary and not site_boundary.is_empty and hasattr(site_boundary, "exterior"):
                    snapped = nearest_points(site_boundary.exterior, pos)[0]
                    if pos.distance(snapped) <= 35.0:
                        pos = snapped
                cat = ep_item.get("category") or default_category
                n_ep = Node(id=ep_id, position=pos, kind="entry", entry_category=cat)
                if "width" in ep_item and ep_item["width"] is not None:
                    n_ep.width = float(ep_item["width"])
                if "setback" in ep_item and ep_item["setback"] is not None:
                    n_ep.setback = float(ep_item["setback"])
                entries.append(n_ep)

        if len(entries) == 1:
            center = buildable_area.centroid if buildable_area and not buildable_area.is_empty else site_boundary.centroid
            n_end = Node(id="hub_end", position=center, kind="endpoint")
            w = float(getattr(entries[0], "width", default_width))
            s = float(getattr(entries[0], "setback", default_setback))
            e = Edge(
                id="street_1",
                from_node=entries[0],
                to_node=n_end,
                category=entries[0].entry_category or default_category,
                width=w,
                setback=s,
            )
            return cls(nodes=[entries[0], n_end], edges=[e])

        if len(entries) == 2:
            ep1, ep2 = entries[0], entries[1]
            cat = ep1.entry_category or ep2.entry_category or default_category
            w = float(getattr(ep1, "width", default_width))
            s = float(getattr(ep1, "setback", default_setback))

            # Если явно передан промежуточный узел (hub_point) для Г-образной / ломаной / угловой трассировки:
            has_explicit_hub = (hub_point is not None and not isinstance(hub_point, bool))
            if has_explicit_hub:
                if isinstance(hub_point, Point):
                    hub_pos = hub_point
                elif isinstance(hub_point, (tuple, list)) and len(hub_point) >= 2:
                    hub_pos = Point(float(hub_point[0]), float(hub_point[1]))
                else:
                    hub_pos = buildable_area.centroid if buildable_area and not buildable_area.is_empty else site_boundary.centroid

                hub_node = Node(id="hub_junction", position=hub_pos, kind="intersection")
                e1 = Edge(id="street_1", from_node=ep1, to_node=hub_node, category=cat, width=w, setback=s)
                e2 = Edge(id="street_2", from_node=ep2, to_node=hub_node, category=cat, width=w, setback=s)
                return cls(nodes=[ep1, ep2, hub_node], edges=[e1, e2])

            # Если hub_point не задан (None) или False:
            # Проверяем, делит ли прямая ep1-ep2 зону застройки на 2 жизнеспособных квартала
            is_bisecting = False
            if buildable_area and not buildable_area.is_empty:
                line_dir = LineString([ep1.position, ep2.position])
                cut_w = max(1.5, w / 2.0) + max(0.0, s)
                poly_cut = line_dir.buffer(cut_w, cap_style="flat", join_style="mitre")
                diff = buildable_area.difference(poly_cut)
                min_area = min(100.0, buildable_area.area * 0.05)
                if isinstance(diff, MultiPolygon):
                    valid_parts = [p for p in diff.geoms if p.area >= min_area]
                    if len(valid_parts) >= 2:
                        is_bisecting = True

            # Прямая сквозная улица, если точки на противоположных сторонах и нет требования излома
            if is_bisecting or hub_point is False:
                e = Edge(id="street_1", from_node=ep1, to_node=ep2, category=cat, width=w, setback=s)
                return cls(nodes=[ep1, ep2], edges=[e])

            # Если точки на одной стороне границы или угол (прямая не делит участок):
            # трассируем проезд внутрь участка через центроид (hub)
            hub_pos = buildable_area.centroid if buildable_area and not buildable_area.is_empty else site_boundary.centroid
            hub_node = Node(id="hub_junction", position=hub_pos, kind="intersection")
            e1 = Edge(id="street_1", from_node=ep1, to_node=hub_node, category=cat, width=w, setback=s)
            e2 = Edge(id="street_2", from_node=ep2, to_node=hub_node, category=cat, width=w, setback=s)
            return cls(nodes=[ep1, ep2, hub_node], edges=[e1, e2])

        # 3 или более въездов: соединение через центральный узел-перекресток (hub)
        if hub_point is not None:
            if isinstance(hub_point, Point):
                hub_pos = hub_point
            elif isinstance(hub_point, (tuple, list)) and len(hub_point) >= 2:
                hub_pos = Point(float(hub_point[0]), float(hub_point[1]))
            else:
                hub_pos = buildable_area.centroid if buildable_area and not buildable_area.is_empty else site_boundary.centroid
        else:
            if len(entries) == 4:
                p = [e.position for e in entries]
                l1 = LineString([p[0], p[1]])
                l2 = LineString([p[2], p[3]])
                l3 = LineString([p[0], p[2]])
                l4 = LineString([p[1], p[3]])
                l5 = LineString([p[0], p[3]])
                l6 = LineString([p[1], p[2]])

                inter = None
                for la, lb in [(l1, l2), (l3, l4), (l5, l6)]:
                    if la.intersects(lb):
                        pt = la.intersection(lb)
                        if isinstance(pt, Point):
                            inter = pt
                            break
                if inter:
                    hub_pos = inter
                else:
                    sum_x = sum(e.position.x for e in entries) / len(entries)
                    sum_y = sum(e.position.y for e in entries) / len(entries)
                    hub_pos = Point(sum_x, sum_y)
            else:
                sum_x = sum(e.position.x for e in entries) / len(entries)
                sum_y = sum(e.position.y for e in entries) / len(entries)
                hub_pos = Point(sum_x, sum_y)

        # Гарантируем, что центральный перекресток (hub) лежит строго внутри участка застройки
        if site_boundary and not site_boundary.is_empty:
            if not site_boundary.buffer(-1.0).contains(hub_pos):
                if buildable_area and not buildable_area.is_empty:
                    hub_pos = buildable_area.representative_point()
                else:
                    hub_pos = site_boundary.representative_point()

        hub_node = Node(id="hub_junction", position=hub_pos, kind="intersection")
        nodes = list(entries) + [hub_node]
        edges = []

        for i, ep in enumerate(entries):
            cat = ep.entry_category or default_category
            w = float(getattr(ep, "width", default_width))
            s = float(getattr(ep, "setback", default_setback))
            edges.append(
                Edge(
                    id=f"street_{i+1}",
                    from_node=ep,
                    to_node=hub_node,
                    category=cat,
                    width=w,
                    setback=s,
                )
            )

        return cls(nodes=nodes, edges=edges)
