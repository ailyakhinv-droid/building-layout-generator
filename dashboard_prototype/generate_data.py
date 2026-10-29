"""Скрипт генерации данных и автономного HTML-дашборда в стиле Miass Dashboard.
Работает изолированно в папке dashboard_prototype/ (не отслеживается Git).
"""

from __future__ import annotations

import json
import math
import sys
import os
from pathlib import Path

# Кодировка консоли
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Корень проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import shapely
import yaml
from shapely.geometry import Polygon, MultiPolygon, LineString, LinearRing

from src.core.cadastre import get_cadastral_parcel, create_site_from_cadastre
from src.core.buildable_area import compute_buildable_area
from src.core.placement import PlacementConfig, PlacementEngine
from src.core.tep_calculator import calculate_tep, check_normatives
from src.core.regional_norms import load_regional_norms, get_regional_norm
from src.core.territory_balance import calculate_territory_balance
from src.library.section_library import SectionLibrary
from src.visualization.viewer_3d import build_3d_geojson_data, generate_3d_viewer_html
from src.visualization.map_view import generate_leaflet_map_html


def geom_to_svg_path(geom, minx, miny, maxx, maxy, width=1000, height=700, pad=40):
    """Преобразовать геометрию Shapely в SVG path 'd' с переворотом оси Y и центрированием."""
    dx = maxx - minx
    dy = maxy - miny
    if dx <= 0 or dy <= 0:
        return ""
    scale = min((width - 2 * pad) / dx, (height - 2 * pad) / dy)
    ox = pad + ((width - 2 * pad) - dx * scale) / 2
    oy = pad + ((height - 2 * pad) - dy * scale) / 2

    def pt(x, y):
        sx = ox + (x - minx) * scale
        sy = oy + (maxy - y) * scale  # Y вниз
        return f"{sx:.1f},{sy:.1f}"

    if geom.geom_type == "Polygon":
        pts = [pt(x, y) for x, y in geom.exterior.coords]
        d = "M " + " L ".join(pts) + " Z"
        for interior in geom.interiors:
            i_pts = [pt(x, y) for x, y in interior.coords]
            d += " M " + " L ".join(i_pts) + " Z"
        return d
    elif geom.geom_type == "MultiPolygon":
        parts = []
        for poly in geom.geoms:
            pts = [pt(x, y) for x, y in poly.exterior.coords]
            sub_d = "M " + " L ".join(pts) + " Z"
            for interior in poly.interiors:
                i_pts = [pt(x, y) for x, y in interior.coords]
                sub_d += " M " + " L ".join(i_pts) + " Z"
            parts.append(sub_d)
        return " ".join(parts)
    elif geom.geom_type in ("LineString", "LinearRing"):
        pts = [pt(x, y) for x, y in geom.coords]
        return "M " + " L ".join(pts)
    return ""


def geom_centroid_svg(geom, minx, miny, maxx, maxy, width=1000, height=700, pad=40):
    """Получить SVG координаты центроида геометрии."""
    c = geom.centroid
    dx = maxx - minx
    dy = maxy - miny
    scale = min((width - 2 * pad) / dx, (height - 2 * pad) / dy)
    ox = pad + ((width - 2 * pad) - dx * scale) / 2
    oy = pad + ((height - 2 * pad) - dy * scale) / 2
    return round(ox + (c.x - minx) * scale, 1), round(oy + (maxy - c.y) * scale, 1)


