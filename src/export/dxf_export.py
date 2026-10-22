"""Экспорт плана застройки в формат DXF (AutoCAD, nanoCAD, ArchiCAD, Civil 3D).

Обеспечивает сквозную совместимость с CAD-программами:
- Восстановление оригинальных координат МСК (base_offset) из исходного чертежа;
- Разделение по специализированным слоям (граница, зона застройки, корпуса, секции, аннотации);
- Замкнутые 2D-полилинии (LWPOLYLINE) для точной штриховки и обмеров;
- Подписи этажности, номеров корпусов и площадей.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import ezdxf
from shapely.geometry import MultiPolygon, Polygon

from src.models.building import Building
from src.models.site import Site
from src.models.tep import TEP


def export_dxf(
    site: Site,
    buildings: list[Building],
    tep: TEP | None = None,
    filepath: str | Path = "output/plan.dxf",
    restore_cad_coords: bool = True,
) -> Path:
    """Экспортировать план застройки в файл AutoCAD DXF (R2010).

    Args:
        site: Земельный участок (содержит boundary, buildable_area, base_offset).
        buildings: Список размещенных зданий и секций.
        tep: Сводные ТЭП участка (опционально).
        filepath: Путь для сохранения .dxf файла.
        restore_cad_coords: Если True — прибавить site.base_offset для точной
                            посадки в исходную геодезическую СК (МСК).

    Returns:
        Объект Path сохраненного файла DXF.
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Смещение координат обратно в исходную МСК CAD-чертежа
    if restore_cad_coords and site.base_offset != (0.0, 0.0):
        ox, oy = site.base_offset
    else:
        ox, oy = 0.0, 0.0

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # ─── Настройка слоёв CAD ───────────────────────────────────────────────
    layers_config = [
        ("0_ГРАНИЦА_УЧАСТКА", 1),       # 1 = Red
        ("0_ЗОНА_ЗАСТРОЙКИ", 4),       # 4 = Cyan
        ("0_КРАСНЫЕ_ЛИНИИ", 1),        # 1 = Red
        ("АРХ_КОРПУСА", 3),            # 3 = Green
        ("АРХ_СЕКЦИИ", 7),             # 7 = White / Black
        ("АРХ_ПОДПИСИ", 2),            # 2 = Yellow
        ("АРХ_ЭКСПЛИКАЦИЯ", 8),        # 8 = Gray
    ]
    for layer_name, color in layers_config:
        if layer_name not in doc.layers:
            doc.layers.add(layer_name, color=color)

    # 1. Экспорт границы участка
    def _export_polygon(poly: Polygon, layer: str) -> None:
        if poly.is_empty:
            return
        pts = [(x + ox, y + oy) for x, y in poly.exterior.coords]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
        for interior in poly.interiors:
            pts_hole = [(x + ox, y + oy) for x, y in interior.coords]
            msp.add_lwpolyline(pts_hole, close=True, dxfattribs={"layer": layer})

    _export_polygon(site.boundary, "0_ГРАНИЦА_УЧАСТКА")

    # 2. Экспорт зоны допустимой застройки
    if site.buildable_area and not site.buildable_area.is_empty:
        if isinstance(site.buildable_area, MultiPolygon):
            for part in site.buildable_area.geoms:
                _export_polygon(part, "0_ЗОНА_ЗАСТРОЙКИ")
        else:
            _export_polygon(site.buildable_area, "0_ЗОНА_ЗАСТРОЙКИ")

    # 3. Экспорт красных линий
    for rl in site.red_lines:
        if not rl.is_empty and len(rl.coords) >= 2:
            rl_pts = [(x + ox, y + oy) for x, y in rl.coords]
            msp.add_lwpolyline(rl_pts, close=False, dxfattribs={"layer": "0_КРАСНЫЕ_ЛИНИИ"})

    # 4. Экспорт зданий и секций
    for i, building in enumerate(buildings):
        b_num = i + 1
        b_fp = building.footprint

        # Контур корпуса в сборе
        if isinstance(b_fp, MultiPolygon):
            for part in b_fp.geoms:
                _export_polygon(part, "АРХ_КОРПУСА")
        elif isinstance(b_fp, Polygon):
            _export_polygon(b_fp, "АРХ_КОРПУСА")

        # Отдельные секции внутри корпуса
        for j, sec in enumerate(building.sections):
            sec_fp = sec.footprint
            if isinstance(sec_fp, Polygon):
                _export_polygon(sec_fp, "АРХ_СЕКЦИИ")

        # Текстовая аннотация корпуса (номер, этажи, площадь)
        c = building.footprint.centroid
        text_cx = c.x + ox
        text_cy = c.y + oy

        label = f"Корпус {b_num} ({building.floors} эт.)"
        text_entity = msp.add_text(
            label,
            dxfattribs={
                "layer": "АРХ_ПОДПИСИ",
                "height": 2.5,
            },
        )
        text_entity.set_placement((text_cx, text_cy), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

        sub_label = f"GFA: {building.total_gfa:,.0f} м²"
        text_sub = msp.add_text(
            sub_label,
            dxfattribs={
                "layer": "АРХ_ПОДПИСИ",
                "height": 1.8,
            },
        )
        text_sub.set_placement((text_cx, text_cy - 3.2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)

    # 5. Сводная таблица параметров / экспликация в углу участка
    if tep:
        minx, miny, _, _ = site.boundary.bounds
        table_x = minx + ox
        table_y = miny + oy - 15.0

        tep_lines = [
            f"ГЕНЕРАТОР ЗАСТРОЙКИ — ТЭП: {site.cadastral_number or 'Участок'}",
            f"Площадь участка: {tep.site_area:,.0f} м² | Застройка: {tep.building_area:,.0f} м² ({tep.bcr:.1%})",
            f"Общая площадь (GFA): {tep.total_gfa:,.0f} м² | Жилая площадь: {tep.residential_area:,.0f} м²",
            f"К-во квартир: {tep.apartments_total} | Население: {tep.population:.0f} чел. | Парковки: {tep.parking_spaces} м/м",
            f"Количество корпусов: {len(buildings)} | Коэффициент застройки (FAR): {tep.far:.2f}",
        ]
        if site.base_offset != (0.0, 0.0):
            tep_lines.append(f"Координаты: МСК сдвиг X0={site.base_offset[0]:,.1f}, Y0={site.base_offset[1]:,.1f}")

        for idx, line in enumerate(tep_lines):
            t = msp.add_text(
                line,
                dxfattribs={
                    "layer": "АРХ_ЭКСПЛИКАЦИЯ",
                    "height": 2.0,
                },
            )
            t.set_placement((table_x, table_y - idx * 3.5), align=ezdxf.enums.TextEntityAlignment.LEFT)

    doc.saveas(str(path))
    return path
