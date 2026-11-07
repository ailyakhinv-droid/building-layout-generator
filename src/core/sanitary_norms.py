"""Модуль градостроительных санитарных норм и разрывов (СанПиН).

Реализует требования двух ключевых санитарных стандартов РФ:
1. СанПиН 2.2.1/2.1.1.1200-03 «Санитарно-защитные зоны и санитарная классификация предприятий,
   сооружений и иных объектов» (Таблица 7.1.1 «Расстояния от открытых автостоянок до жилых
   и общественных зданий, детских и спортивных площадок»):
   - До 10 машин: не менее 10 м до окон жилых домов, не менее 25 м до детских/спорт площадок;
   - 11-50 машин: не менее 15 м до окон жилых домов, не менее 25 м до площадок;
   - 51-100 машин: не менее 25 м до окон жилых домов, не менее 50 м до площадок;
   - 101-300 машин: не менее 35-50 м до окон жилых домов.
   - Принцип градостроительной компоновки: дробление открытых стоянок на придомовые карманы
     вместимостью до 10-25 м/м вдоль проездов с внешних сторон домов.

2. СанПиН 2.1.3684-21 «Санитарно-эпидемиологические требования к содержанию территорий
   городских и сельских поселений» (Раздел II, п. 4 - площадки накопления ТКО):
   - Расстояние от контейнерных площадок до многоквартирных жилых домов, детских игровых
     и спортивных площадок, зон отдыха: не менее 20 м;
   - Радиус пешеходной доступности от крайнего входа/подъезда жилого здания: не более 100 м;
   - Размеры типовой площадки на 3-5 евроконтейнеров (0.8-1.1 м³): 5.0 x 2.5 м или 6.0 x 3.0 м;
   - Наличие твердого водонепроницаемого покрытия с уклоном для выкатывания контейнеров
     и ограждения с трех сторон высотой не менее 1.0 м;
   - Транспортная доступность: примыкание к проезду для мусоровоза с радиусом поворота R >= 10 м.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)
from shapely.ops import unary_union

from src.models.building import Building
from src.models.site import Site


@dataclass
class SanitaryParkingNorms:
    """Санитарные разрывы от открытых автостоянок по СанПиН 2.2.1/2.1.1.1200-03 (Таблица 7.1.1)."""

    # Разрывы до жилых окон (м)
    SETBACK_WINDOWS_TIER_1: float = 10.0  # До 10 машиномест включительно
    SETBACK_WINDOWS_TIER_2: float = 15.0  # 11 - 50 машиномест
    SETBACK_WINDOWS_TIER_3: float = 25.0  # 51 - 100 машиномест
    SETBACK_WINDOWS_TIER_4: float = 35.0  # 101 - 300 машиномест

    # Разрывы до детских игровых и спортивных площадок (м)
    SETBACK_PLAYGROUNDS_SMALL: float = 25.0  # До 50 машиномест
    SETBACK_PLAYGROUNDS_LARGE: float = 50.0  # Свыше 50 машиномест

    # Максимальная рекомендуемая вместимость придомового кармана
    RECOMMENDED_CLUSTER_CAPACITY: int = 15   # 10-15 м/м для сохранения разрыва 10-15м


@dataclass
class WasteCollectionNorms:
    """Санитарные требования к площадкам сбора ТКО по СанПиН 2.1.3684-21 (п. 4)."""

    # Дистанции размещения
    MIN_DISTANCE_TO_WINDOWS_M: float = 20.0       # Не ближе 20 м от окон и детских площадок
    MAX_WALKING_RADIUS_M: float = 100.0           # Не дальше 100 м от крайнего входа/подъезда

    # Вместимость площадки
    CONTAINERS_PER_SITE_DEFAULT: int = 4          # 3-5 евроконтейнеров 1.1 м³
    PEOPLE_PER_CONTAINER: int = 150               # Норма накопления ~1 контейнер на 150 чел

    # Габариты типовой площадки ТКО (м)
    SITE_WIDTH_M: float = 5.0                     # Ширина (фронт)
    SITE_DEPTH_M: float = 2.5                     # Глубина
    ENCLOSURE_HEIGHT_M: float = 1.2               # Высота ограждения

    # Минимальный радиус разворота мусоровоза (м)
    MIN_TRUCK_TURNING_RADIUS_M: float = 10.0


@dataclass
class WasteSiteItem:
    """Отдельная запроектированная контейнерная площадка ТКО."""

    id: str
    polygon: Polygon
    centroid: Point
    containers_count: int = 4
    service_radius_m: float = 100.0
    covered_buildings_count: int = 0
    distance_to_nearest_window_m: float = 0.0
    is_compliant: bool = True
    note: str = ""


@dataclass
class SanitaryAnalysisResult:
    """Комплексный результат анализа и пространственной расстановки по СанПиН."""

    # 1. Площадки ТКО (СанПиН 2.1.3684-21)
    waste_sites: list[WasteSiteItem] = field(default_factory=list)
    waste_sites_union: Polygon | MultiPolygon | None = None
    waste_service_circles_union: Polygon | MultiPolygon | None = None
    waste_forbidden_zone: Polygon | MultiPolygon | None = None
    total_containers_count: int = 0
    waste_coverage_pct: float = 100.0
    waste_is_compliant: bool = True
    waste_issues: list[str] = field(default_factory=list)

    # 2. Санитарные разрывы открытых стоянок (СанПиН 2.2.1/2.1.1.1200-03)
    parking_forbidden_buffer_10m: Polygon | MultiPolygon | None = None
    parking_forbidden_buffer_15m: Polygon | MultiPolygon | None = None
    parking_forbidden_buffer_25m: Polygon | MultiPolygon | None = None
    parking_allowed_envelope_small: Polygon | MultiPolygon | None = None
    parking_is_compliant: bool = True
    parking_issues: list[str] = field(default_factory=list)
    recommended_pocket_size: int = 15

    # Сводные метрики
    summary_notes: list[str] = field(default_factory=list)


class SanitaryNormsEngine:
    """Движок проверки санитарных разрывов и генерации площадок ТКО по СанПиН."""

    def __init__(
        self,
        parking_norms: SanitaryParkingNorms | None = None,
        waste_norms: WasteCollectionNorms | None = None,
    ) -> None:
        self.p_norms = parking_norms or SanitaryParkingNorms()
        self.w_norms = waste_norms or WasteCollectionNorms()

    def get_building_union(self, buildings: Sequence[Building]) -> Polygon | MultiPolygon:
        """Объединенный контур пятен всех жилых корпусов."""
        polys = [b.footprint for b in buildings if getattr(b, "footprint", None) and not b.footprint.is_empty]
        if not polys:
            return Polygon()
        return unary_union(polys)

    def get_building_entrances_or_centroids(self, buildings: Sequence[Building]) -> list[Point]:
        """Получить точки подъездов или центроиды секций для расчета радиуса 100м."""
        points: list[Point] = []
        for b in buildings:
            if getattr(b, "sections", None):
                for s in b.sections:
                    fp = getattr(s, "footprint", None)
                    if fp and not fp.is_empty:
                        points.append(fp.centroid)
            elif getattr(b, "footprint", None) and not b.footprint.is_empty:
                points.append(b.footprint.centroid)
        return points

    def analyze_sanitary_parking(
        self,
        site: Site,
        buildings: Sequence[Building],
        playgrounds_polygon: Polygon | MultiPolygon | None = None,
    ) -> dict[str, Any]:
        """Расчет санитарных разрывов для автостоянок по СанПиН 2.2.1/2.1.1.1200-03 (Таблица 7.1.1).

        Формирует:
        - 10-метровый запретный буфер от фасадов (для стоянок до 10 машин);
        - 15-метровый запретный буфер от фасадов (для стоянок 11-50 машин);
        - 25-метровый запретный буфер от детских и спортивных площадок;
        - Допустимый конверт для размещения открытых стоянок.
        """
        b_union = self.get_building_union(buildings)
        site_poly = site.boundary

        buf_10m = b_union.buffer(self.p_norms.SETBACK_WINDOWS_TIER_1) if not b_union.is_empty else Polygon()
        buf_15m = b_union.buffer(self.p_norms.SETBACK_WINDOWS_TIER_2) if not b_union.is_empty else Polygon()

        # Буфер площадок благоустройства (детские, спорт)
        if playgrounds_polygon and not playgrounds_polygon.is_empty:
            buf_play_25m = playgrounds_polygon.buffer(self.p_norms.SETBACK_PLAYGROUNDS_SMALL)
        else:
            # Оценочно: если точный полигон площадок не передан, берем центроид двора
            if not b_union.is_empty:
                courtyard_pt = site_poly.centroid
                buf_play_25m = courtyard_pt.buffer(20.0)
            else:
                buf_play_25m = Polygon()

        # Запретная зона для карманов до 15-20 м/м: окна (15м) + детские площадки (25м)
        forbidden_zone_standard = unary_union([buf_15m, buf_play_25m])

        # Допустимый конверт внутри участка
        allowed_envelope = site_poly.difference(forbidden_zone_standard) if not site_poly.is_empty else Polygon()

        issues = []
        if allowed_envelope.is_empty or (allowed_envelope.area < 200.0):
            issues.append(
                "Стесненная территория: после вычета санитарных разрывов СанПиН (15м до окон, 25м до площадок) "
                "площадь для открытых стоянок ограничена. Требуется вынос стоянок на внешний периметр или в подземный паркинг."
            )

        return {
            "buf_10m": buf_10m,
            "buf_15m": buf_15m,
            "buf_play_25m": buf_play_25m,
            "forbidden_zone": forbidden_zone_standard,
            "allowed_envelope": allowed_envelope,
            "is_compliant": len(issues) == 0,
            "issues": issues,
        }

    def generate_waste_collection_sites(
        self,
        site: Site,
        buildings: Sequence[Building],
        population: int = 1000,
        fire_lanes: Polygon | MultiPolygon | None = None,
        playgrounds_polygon: Polygon | MultiPolygon | None = None,
    ) -> list[WasteSiteItem]:
        """Автоматическая расстановка контейнерных площадок ТКО по СанПиН 2.1.3684-21.

        Правила:
        1. Расстояние от жилых окон и площадок отдыха: >= 20.0 м (п. 4);
        2. Пешеходный радиус доступности от секций/подъездов: <= 100.0 м (п. 4);
        3. Примыкание к проезду или разворотной полосе для свободного подъезда мусоровоза;
        4. Вместимость: из расчета 1 евроконтейнер на ~150 жителей (3-5 контейнеров на площадку).
        """
        b_union = self.get_building_union(buildings)
        site_poly = site.boundary
        if site_poly.is_empty or b_union.is_empty:
            return []

        # 1. Запретная зона: 20м от окон зданий и 20м от площадок
        b_buf_20m = b_union.buffer(self.w_norms.MIN_DISTANCE_TO_WINDOWS_M)
        if playgrounds_polygon and not playgrounds_polygon.is_empty:
            play_buf_20m = playgrounds_polygon.buffer(self.w_norms.MIN_DISTANCE_TO_WINDOWS_M)
            forbidden_zone = unary_union([b_buf_20m, play_buf_20m])
        else:
            forbidden_zone = b_buf_20m

        # 2. Допустимая полоса на участке: ЗУ минус 20-метровый буфер
        allowable_land = site_poly.difference(forbidden_zone)
        if allowable_land.is_empty:
            # Если 20м буфер накрыл весь участок, сжимаем до 15м (допустимо в стесненных условиях по п. 4)
            b_buf_15m = b_union.buffer(15.0)
            allowable_land = site_poly.difference(b_buf_15m)

        # 3. Расчет требуемого числа контейнеров и площадок
        pop = max(100, population)
        total_containers = max(2, math.ceil(pop / self.w_norms.PEOPLE_PER_CONTAINER))
        # Оптимально 3-4 контейнера на площадку
        containers_per_site = min(5, max(3, self.w_norms.CONTAINERS_PER_SITE_DEFAULT))
        num_sites = max(1, math.ceil(total_containers / containers_per_site))

        # 4. Точки тяготения (секции / подъезды домов)
        entrance_points = self.get_building_entrances_or_centroids(buildings)
        if not entrance_points:
            entrance_points = [b_union.centroid]

        # 5. Линия транспортной доступности
        candidate_points: list[Point] = []

        # 5.1. Точки вдоль изолинии отступа 22 м от окон (гарантирует отступ >= 20м по СанПиН)
        iso_ring = b_union.buffer(22.0).boundary
        if iso_ring and not iso_ring.is_empty:
            cur_d = 5.0
            while cur_d < iso_ring.length:
                pt = iso_ring.interpolate(cur_d)
                if site_poly.contains(pt) and not forbidden_zone.contains(pt):
                    if site_poly.boundary.distance(pt) >= 1.5:
                        candidate_points.append(pt)
                cur_d += 25.0

        # 5.2. Точки вдоль пожарных проездов вне запретной зоны
        if fire_lanes and not fire_lanes.is_empty:
            fl_b = fire_lanes.boundary
            cur_f = 5.0
            while cur_f < fl_b.length:
                pt = fl_b.interpolate(cur_f)
                if site_poly.contains(pt) and not forbidden_zone.contains(pt):
                    candidate_points.append(pt)
                cur_f += 25.0

        # 5.3. Если кандидатов мало, сэмплируем границы допустимой зоны ЗУ
        if len(candidate_points) < num_sites:
            inner_allowable = allowable_land.buffer(-1.0)
            if not inner_allowable.is_empty:
                b_line = inner_allowable.boundary
                cur_b = 5.0
                while cur_b < b_line.length:
                    pt = b_line.interpolate(cur_b)
                    if not forbidden_zone.contains(pt) and site_poly.contains(pt):
                        candidate_points.append(pt)
                    cur_b += 20.0

        if not candidate_points:
            # Fallback: точка, гарантированно лежащая внутри допустимой зоны
            candidate_points.append(allowable_land.representative_point())

        # 6. Жадный выбор площадок для 100% покрытия подъездов радиусом 100 м
        uncovered_entrances = list(entrance_points)
        chosen_sites: list[WasteSiteItem] = []
        site_idx = 0
        remaining_containers = total_containers

        w_w = self.w_norms.SITE_WIDTH_M
        w_d = self.w_norms.SITE_DEPTH_M

        while candidate_points and (site_idx < num_sites or remaining_containers > 0):
            site_idx += 1
            # Выбираем кандидата, который покрывает максимум непокрытых подъездов в радиусе 100м
            best_cand = None
            best_covered: list[Point] = []
            best_score = -1e9

            for cand in candidate_points:
                cov = [ep for ep in uncovered_entrances if cand.distance(ep) <= self.w_norms.MAX_WALKING_RADIUS_M]
                dist_to_win = cand.distance(b_union)
                # Предпочтение точкам, покрывающим непокрытые входы и с отступом >= 20м
                score = len(cov) * 100.0 + min(50.0, dist_to_win)
                if score > best_score:
                    best_score = score
                    best_cand = cand
                    best_covered = cov

            if not best_cand:
                best_cand = candidate_points[0]

            # Создаем геометрию типовой площадки ТКО (прямоугольник w_w x w_d)
            site_box = box(
                best_cand.x - w_w / 2.0,
                best_cand.y - w_d / 2.0,
                best_cand.x + w_w / 2.0,
                best_cand.y + w_d / 2.0,
            )

            dist_win = round(best_cand.distance(b_union), 1)
            is_comp = dist_win >= (self.w_norms.MIN_DISTANCE_TO_WINDOWS_M - 0.5)

            containers_assigned = min(remaining_containers, containers_per_site)
            remaining_containers = max(0, remaining_containers - containers_assigned)

            w_item = WasteSiteItem(
                id=f"tko_{site_idx}",
                polygon=site_box,
                centroid=best_cand,
                containers_count=max(2, containers_assigned),
                service_radius_m=self.w_norms.MAX_WALKING_RADIUS_M,
                covered_buildings_count=len(best_covered),
                distance_to_nearest_window_m=dist_win,
                is_compliant=is_comp,
                note=f"Площадка ТКО №{site_idx}: {containers_assigned} евром/к, отступ до жилья {dist_win}м (норма >=20м)",
            )
            chosen_sites.append(w_item)

            # Обновляем список непокрытых входов
            uncovered_entrances = [ep for ep in uncovered_entrances if ep not in best_covered]
            # Убираем использованного кандидата и близких соседей (<25м)
            candidate_points = [cp for cp in candidate_points if cp.distance(best_cand) > 25.0]

            if not uncovered_entrances and remaining_containers <= 0:
                break

        return chosen_sites

    def analyze_site(
        self,
        site: Site,
        buildings: Sequence[Building],
        population: int = 1000,
        fire_lanes: Polygon | MultiPolygon | None = None,
        playgrounds_polygon: Polygon | MultiPolygon | None = None,
    ) -> SanitaryAnalysisResult:
        """Выполнить полный санитарный анализ ЗУ: парковки + ТКО."""
        # 1. Анализ парковок
        p_res = self.analyze_sanitary_parking(site, buildings, playgrounds_polygon)

        # 2. Площадки ТКО
        waste_sites = self.generate_waste_collection_sites(
            site=site,
            buildings=buildings,
            population=population,
            fire_lanes=fire_lanes,
            playgrounds_polygon=playgrounds_polygon,
        )

        # Полигон площадок
        w_polys = [ws.polygon for ws in waste_sites]
        w_union = unary_union(w_polys) if w_polys else None

        # Окружности радиуса 100м
        circles = [ws.centroid.buffer(ws.service_radius_m) for ws in waste_sites]
        circles_union = unary_union(circles) if circles else None

        # Проверка покрытия подъездов радиусом 100м
        entrances = self.get_building_entrances_or_centroids(buildings)
        covered_count = 0
        if circles_union and not circles_union.is_empty:
            for ep in entrances:
                if circles_union.contains(ep) or circles_union.distance(ep) < 0.5:
                    covered_count += 1
        total_entrances = max(1, len(entrances))
        coverage_pct = round((covered_count / total_entrances) * 100.0, 1)

        waste_issues: list[str] = []
        if coverage_pct < 99.0:
            waste_issues.append(
                f"Радиус доступности ТКО (100м): покрыто {coverage_pct}% жилых подъездов. "
                f"Рекомендуется добавить площадку ТКО в неохваченном секторе."
            )

        for ws in waste_sites:
            if not ws.is_compliant:
                waste_issues.append(
                    f"{ws.note}: нарушение СанПиН 2.1.3684-21 (отступ менее 20м до окон жилого дома)."
                )

        total_cnt = sum(ws.containers_count for ws in waste_sites)

        summary_notes = []
        if len(waste_sites) > 0 and coverage_pct >= 99.0 and all(ws.is_compliant for ws in waste_sites):
            summary_notes.append(
                f"✓ СанПиН 2.1.3684-21 (ТКО) соблюден: {len(waste_sites)} площадки ({total_cnt} евроконтейнеров), "
                f"100% жилья в радиусе <=100м, отступ от окон >=20м."
            )
        if p_res["is_compliant"]:
            summary_notes.append(
                f"✓ СанПиН 2.2.1/2.1.1.1200-03 (Автостоянки): разрывы 10-15м от окон и 25м от площадок соблюдены."
            )

        return SanitaryAnalysisResult(
            waste_sites=waste_sites,
            waste_sites_union=w_union,
            waste_service_circles_union=circles_union,
            waste_forbidden_zone=p_res["forbidden_zone"],
            total_containers_count=total_cnt,
            waste_coverage_pct=coverage_pct,
            waste_is_compliant=len(waste_issues) == 0,
            waste_issues=waste_issues,
            parking_forbidden_buffer_10m=p_res["buf_10m"],
            parking_forbidden_buffer_15m=p_res["buf_15m"],
            parking_forbidden_buffer_25m=p_res["buf_play_25m"],
            parking_allowed_envelope_small=p_res["allowed_envelope"],
            parking_is_compliant=p_res["is_compliant"],
            parking_issues=p_res["issues"],
            summary_notes=summary_notes,
        )
