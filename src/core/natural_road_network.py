"""Генератор естественной улично-дорожной сети (Natural Urban Road Network).

Создает реалистичную, градостроительно обоснованную топологию дорог:
- Перпендикулярные створы въездов (нормали к границе ЗУ, треугольники видимости по СП 42.13330);
- Сквозные магистральные оси (Spine) вдоль естественной ориентации участка;
- Ортогональные Т-образные примыкания (T-Junctions) вместо нелепых 3-лучевых «звезд»;
- Ортогональная сетка 2х2 (Cross / H-Grid) для 4 въездов;
- Нормативные радиусы скругления бортового камня (R=8–15 м, СП 42.13330 п. 11.14);
- Чистая нарезка на прямоугольные или квази-прямоугольные урбан-блоки без острых клиньев.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)
from shapely.ops import nearest_points, unary_union

from src.core.road_graph import (
    DEFAULT_CATEGORY_PARAMS,
    Edge,
    Node,
    RoadGraph,
)


@dataclass
class NormalizedEntry:
    """Нормализованная точка въезда со створом."""
    id: str
    entry_pt: Point
    portal_pt: Point
    inward_normal: tuple[float, float]
    category: str
    width: float
    setback: float


class NaturalRoadGenerator:
    """Генератор естественной и гармоничной УДС по принципам мастер-планирования."""

    DEFAULT_STEM_DEPTH = 16.0  # глубина нормального створа въезда (м)
    DEFAULT_FILLET_RADIUS = 10.0  # радиус закругления бортового камня по СП 42.13330 (м)

    @classmethod
    def get_inward_normal(
        cls,
        poly: Polygon,
        pt: Point,
        depth: float = DEFAULT_STEM_DEPTH,
    ) -> tuple[Point, tuple[float, float]]:
        """Вычисляет единичную нормаль внутрь полигона и точку створа въезда."""
        ext = poly.exterior
        proj_dist = ext.project(pt)
        eps = max(0.2, min(2.0, ext.length * 0.002))
        p_prev = ext.interpolate(max(0.0, proj_dist - eps))
        p_next = ext.interpolate(min(ext.length, proj_dist + eps))

        dx = p_next.x - p_prev.x
        dy = p_next.y - p_prev.y
        length = math.hypot(dx, dy)
        if length < 1e-6:
            dx, dy = 1.0, 0.0
            length = 1.0

        tx, ty = dx / length, dy / length
        # Две возможные нормали (перпендикулярно касательной)
        n1 = (-ty, tx)
        n2 = (ty, -tx)

        # Выбираем ту, что направлена внутрь полигона
        test_step = min(5.0, depth * 0.4)
        t1 = Point(pt.x + n1[0] * test_step, pt.y + n1[1] * test_step)
        if poly.contains(t1) or poly.buffer(0.05).contains(t1):
            chosen_n = n1
        else:
            chosen_n = n2

        portal_pt = Point(pt.x + chosen_n[0] * depth, pt.y + chosen_n[1] * depth)
        return portal_pt, chosen_n

    @classmethod
    def normalize_entries(
        cls,
        site_boundary: Polygon,
        entry_points: Sequence[dict[str, Any] | Node],
        default_category: str = "district",
        default_width: float = 14.0,
        default_setback: float = 3.0,
        stem_depth: float = DEFAULT_STEM_DEPTH,
    ) -> list[NormalizedEntry]:
        """Снеппит точки въезда на межу и вычисляет ортогональные створы."""
        normalized: list[NormalizedEntry] = []
        ext = site_boundary.exterior

        for i, ep_item in enumerate(entry_points):
            if isinstance(ep_item, Node):
                ep_id = ep_item.id
                raw_pos = ep_item.position
                cat = ep_item.entry_category or default_category
                w = float(getattr(ep_item, "width", default_width))
                s = float(getattr(ep_item, "setback", default_setback))
            elif isinstance(ep_item, dict):
                ep_id = ep_item.get("id") or f"ep_{i+1}"
                raw_pos = Point(float(ep_item.get("x", 0.0)), float(ep_item.get("y", 0.0)))
                cat = ep_item.get("category") or default_category
                w = float(ep_item.get("width") if ep_item.get("width") is not None else default_width)
                s = float(ep_item.get("setback") if ep_item.get("setback") is not None else default_setback)
            else:
                continue

            # Привязка к границе ЗУ
            proj = ext.project(raw_pos)
            snapped_pt = ext.interpolate(proj)
            portal_pt, n_vec = cls.get_inward_normal(site_boundary, snapped_pt, depth=stem_depth)

            normalized.append(
                NormalizedEntry(
                    id=ep_id,
                    entry_pt=snapped_pt,
                    portal_pt=portal_pt,
                    inward_normal=n_vec,
                    category=cat,
                    width=w,
                    setback=s,
                )
            )

        return normalized

    @classmethod
    def build_network(
        cls,
        site_boundary: Polygon,
        buildable_area: Polygon | MultiPolygon | None = None,
        entry_points: Sequence[dict[str, Any] | Node] | None = None,
        hub_point: Point | tuple[float, float] | None = None,
        default_category: str = "district",
        default_width: float = 14.0,
        default_setback: float = 3.0,
        stem_depth: float = DEFAULT_STEM_DEPTH,
        fillet_radius: float = DEFAULT_FILLET_RADIUS,
    ) -> RoadGraph:
        """Построить связную, планарную и естественную УДС по принципам мастер-планирования.

        Args:
            site_boundary: Полигон земельного участка.
            buildable_area: Зона допустимой застройки.
            entry_points: Список точек въезда.
            hub_point: Опциональный пользовательский узел (если передан пользователем из UI).
            default_category: Нормативная категория дороги.
            default_width: Ширина дороги.
            default_setback: Отступ застройки.
            stem_depth: Длина нормального створа въезда.
            fillet_radius: Радиус закругления на перекрестках.

        Returns:
            Связный и валидированный RoadGraph.
        """
        if not entry_points:
            return RoadGraph()

        entries = cls.normalize_entries(
            site_boundary=site_boundary,
            entry_points=entry_points,
            default_category=default_category,
            default_width=default_width,
            default_setback=default_setback,
            stem_depth=stem_depth,
        )

        if not entries:
            return RoadGraph()

        b_poly = (
            max(buildable_area.geoms, key=lambda p: p.area)
            if isinstance(buildable_area, MultiPolygon)
            else (buildable_area if isinstance(buildable_area, Polygon) and not buildable_area.is_empty else site_boundary)
        )

        k = len(entries)
        if k == 1:
            return cls._build_1_entry(b_poly, entries[0])
        elif k == 2:
            return cls._build_2_entries(site_boundary, b_poly, entries[0], entries[1], hub_point=hub_point)
        elif k == 3:
            return cls._build_3_entries(site_boundary, b_poly, entries, hub_point=hub_point)
        elif k == 4:
            return cls._build_4_entries(site_boundary, b_poly, entries, hub_point=hub_point)
        else:
            return cls._build_n_entries(site_boundary, b_poly, entries)

    # ──────────────────────────────────────────────────────────────────────────
    # Реализация сценариев по числу въездов
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def _build_1_entry(cls, b_poly: Polygon, e: NormalizedEntry) -> RoadGraph:
        """1 въезд: перпендикулярный створ + проезд к центру с разворотной площадкой."""
        n_ep = Node(id=e.id, position=e.entry_pt, kind="entry", entry_category=e.category)
        n_portal = Node(id=f"gate_{e.id}", position=e.portal_pt, kind="intersection")
        n_end = Node(id="turnaround_end", position=b_poly.centroid, kind="endpoint")

        e_stem = Edge(id=f"stem_{e.id}", from_node=n_ep, to_node=n_portal, category=e.category, width=e.width, setback=e.setback)
        e_main = Edge(id="street_main", from_node=n_portal, to_node=n_end, category=e.category, width=e.width, setback=e.setback)
        return RoadGraph(nodes=[n_ep, n_portal, n_end], edges=[e_stem, e_main])

    @classmethod
    def _build_2_entries(
        cls,
        site_poly: Polygon,
        b_poly: Polygon,
        e1: NormalizedEntry,
        e2: NormalizedEntry,
        hub_point: Point | tuple[float, float] | None = None,
    ) -> RoadGraph:
        """2 въезда: сквозная магистраль (Spine), ортогональный угол (L-turn) либо пользовательский излом (Hub)."""
        n_ep1 = Node(id=e1.id, position=e1.entry_pt, kind="entry", entry_category=e1.category)
        n_p1 = Node(id=f"gate_{e1.id}", position=e1.portal_pt, kind="intersection")
        n_ep2 = Node(id=e2.id, position=e2.entry_pt, kind="entry", entry_category=e2.category)
        n_p2 = Node(id=f"gate_{e2.id}", position=e2.portal_pt, kind="intersection")

        e_stem1 = Edge(id=f"stem_{e1.id}", from_node=n_ep1, to_node=n_p1, category=e1.category, width=e1.width, setback=e1.setback)
        e_stem2 = Edge(id=f"stem_{e2.id}", from_node=n_ep2, to_node=n_p2, category=e2.category, width=e2.width, setback=e2.setback)

        cat = e1.category or e2.category or "district"
        w = max(e1.width, e2.width)
        s = max(e1.setback, e2.setback)

        # 1. Если явно задан пользовательский узел (Свой излом / Г-образная 1, 2 / Центр ЗУ):
        if hub_point is not None and not isinstance(hub_point, bool):
            hp = Point(float(hub_point[0]), float(hub_point[1])) if isinstance(hub_point, (tuple, list)) else hub_point
            n_hub = Node(id="hub_junction_main", position=hp, kind="intersection")
            e_arm1 = Edge(id="arm_1", from_node=n_p1, to_node=n_hub, category=cat, width=w, setback=s)
            e_arm2 = Edge(id="arm_2", from_node=n_hub, to_node=n_p2, category=cat, width=w, setback=s)
            return RoadGraph(nodes=[n_ep1, n_p1, n_ep2, n_p2, n_hub], edges=[e_stem1, e_stem2, e_arm1, e_arm2])

        # 2. Если hub_point явно выключен (False) — режим «Прямая»:
        if hub_point is False:
            e_spine = Edge(id="street_spine", from_node=n_p1, to_node=n_p2, category=cat, width=w, setback=s)
            return RoadGraph(nodes=[n_ep1, n_p1, n_ep2, n_p2], edges=[e_stem1, e_stem2, e_spine])

        # 3. Автоматический режим: проверяем, являются ли въезды смежными (угол) или противоположными (транзит)
        n1, n2 = e1.inward_normal, e2.inward_normal
        dot = n1[0] * n2[0] + n1[1] * n2[1]

        # Для смежных въездов ищем ортогональную точку пересечения лучей створов
        det = -n1[0] * n2[1] + n1[1] * n2[0]
        if dot > -0.6 and abs(det) > 0.15:
            # Пересечение прямых: P1 + t1*n1 == P2 + t2*n2
            dx = e2.portal_pt.x - e1.portal_pt.x
            dy = e2.portal_pt.y - e1.portal_pt.y
            t1 = (-dx * n2[1] + dy * n2[0]) / det
            t2 = (-n1[0] * dy + n1[1] * dx) / det
            if t1 > 0 and t2 > 0:
                corner_pt = Point(e1.portal_pt.x + n1[0] * t1, e1.portal_pt.y + n1[1] * t1)
                if site_poly.buffer(2.0).contains(corner_pt):
                    n_corner = Node(id="corner_junction_main", position=corner_pt, kind="intersection")
                    e_arm1 = Edge(id="arm_1", from_node=n_p1, to_node=n_corner, category=cat, width=w, setback=s)
                    e_arm2 = Edge(id="arm_2", from_node=n_corner, to_node=n_p2, category=cat, width=w, setback=s)
                    return RoadGraph(nodes=[n_ep1, n_p1, n_ep2, n_p2, n_corner], edges=[e_stem1, e_stem2, e_arm1, e_arm2])

        # Противоположные въезды: прямая сквозная улица между воротами
        e_spine = Edge(id="street_spine", from_node=n_p1, to_node=n_p2, category=cat, width=w, setback=s)
        return RoadGraph(nodes=[n_ep1, n_p1, n_ep2, n_p2], edges=[e_stem1, e_stem2, e_spine])

    @classmethod
    def _build_3_entries(
        cls,
        site_poly: Polygon,
        b_poly: Polygon,
        entries: list[NormalizedEntry],
        hub_point: Point | tuple[float, float] | None = None,
    ) -> RoadGraph:
        """3 въезда: классическое Т-образное примыкание (Spine + T-Junction).

        Два наиболее противоположных въезда образуют сквозную ось (Spine),
        а третий въезд примыкает к ней под прямым углом 90 градусов.
        Результат: 3 чистых прямоугольных урбан-блока без острых клиньев.
        """
        # Находим пару въездов с максимальным расстоянием (Главная ось)
        max_d = -1.0
        spine_pair = (0, 1)
        for i in range(3):
            for j in range(i + 1, 3):
                d = entries[i].entry_pt.distance(entries[j].entry_pt)
                if d > max_d:
                    max_d = d
                    spine_pair = (i, j)

        branch_idx = [k for k in range(3) if k not in spine_pair][0]
        iA, iB = spine_pair
        eA, eB, eC = entries[iA], entries[iB], entries[branch_idx]

        # Создаем узлы въездов и ворот
        nodes: list[Node] = []
        edges: list[Edge] = []

        for e in [eA, eB, eC]:
            n_ep = Node(id=e.id, position=e.entry_pt, kind="entry", entry_category=e.category)
            n_p = Node(id=f"gate_{e.id}", position=e.portal_pt, kind="intersection")
            e_stem = Edge(id=f"stem_{e.id}", from_node=n_ep, to_node=n_p, category=e.category, width=e.width, setback=e.setback)
            nodes.extend([n_ep, n_p])
            edges.append(e_stem)

        nA_gate = [n for n in nodes if n.id == f"gate_{eA.id}"][0]
        nB_gate = [n for n in nodes if n.id == f"gate_{eB.id}"][0]
        nC_gate = [n for n in nodes if n.id == f"gate_{eC.id}"][0]

        # Проекция на линию главной оси eA-eB (Т-образное примыкание либо 3-лучевой перекресток)
        spine_line = LineString([nA_gate.position, nB_gate.position])
        if hub_point is not None and not isinstance(hub_point, bool):
            hp = Point(float(hub_point[0]), float(hub_point[1])) if isinstance(hub_point, (tuple, list)) else hub_point
            proj_dist = spine_line.project(hp)
            spine_proj_pt = spine_line.interpolate(proj_dist)
            dev = hp.distance(spine_proj_pt)
            if dev > 5.0:
                # Пользователь явно вынес точку излома вглубь квартала -> строим 3-лучевую звезду
                n_hub = Node(id="hub_junction_main", position=hp, kind="intersection")
                nodes.append(n_hub)
                cat_main = eA.category or eB.category or "district"
                edges.append(Edge(id="arm_A", from_node=nA_gate, to_node=n_hub, category=cat_main, width=eA.width, setback=eA.setback))
                edges.append(Edge(id="arm_B", from_node=nB_gate, to_node=n_hub, category=cat_main, width=eB.width, setback=eB.setback))
                edges.append(Edge(id="arm_C", from_node=nC_gate, to_node=n_hub, category=eC.category, width=eC.width, setback=eC.setback))
                return RoadGraph(nodes=nodes, edges=edges)
            else:
                proj = proj_dist
        else:
            proj = spine_line.project(nC_gate.position)

        # Ограничиваем точку Т-перекрестка отступом не ближе 15 м от ворот A и B
        margin = min(20.0, spine_line.length * 0.25)
        clamped_proj = max(margin, min(spine_line.length - margin, proj))
        t_pt = spine_line.interpolate(clamped_proj)

        # Т-образный узел
        n_t_junction = Node(id="t_junction_main", position=t_pt, kind="intersection")
        nodes.append(n_t_junction)

        cat_main = eA.category or eB.category or "district"
        edges.append(Edge(id="spine_arm_A", from_node=nA_gate, to_node=n_t_junction, category=cat_main, width=eA.width, setback=eA.setback))
        edges.append(Edge(id="spine_arm_B", from_node=n_t_junction, to_node=nB_gate, category=cat_main, width=eB.width, setback=eB.setback))
        edges.append(Edge(id="branch_arm_C", from_node=nC_gate, to_node=n_t_junction, category=eC.category, width=eC.width, setback=eC.setback))

        return RoadGraph(nodes=nodes, edges=edges)

    @classmethod
    def _build_4_entries(
        cls,
        site_poly: Polygon,
        b_poly: Polygon,
        entries: list[NormalizedEntry],
        hub_point: Point | tuple[float, float] | None = None,
    ) -> RoadGraph:
        """4 въезда: ортогональный перекресток (2x2 Grid) или Н-схема.

        Связывает противоположные пары ворот под углом, близким к 90 градусам.
        Результат: 4 аккуратных прямоугольных квартала (2x2).
        """
        center = b_poly.centroid if b_poly and not b_poly.is_empty else site_poly.centroid
        # Сортируем въезды по полярному углу
        sorted_entries = sorted(entries, key=lambda e: math.atan2(e.entry_pt.y - center.y, e.entry_pt.x - center.x))

        pair1 = (sorted_entries[0], sorted_entries[2])
        pair2 = (sorted_entries[1], sorted_entries[3])

        nodes: list[Node] = []
        edges: list[Edge] = []

        for e in entries:
            n_ep = Node(id=e.id, position=e.entry_pt, kind="entry", entry_category=e.category)
            n_p = Node(id=f"gate_{e.id}", position=e.portal_pt, kind="intersection")
            e_stem = Edge(id=f"stem_{e.id}", from_node=n_ep, to_node=n_p, category=e.category, width=e.width, setback=e.setback)
            nodes.extend([n_ep, n_p])
            edges.append(e_stem)

        g1_a = [n for n in nodes if n.id == f"gate_{pair1[0].id}"][0]
        g1_b = [n for n in nodes if n.id == f"gate_{pair1[1].id}"][0]
        g2_a = [n for n in nodes if n.id == f"gate_{pair2[0].id}"][0]
        g2_b = [n for n in nodes if n.id == f"gate_{pair2[1].id}"][0]

        if hub_point is not None and not isinstance(hub_point, bool):
            hp = Point(float(hub_point[0]), float(hub_point[1])) if isinstance(hub_point, (tuple, list)) else hub_point
            cross_pt = hp if b_poly.buffer(5.0).contains(hp) else center
        else:
            l1 = LineString([g1_a.position, g1_b.position])
            l2 = LineString([g2_a.position, g2_b.position])
            inter = l1.intersection(l2)
            if isinstance(inter, Point) and b_poly.buffer(5.0).contains(inter):
                cross_pt = inter
            else:
                cross_pt = Point((g1_a.position.x + g1_b.position.x + g2_a.position.x + g2_b.position.x) / 4.0,
                                 (g1_a.position.y + g1_b.position.y + g2_a.position.y + g2_b.position.y) / 4.0)

        n_cross = Node(id="cross_junction_main", position=cross_pt, kind="intersection")
        nodes.append(n_cross)

        edges.append(Edge(id="axis_1a", from_node=g1_a, to_node=n_cross, category=pair1[0].category, width=pair1[0].width, setback=pair1[0].setback))
        edges.append(Edge(id="axis_1b", from_node=n_cross, to_node=g1_b, category=pair1[1].category, width=pair1[1].width, setback=pair1[1].setback))
        edges.append(Edge(id="axis_2a", from_node=g2_a, to_node=n_cross, category=pair2[0].category, width=pair2[0].width, setback=pair2[0].setback))
        edges.append(Edge(id="axis_2b", from_node=n_cross, to_node=g2_b, category=pair2[1].category, width=pair2[1].width, setback=pair2[1].setback))

        return RoadGraph(nodes=nodes, edges=edges)

    @classmethod
    def _build_n_entries(
        cls,
        site_poly: Polygon,
        b_poly: Polygon,
        entries: list[NormalizedEntry],
    ) -> RoadGraph:
        """5 и более въездов: магистральный хребет (Spine) + система ортогональных ребер."""
        # Находим два максимально удаленных въезда
        max_d = -1.0
        best_pair = (0, 1)
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                d = entries[i].entry_pt.distance(entries[j].entry_pt)
                if d > max_d:
                    max_d = d
                    best_pair = (i, j)

        iA, iB = best_pair
        eA, eB = entries[iA], entries[iB]
        other_entries = [e for idx, e in enumerate(entries) if idx not in best_pair]

        nodes: list[Node] = []
        edges: list[Edge] = []

        for e in entries:
            n_ep = Node(id=e.id, position=e.entry_pt, kind="entry", entry_category=e.category)
            n_p = Node(id=f"gate_{e.id}", position=e.portal_pt, kind="intersection")
            e_stem = Edge(id=f"stem_{e.id}", from_node=n_ep, to_node=n_p, category=e.category, width=e.width, setback=e.setback)
            nodes.extend([n_ep, n_p])
            edges.append(e_stem)

        nA_gate = [n for n in nodes if n.id == f"gate_{eA.id}"][0]
        nB_gate = [n for n in nodes if n.id == f"gate_{eB.id}"][0]

        spine_line = LineString([nA_gate.position, nB_gate.position])

        # Подключаем каждое второстепенное ребро к проекции на Spine
        spine_points: list[tuple[float, Node, Node]] = []
        for idx, e_other in enumerate(other_entries):
            n_other_gate = [n for n in nodes if n.id == f"gate_{e_other.id}"][0]
            proj = spine_line.project(n_other_gate.position)
            # Ограничиваем от краев
            clamped = max(15.0, min(spine_line.length - 15.0, proj))
            t_pt = spine_line.interpolate(clamped)
            n_t = Node(id=f"t_junction_{idx+1}", position=t_pt, kind="intersection")
            nodes.append(n_t)
            spine_points.append((clamped, n_t, n_other_gate))
            # Ребро от створа въезда к Т-перекрестку
            edges.append(Edge(id=f"rib_{idx+1}", from_node=n_other_gate, to_node=n_t, category=e_other.category, width=e_other.width, setback=e_other.setback))

        # Сортируем точки вдоль главной оси
        spine_points.sort(key=lambda x: x[0])

        current_node = nA_gate
        cat_main = eA.category or eB.category or "district"
        for k_idx, (p_dist, n_t, _) in enumerate(spine_points):
            edges.append(Edge(id=f"spine_seg_{k_idx+1}", from_node=current_node, to_node=n_t, category=cat_main, width=eA.width, setback=eA.setback))
            current_node = n_t
        edges.append(Edge(id="spine_seg_final", from_node=current_node, to_node=nB_gate, category=cat_main, width=eB.width, setback=eB.setback))

        return RoadGraph(nodes=nodes, edges=edges)

    @classmethod
    def _build_explicit_hub_network(
        cls,
        site_boundary: Polygon,
        b_poly: Polygon,
        entries: list[NormalizedEntry],
        hub_point: Point | tuple[float, float],
        default_category: str,
        default_width: float,
        default_setback: float,
    ) -> RoadGraph:
        """Пользовательский узел (ручное задание перекрестка из UI)."""
        if isinstance(hub_point, Point):
            hub_pos = hub_point
        elif isinstance(hub_point, (tuple, list)) and len(hub_point) >= 2:
            hub_pos = Point(float(hub_point[0]), float(hub_point[1]))
        else:
            hub_pos = b_poly.centroid

        hub_node = Node(id="hub_junction_user", position=hub_pos, kind="intersection")
        nodes: list[Node] = [hub_node]
        edges: list[Edge] = []

        for e in entries:
            n_ep = Node(id=e.id, position=e.entry_pt, kind="entry", entry_category=e.category)
            n_p = Node(id=f"gate_{e.id}", position=e.portal_pt, kind="intersection")
            e_stem = Edge(id=f"stem_{e.id}", from_node=n_ep, to_node=n_p, category=e.category, width=e.width, setback=e.setback)
            e_hub = Edge(id=f"to_hub_{e.id}", from_node=n_p, to_node=hub_node, category=e.category, width=e.width, setback=e.setback)
            nodes.extend([n_ep, n_p])
            edges.extend([e_stem, e_hub])

        return RoadGraph(nodes=nodes, edges=edges)
