"""Модуль генерации и визуализации парковочных пространств (СП 113.13330.2016, СанПиН 2.2.1/2.1.1.1200-03).

Поддерживает:
1. Концепцию «Двор без машин» (размещение стоянок исключительно по внешнему периметру застройки);
2. Стандартное размещение (с допущением стоянок во внутреннем дворе);
3. Моделирование индивидуальных машиномест габаритом 2.5 x 5.0 (5.3) м;
4. Формирование GeoJSON для 2D-карты и 3D-визуализации.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from shapely.geometry import MultiPolygon, Point, Polygon, box, mapping
from shapely.ops import unary_union
from shapely.validation import make_valid

from src.models.building import Building
from src.models.site import Site


@dataclass
class ParkingSlot:
    """Индивидуальное машиноместо."""
    polygon: Polygon
    width_m: float = 2.5
    depth_m: float = 5.0
    is_courtyard: bool = False


@dataclass
class ParkingLayoutResult:
    """Результат расчета и трассировки парковочных мест."""
    slots: list[ParkingSlot] = field(default_factory=list)
    bays_polygon: Polygon | MultiPolygon | None = None
    slots_count: int = 0
    total_area_sqm: float = 0.0
    car_free_courtyard: bool = True
    allow_parking_in_zouit: bool = False
    courtyard_slots_count: int = 0
    perimeter_slots_count: int = 0
    zouit_slots_count: int = 0
    geojson: dict[str, Any] = field(default_factory=dict)


def generate_parking_layout(
    site: Site,
    buildings: Sequence[Building],
    target_spaces: int,
    car_free_courtyard: bool = True,
    fire_lanes_poly: Polygon | MultiPolygon | None = None,
    forbidden_zone: Polygon | MultiPolygon | None = None,
    allow_parking_in_zouit: bool = False,
    roads_poly: Polygon | MultiPolygon | None = None,
    road_centerlines: Sequence[LineString] | None = None,
    roads_buffer: Polygon | MultiPolygon | None = None,
) -> ParkingLayoutResult:
    """Сгенерировать реалистичные парковочные карманы и машиноместа на участке.

    Args:
        site: Земельный участок.
        buildings: Размещенные жилые здания.
        target_spaces: Требуемое число наземных машиномест.
        car_free_courtyard: Включена ли концепция «Двор без машин».
        fire_lanes_poly: Полигон пожарных проездов (для предотвращения блокировки).
        forbidden_zone: Запретная зона СанПиН (окна, детские площадки).
        allow_parking_in_zouit: Разрешено ли размещение парковок в охранных зонах (СЗЗ).
        roads_poly: Полигон проезжей части дорог (строго исключается из парковок).
        road_centerlines: Осевые линии дорог (для створов въездов и придорожных карманов).
        roads_buffer: Буферные зоны дорог / полосы отвода.

    Returns:
        ParkingLayoutResult с геометрией машиномест и статистикой.
    """
    if target_spaces <= 0 or not site.boundary or site.boundary.is_empty:
        return ParkingLayoutResult(
            car_free_courtyard=car_free_courtyard,
            allow_parking_in_zouit=allow_parking_in_zouit,
        )

    site_poly = site.boundary
    if not site_poly.is_valid:
        site_poly = make_valid(site_poly)

    # Авто-подтягивание дорожной сети из результатов нарезки, если не передано явно
    roads_res = getattr(site, "roads_result", None)
    if roads_res:
        if roads_poly is None:
            roads_poly = getattr(roads_res, "roads_polygon", None)
        if road_centerlines is None:
            road_centerlines = getattr(roads_res, "centerlines", None)
        if roads_buffer is None:
            roads_buffer = getattr(roads_res, "buffer_polygon", None)

    b_polys = [b.footprint for b in buildings if b.footprint and not b.footprint.is_empty]
    b_union = unary_union(b_polys) if b_polys else Polygon()
    if not b_union.is_empty and not b_union.is_valid:
        b_union = make_valid(b_union)

    # Определение дворовой зоны через выпуклую оболочку зданий
    courtyard_poly = b_union.convex_hull if (len(b_polys) >= 2 and not b_union.is_empty) else Polygon()

    # Зона, свободная от зданий: гарантированный санитарный разрыв 10.0 м от жилых стен (СанПиН 2.2.1/2.1.1.1200-03, табл. 7.1.1)
    walkway_setback = b_union.buffer(10.0) if not b_union.is_empty else Polygon()

    # Базовая зона размещения парковок: внутри участка с отступом 1.2 м от забора
    base_available = site_poly.buffer(-1.2).difference(walkway_setback)

    # ИСКЛЮЧЕНИЕ ДОРОГ: проезжая часть улиц и дорог строго исключается с запасом 1.0 м (бортовой камень)
    if roads_poly and not roads_poly.is_empty:
        base_available = base_available.difference(roads_poly.buffer(1.0))

    # ОСВОБОЖДЕНИЕ СТВОРОВ ВЪЕЗДОВ: где дороги пересекают внешнюю границу участка,
    # парковка категорически не должна перекрывать въездной портал
    if road_centerlines and site_poly.boundary and not site_poly.boundary.is_empty:
        boundary_line = site_poly.boundary
        for r_line in road_centerlines:
            try:
                gate_inter = r_line.intersection(boundary_line.buffer(1.2))
                if not gate_inter.is_empty:
                    # Освобождаем входной портал шириной 12–15 м
                    base_available = base_available.difference(gate_inter.buffer(11.0))
            except Exception:
                pass

    # При концепции «Двор без машин» полностью исключаем дворовую зону
    if car_free_courtyard and not courtyard_poly.is_empty:
        # Буфер двора с запасом 3.0 м внутрь
        courtyard_shield = courtyard_poly.buffer(3.0)
        base_available = base_available.difference(courtyard_shield)

    # Учитываем дополнительную запретную зону СанПиН (если передана)
    if forbidden_zone and not forbidden_zone.is_empty:
        filtered_zone = base_available.difference(forbidden_zone)
        if filtered_zone.area >= 100.0:
            base_available = filtered_zone

    # Предотвращаем прямое перекрытие пожарных проездов
    if fire_lanes_poly and not fire_lanes_poly.is_empty:
        # Парковка примыкает к проезду, но не блокирует его ось
        base_available = base_available.difference(fire_lanes_poly.buffer(-0.5))

    # Учет охранных зон (ЗОУИТ):
    # Строгая геометрия охранных зон (ЗОУИТ)
    zouit_polys = getattr(site, "zouit_polygons", []) or []
    valid_zouit = [zp for zp in zouit_polys if zp and not zp.is_empty and zp.is_valid]
    zouit_union_all = unary_union(valid_zouit) if valid_zouit else None

    if valid_zouit:
        if allow_parking_in_zouit:
            zouit_info = getattr(site, "zouit_info", []) or []
            strict_forbidden = []
            for idx, zp in enumerate(valid_zouit):
                info = zouit_info[idx] if idx < len(zouit_info) else {}
                text = f"{info.get('name', '')} {info.get('description', '')}".lower()
                is_danger = any(w in text for w in [
                    "лэп", "электропередач", "газопровод", "газ", "нефтепровод",
                    "теплосеть", "водопровод", "зсо", "источник водоснабжен", "канализац"
                ])
                if is_danger:
                    strict_forbidden.append(zp)
            if strict_forbidden:
                base_available = base_available.difference(unary_union(strict_forbidden).buffer(0.5))
        else:
            # Строгое исключение всех охранных зон по умолчанию
            base_available = base_available.difference(unary_union(valid_zouit).buffer(0.5))

    if base_available.is_empty or base_available.area < 25.0:
        return ParkingLayoutResult(
            car_free_courtyard=car_free_courtyard,
            allow_parking_in_zouit=allow_parking_in_zouit,
        )

    # Генерация машиномест 2.5 x 5.0 м вдоль внешнего периметра и проездов
    stall_w = 2.5  # ширина одного машиноместа
    stall_d = 5.0  # глубина машиноместа

    placed_slots: list[ParkingSlot] = []

    # 1. Трассировка вдоль сегментов внешней границы участка
    # Защита от узких клиньев/хвостов: для размещения машиноместа 5.0 м требуется проезд перед ним не менее 5.5 м (СП 113.13330 п. 5.1.5).
    # Поэтому в узких местах участка (< 12.0 м общей ширины) машиноместа не размещаются.
    coords = list(site_poly.exterior.coords)
    for i in range(len(coords) - 1):
        if len(placed_slots) >= target_spaces:
            break
        p1 = coords[i]
        p2 = coords[i + 1]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length < 8.0:
            continue

        tx, ty = dx / length, dy / length
        # Внутренняя нормаль
        nx, ny = -ty, tx
        mid_test = Point((p1[0] + p2[0]) / 2.0 + nx * 2.0, (p1[1] + p2[1]) / 2.0 + ny * 2.0)
        if not site_poly.contains(mid_test):
            nx, ny = ty, -tx

        # Отступ от угла 2.5 м
        start_offset = 2.5
        usable_len = length - 5.0
        if usable_len < stall_w:
            continue

        num_slots = int(usable_len // stall_w)
        for s_idx in range(num_slots):
            if len(placed_slots) >= target_spaces:
                break
            sx = p1[0] + tx * (start_offset + s_idx * stall_w) + nx * 1.5
            sy = p1[1] + ty * (start_offset + s_idx * stall_w) + ny * 1.5

            c1 = (sx, sy)
            c2 = (sx + tx * (stall_w - 0.1), sy + ty * (stall_w - 0.1))
            c3 = (c2[0] + nx * stall_d, c2[1] + ny * stall_d)
            c4 = (sx + nx * stall_d, sy + ny * stall_d)
            slot_poly = Polygon([c1, c2, c3, c4])

            # Нормативная полоса маневрирования перед машиноместом (СП 113.13330 п. 5.1.5: глубина 5.5 м)
            driveway_poly = Polygon([
                c4,
                c3,
                (c3[0] + nx * 5.5, c3[1] + ny * 5.5),
                (c4[0] + nx * 5.5, c4[1] + ny * 5.5),
            ])

            # Контроль проезда: полоса обязана целиком помещаться в границы участка
            if not site_poly.contains(driveway_poly.buffer(-0.1)):
                continue  # Узкий клин/хвост участка, маневр и выезд автомобиля невозможен

            # Запрет наложений на ЗОУИТ: ни машиноместо, ни проезд не могут пересекать охранную зону
            if zouit_union_all and not allow_parking_in_zouit:
                if slot_poly.intersects(zouit_union_all) or driveway_poly.intersects(zouit_union_all):
                    continue

            # Запрет наложения на дорогу и пожарный проезд
            if roads_poly and (slot_poly.intersects(roads_poly) or driveway_poly.intersects(roads_poly)):
                continue
            if fire_lanes_poly and (slot_poly.intersects(fire_lanes_poly) or driveway_poly.intersects(fire_lanes_poly)):
                continue

            if base_available.contains(slot_poly.buffer(-0.1)):
                placed_slots.append(
                    ParkingSlot(
                        polygon=slot_poly,
                        width_m=stall_w,
                        depth_m=stall_d,
                        is_courtyard=False,
                    )
                )

    # 2. Если мест вдоль забора не хватило, добавляем карманы вдоль внешних фасадов
    if len(placed_slots) < target_spaces and not b_union.is_empty:
        for b in buildings:
            if len(placed_slots) >= target_spaces:
                break
            fp = b.footprint
            if not fp or fp.is_empty:
                continue
            b_coords = list(fp.exterior.coords)
            for j in range(len(b_coords) - 1):
                if len(placed_slots) >= target_spaces:
                    break
                bp1 = b_coords[j]
                bp2 = b_coords[j + 1]
                bdx = bp2[0] - bp1[0]
                bdy = bp2[1] - bp1[1]
                blen = math.hypot(bdx, bdy)
                if blen < 12.0:
                    continue

                btx, bty = bdx / blen, bdy / blen
                bnx, bny = -bty, btx
                # Проверяем, что нормаль смотрит НАРУЖУ от здания
                out_test = Point((bp1[0] + bp2[0]) / 2.0 + bnx * 2.0, (bp1[1] + bp2[1]) / 2.0 + bny * 2.0)
                if fp.contains(out_test):
                    bnx, bny = bty, -btx

                # Если включен двор без машин, проверяем, что вектор наружу направлен от двора
                if car_free_courtyard and not courtyard_poly.is_empty:
                    if courtyard_poly.contains(out_test):
                        continue  # Фасад обращен во двор — парковку ставить запрещено

                # Отступ от фасада: минимум 10.5 м для строгого соблюдения СанПиН 2.2.1/2.1.1.1200-03 (разрыв >= 10 м)
                pocket_dist = 10.5
                num_slots = int((blen - 4.0) // stall_w)
                for s_idx in range(num_slots):
                    if len(placed_slots) >= target_spaces:
                        break
                    psx = bp1[0] + btx * (2.0 + s_idx * stall_w) + bnx * pocket_dist
                    psy = bp1[1] + bty * (2.0 + s_idx * stall_w) + bny * pocket_dist

                    pc1 = (psx, psy)
                    pc2 = (psx + btx * (stall_w - 0.1), psy + bty * (stall_w - 0.1))
                    pc3 = (pc2[0] + bnx * stall_d, pc2[1] + bny * stall_d)
                    pc4 = (psx + bnx * stall_d, psy + bny * stall_d)

                    pslot_poly = Polygon([pc1, pc2, pc3, pc4])
                    if base_available.contains(pslot_poly.buffer(-0.1)):
                        placed_slots.append(
                            ParkingSlot(
                                polygon=pslot_poly,
                                width_m=stall_w,
                                depth_m=stall_d,
                                is_courtyard=False,
                            )
                        )

    # 3. Придорожные парковочные карманы (Street Parking) вдоль внутренних улиц
    if len(placed_slots) < target_spaces and road_centerlines:
        for r_line in road_centerlines:
            if len(placed_slots) >= target_spaces:
                break
            r_coords = list(r_line.coords)
            for k in range(len(r_coords) - 1):
                if len(placed_slots) >= target_spaces:
                    break
                rp1 = r_coords[k]
                rp2 = r_coords[k + 1]
                rdx = rp2[0] - rp1[0]
                rdy = rp2[1] - rp1[1]
                rlen = math.hypot(rdx, rdy)
                if rlen < 12.0:
                    continue
                rtx, rty = rdx / rlen, rdy / rlen
                rnx, rny = -rty, rtx

                for side in (-1.0, 1.0):
                    snx = rnx * side
                    sny = rny * side
                    # Отступ от оси улицы: полуширина проезжей части (~7.5-8.0м) + 1.2м до кармана
                    dist_from_axis = 8.5
                    num_road_slots = int((rlen - 8.0) // stall_w)
                    for s_idx in range(num_road_slots):
                        if len(placed_slots) >= target_spaces:
                            break
                        rsx = rp1[0] + rtx * (4.0 + s_idx * stall_w) + snx * dist_from_axis
                        rsy = rp1[1] + rty * (4.0 + s_idx * stall_w) + sny * dist_from_axis

                        rc1 = (rsx, rsy)
                        rc2 = (rsx + rtx * (stall_w - 0.1), rsy + rty * (stall_w - 0.1))
                        rc3 = (rc2[0] + snx * stall_d, rc2[1] + sny * stall_d)
                        rc4 = (rsx + snx * stall_d, rsy + sny * stall_d)

                        rslot = Polygon([rc1, rc2, rc3, rc4])
                        # Строгая проверка: карман должен полностью находиться внутри разрешенной зоны
                        # (вне проезжей части дороги и вне санитарных разрывов окон)
                        if base_available.contains(rslot.buffer(-0.05)):
                            # И не пересекать уже размещенные машиноместа
                            if not any(rslot.intersects(p.polygon) for p in placed_slots[-30:]):
                                placed_slots.append(
                                    ParkingSlot(
                                        polygon=rslot,
                                        width_m=stall_w,
                                        depth_m=stall_d,
                                        is_courtyard=False,
                                    )
                                )

    # Объединенный полигон асфальтового покрытия стоянок
    bays_poly = unary_union([s.polygon.buffer(0.05) for s in placed_slots]) if placed_slots else None
    total_area = sum(s.polygon.area for s in placed_slots)

    # GeoJSON фичи для Leaflet и Three.js
    features = []
    for idx, slot in enumerate(placed_slots):
        features.append({
            "type": "Feature",
            "geometry": mapping(slot.polygon),
            "properties": {
                "layer": "PARKING_SLOTS",
                "id": idx + 1,
                "type": "ground_parking",
                "width_m": slot.width_m,
                "depth_m": slot.depth_m,
                "is_courtyard": slot.is_courtyard,
            },
        })

    if bays_poly is not None and not bays_poly.is_empty:
        features.append({
            "type": "Feature",
            "geometry": mapping(bays_poly),
            "properties": {
                "layer": "PARKING_BAYS",
                "area_sqm": round(total_area, 1),
                "slots_count": len(placed_slots),
                "car_free_courtyard": car_free_courtyard,
            },
        })

    # Проверка, сколько слотов оказалось в ЗОУИТ
    zouit_count = 0
    if valid_zouit:
        z_union = unary_union(valid_zouit)
        zouit_count = sum(1 for s in placed_slots if s.polygon.intersection(z_union).area > 0.1)

    return ParkingLayoutResult(
        slots=placed_slots,
        bays_polygon=bays_poly,
        slots_count=len(placed_slots),
        total_area_sqm=round(total_area, 1),
        car_free_courtyard=car_free_courtyard,
        allow_parking_in_zouit=allow_parking_in_zouit,
        courtyard_slots_count=sum(1 for s in placed_slots if s.is_courtyard),
        perimeter_slots_count=sum(1 for s in placed_slots if not s.is_courtyard),
        zouit_slots_count=zouit_count,
        geojson={
            "type": "FeatureCollection",
            "features": features,
        },
    )