def generate_scenario_data(cad_query: str, typology: str, target_floors: int, scenario_id: str, label: str):
    """Сгенерировать полный пакет данных для сценария."""
    config_path = PROJECT_ROOT / "config" / "defaults.yaml"
    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    library = SectionLibrary(PROJECT_ROOT / "config" / "sections")
    parcel = get_cadastral_parcel(cad_query)
    site = create_site_from_cadastre(parcel)
    compute_buildable_area(site, config)

    placement_cfg = PlacementConfig(
        target_floors=target_floors,
        typology=typology,
        cascade_floors=True,
        asymmetric_wings=True,
    )
    engine = PlacementEngine(site, library, config)
    buildings = engine.generate(placement_cfg)
    tep = calculate_tep(site, buildings, config)

    norm_id = parcel.regional_norm_id or "russia_sp42"
    norm = get_regional_norm(norm_id) or get_regional_norm("russia_sp42")
    balance = calculate_territory_balance(
        site.area,
        tep.building_area,
        tep.population,
        tep.residential_area,
        tep.apartments_total,
        norm,
    )
    checks = check_normatives(tep, config)

    # Вычисляем общие границы для SVG (с запасом 15м)
    b_minx, b_miny, b_maxx, b_maxy = site.boundary.bounds
    pad_m = 15.0
    minx, miny, maxx, maxy = b_minx - pad_m, b_miny - pad_m, b_maxx + pad_m, b_maxy + pad_m
    svg_w, svg_h = 1000, 700

    site_path = geom_to_svg_path(site.boundary, minx, miny, maxx, maxy, svg_w, svg_h)
    buildable_path = geom_to_svg_path(site.buildable_area, minx, miny, maxx, maxy, svg_w, svg_h) if site.buildable_area else ""
    red_lines = [geom_to_svg_path(rl, minx, miny, maxx, maxy, svg_w, svg_h) for rl in getattr(site, "red_lines", [])]

    # Корпуса и секции
    buildings_data = []
    sections_data = []
    section_counter = 0

    category_labels = {
        "MIDDLE": "Рядовая",
        "CORNER": "Угловая",
        "END": "Торцевая",
        "TOWER": "Точечная (башня)",
    }

    # Цвета для категорий
    category_colors = {
        "MIDDLE": "#538db2",  # Мягкий синий
        "CORNER": "#c5a35b",  # Песочно-горчичный
        "END": "#8d9f6b",     # Шалфейно-оливковый
        "TOWER": "#924ff7",   # Пурпурно-сиреневый
    }

    for b_idx, b in enumerate(buildings):
        b_id = f"b{b_idx + 1}"
        b_name = f"Дом Д{b_idx + 1}"
        b_path = geom_to_svg_path(b.footprint, minx, miny, maxx, maxy, svg_w, svg_h)
        b_cx, b_cy = geom_centroid_svg(b.footprint, minx, miny, maxx, maxy, svg_w, svg_h)

        b_entry = {
            "id": b_id,
            "name": b_name,
            "floors": b.floors,
            "min_floors": b.min_floors,
            "max_floors": b.max_floors,
            "sections_count": len(b.sections),
            "total_gfa": round(b.total_gfa),
            "building_area": round(b.total_building_area),
            "apartments_total": sum(b.total_apartments.values()),
            "apartments": b.total_apartments,
            "path": b_path,
            "cx": b_cx,
            "cy": b_cy,
        }
        buildings_data.append(b_entry)

        for s_idx, s in enumerate(b.sections):
            section_counter += 1
            s_id = f"sec_{section_counter}"
            s_label = f"Д{b_idx + 1} · С{s_idx + 1}"
            s_path = geom_to_svg_path(s.footprint, minx, miny, maxx, maxy, svg_w, svg_h)
            s_cx, s_cy = geom_centroid_svg(s.footprint, minx, miny, maxx, maxy, svg_w, svg_h)

            cat = s.section_type.category.upper()
            st_apts = s.get_apartments()

            s_entry = {
                "id": s_id,
                "label": s_label,
                "building_id": b_id,
                "building_name": b_name,
                "section_index": s_idx + 1,
                "type_id": s.section_type.id,
                "type_name": s.section_type.name,
                "category": cat,
                "category_label": category_labels.get(cat, cat),
                "category_color": category_colors.get(cat, "#798392"),
                "floors": s.floors,
                "height_m": round(s.height, 1),
                "width": s.section_type.width,
                "depth": s.section_type.depth,
                "footprint_area": round(s.footprint.area, 1),
                "gfa": round(s.gfa),
                "elevators": getattr(s.section_type, "elevators", 1),
                "commercial_ground": getattr(s.section_type, "has_commercial_ground", False),
                "apartments_total": sum(st_apts.values()),
                "apartments": st_apts,
                "path": s_path,
                "cx": s_cx,
                "cy": s_cy,
            }
            sections_data.append(s_entry)

    # 3D и Leaflet встраивания
    try:
        leaflet_html = generate_leaflet_map_html(site, buildings, tep, height=640, show_sections=True)
    except Exception as e:
        leaflet_html = f"<!-- Leaflet error: {e} -->"

    try:
        viewer_3d_data = build_3d_geojson_data(site, buildings, tep)
        viewer_3d_html = generate_3d_viewer_html(site, buildings, tep, height="640px", default_basemap="light", standalone=False)
    except Exception as e:
        viewer_3d_data = None
        viewer_3d_html = f"<!-- 3D Viewer error: {e} -->"

    geo_lat, geo_lon = site.geo_center if site.geo_center else (0.0, 0.0)
    yandex_maps_url = f"https://yandex.ru/maps/?pt={geo_lon:.6f},{geo_lat:.6f}&z=16&l=map"
    pkk_url = f"https://pkk.rosreestr.ru/#/search/{geo_lat:.6f},{geo_lon:.6f}/16"

    return {
        "id": scenario_id,
        "label": label,
        "cadastral_number": site.cadastral_number,
        "region_name": parcel.region_name,
        "district_name": parcel.district_name,
        "address": parcel.address,
        "norm_name": norm.name if norm else "СП 42.13330.2016",
        "typology": typology,
        "site_area_sqm": round(site.area, 1),
        "site_area_ha": round(site.area / 10000.0, 2),
        "buildable_area_sqm": round(site.buildable_area.area, 1) if site.buildable_area else 0,
        "geo_center": {"lat": round(geo_lat, 6), "lon": round(geo_lon, 6)},
        "yandex_maps_url": yandex_maps_url,
        "pkk_url": pkk_url,
        "svg_viewbox": f"0 0 {svg_w} {svg_h}",
        "site_path": site_path,
        "buildable_path": buildable_path,
        "red_lines_paths": red_lines,
        "tep": {
            "gfa": round(tep.total_gfa),
            "residential_area": round(tep.residential_area),
            "commercial_area": round(getattr(tep, "commercial_area", 0) or (tep.total_gfa - tep.residential_area)),
            "building_area": round(tep.building_area),
            "bcr": round(tep.bcr, 3),
            "far": round(tep.far, 2),
            "apartments_total": tep.apartments_total,
            "apartments_breakdown": {
                "studio": tep.apartments_studio,
                "1k": tep.apartments_1k,
                "2k": tep.apartments_2k,
                "3k": tep.apartments_3k,
                "4k": tep.apartments_4k,
            },
            "population": tep.population,
            "parking_required": balance.parking.required_total,
            "parking_required_guest": balance.parking.required_guest,
            "parking_ground": balance.parking.ground_capacity,
            "parking_ground_area": round(balance.parking.ground_area),
            "parking_underground": balance.parking.underground_deficit,
            "parking_underground_area_est": round(balance.parking.underground_area_est),
            "playgrounds_total": round(balance.playgrounds.total),
            "playgrounds_children": round(balance.playgrounds.children),
            "playgrounds_sport": round(balance.playgrounds.sport),
            "playgrounds_relax": round(balance.playgrounds.relax),
            "playgrounds_utility": round(balance.playgrounds.utility + balance.playgrounds.waste),
            "green_area": round(tep.green_area if hasattr(tep, "green_area") else site.area * 0.25),
        },
        "balance_shares": {k: round(v, 1) for k, v in balance.get_structure_shares().items()},
        "warnings": balance.warnings,
        "norm_checks": {
            k: {
                "name": v["name"],
                "value": round(v["value"], 2) if isinstance(v["value"], float) else v["value"],
                "limit": round(v["limit"], 2) if isinstance(v["limit"], float) else v["limit"],
                "ok": v["ok"],
                "unit": v.get("unit", ""),
            }
            for k, v in checks.items()
        },
        "buildings": buildings_data,
        "sections": sections_data,
        "leaflet_html": leaflet_html,
        "viewer_3d_html": viewer_3d_html,
        "viewer_3d_data": viewer_3d_data,
    }


def main():
    print("Генерация данных сценариев для дашборда...")
    scenarios = []

    # 1. Самара (Квартальная)
    try:
        s1 = generate_scenario_data("63:01:0709002:2320", "AUTO", 14, "samara_auto", "Самара (4.2 га) · Квартальная застройка")
        scenarios.append(s1)
        print("✓ Сценарий 1 (Самара Квартал) готов")
    except Exception as e:
        print("Ошибка сценария 1:", e)

    # 2. Тюмень (Башни)
    try:
        s2 = generate_scenario_data("72:23:0222001:16187", "TOWER", 18, "tyumen_towers", "Тюмень (4.4 га) · Башенная застройка (Towers)")
        scenarios.append(s2)
        print("✓ Сценарий 2 (Тюмень Башни) готов")
    except Exception as e:
        print("Ошибка сценария 2:", e)

    # 3. Самара (П-образные дворы)
    try:
        s3 = generate_scenario_data("63:01:0709002:2320", "U_SHAPE", 12, "samara_u_shape", "Самара (4.2 га) · П-образные дворы")
        scenarios.append(s3)
        print("✓ Сценарий 3 (Самара U-Shape) готов")
    except Exception as e:
        print("Ошибка сценария 3:", e)

    out_json = PROJECT_ROOT / "dashboard_prototype" / "data.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(scenarios, f, ensure_ascii=False, indent=2)
    print(f"✓ Данные сохранены в {out_json}")


if __name__ == "__main__":
    main()
