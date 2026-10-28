"""Сервис генерации застройки для автономного дашборда ТЭП.
Полная поддержка всех функций Streamlit:
- Режим 1: По кадастровому номеру / адресу / координатам WGS-84 + прикрепление CAD;
- Режим 2: По чертежу DWG / DXF с инспекцией слоев и геопривязкой к МСК/кадастру;
- Тонкая настройка координат (ручная широта/долгота);
- Генерация расстановки (AUTO, Towers, U-Shape, L-Shape, Linear);
- Режимы (заданная этажность, подбор под ТЭП, максимизация);
- Территориальный баланс РНГП (парковки, гостевые, подземный дефицит в м², площадки);
- Матрица вариантов по этажности (Optimizer.generate_variants);
- Каталог библиотеки секций;
- Экспорт DXF, 3D HTML, GeoJSON и отчетов.
"""

from __future__ import annotations

import base64
import json
import math
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import shapely
import yaml
from shapely.geometry import Polygon, MultiPolygon, LineString, LinearRing

from src.core.cadastre import (
    PRESET_PARCELS,
    get_cadastral_parcel,
    create_site_from_cadastre,
    smart_resolve_location,
    parse_cadastral_components,
)
from src.core.site_parser import create_rectangular_site
from src.core.buildable_area import compute_buildable_area
from src.core.placement import PlacementConfig, PlacementEngine
from src.core.optimizer import Optimizer
from src.core.tep_calculator import calculate_tep, check_normatives
from src.core.regional_norms import load_regional_norms, get_regional_norm
from src.core.territory_balance import calculate_territory_balance, TerritoryBalanceResult
from src.library.section_library import SectionLibrary
from src.visualization.viewer_3d import generate_3d_viewer_html
from src.visualization.map_view import generate_leaflet_map_html
from src.export.dxf_export import export_dxf
from src.export.html_3d_export import export_3d_html
from src.export.geojson_export import export_geojson
from src.export.report import generate_report
from src.core.cad_parser import parse_cad_site, inspect_cad_layers
from src.geo.msk_converter import (
    get_msk_key_for_region,
    detect_msk_by_coordinates,
    msk_to_wgs84_coords,
    wgs84_to_msk_coords,
    MSK_PRESETS,
)


def geom_to_svg_path(geom, minx, miny, maxx, maxy, width=1000, height=700, pad=40):
    """Преобразовать геометрию Shapely в SVG path 'd' с переворотом оси Y и центрированием."""
    if geom is None or geom.is_empty:
        return ""
    dx = maxx - minx
    dy = maxy - miny
    if dx <= 0 or dy <= 0:
        return ""
    scale = min((width - 2 * pad) / dx, (height - 2 * pad) / dy)
    ox = pad + ((width - 2 * pad) - dx * scale) / 2
    oy = pad + ((height - 2 * pad) - dy * scale) / 2

    def pt(x, y):
        sx = ox + (x - minx) * scale
        sy = oy + (maxy - y) * scale
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
    if geom is None or geom.is_empty:
        return 0, 0
    c = geom.centroid
    dx = maxx - minx
    dy = maxy - miny
    scale = min((width - 2 * pad) / dx, (height - 2 * pad) / dy)
    ox = pad + ((width - 2 * pad) - dx * scale) / 2
    oy = pad + ((height - 2 * pad) - dy * scale) / 2
    return round(ox + (c.x - minx) * scale, 1), round(oy + (maxy - c.y) * scale, 1)


# Кешированное состояние последней генерации
_LAST_STATE = {
    "site": None,
    "buildings": None,
    "tep": None,
    "config": None,
    "balance": None,
}

_CONFIG = None
_LIBRARY = None


def get_config():
    global _CONFIG
    if _CONFIG is None:
        config_path = PROJECT_ROOT / "config" / "defaults.yaml"
        with config_path.open("r", encoding="utf-8") as f:
            _CONFIG = yaml.safe_load(f)
    return dict(_CONFIG)


def get_library():
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = SectionLibrary(PROJECT_ROOT / "config" / "sections")
    return _LIBRARY


def get_library_catalog() -> list[dict[str, Any]]:
    """Получить полный каталог типовых секций из библиотеки с их характеристиками."""
    library = get_library()
    sections = library.get_all()
    catalog = []
    category_names = {
        "MIDDLE": "Рядовая секция (центральное звено корпуса)",
        "CORNER": "Угловая поворотная секция (дворы)",
        "END": "Торцевая секция с окнами на фасад",
        "TOWER": "Точечная башня (доминанта)",
    }
    for s in sections:
        cat = s.category.upper()
        total_apts = sum(s.apartments_per_floor.values())
        catalog.append({
            "id": s.id,
            "code": getattr(s, "section_code", "") or s.id,
            "name": s.name,
            "category": cat,
            "category_name": category_names.get(cat, cat),
            "width": s.width,
            "depth": s.depth,
            "floor_area": round(s.floor_area, 1),
            "elevators": s.elevators,
            "min_floors": s.min_floors,
            "max_floors": s.max_floors,
            "default_floors": s.default_floors,
            "has_commercial_ground": s.has_commercial_ground,
            "apartments_per_floor": s.apartments_per_floor,
            "total_apartments_per_floor": total_apts,
            "apt_areas": getattr(s, "apt_areas", {}),
        })
    return catalog


def inspect_cad_bytes(file_bytes: bytes, filename: str) -> list[dict[str, Any]]:
    """Инспекция слоев загруженного чертежа DWG / DXF."""
    layers_info = inspect_cad_layers(file_bytes, filename)
    result = []
    for l in layers_info:
        result.append({
            "name": l.name,
            "total_entities": l.total_entities,
            "is_candidate": l.is_candidate,
            "is_red_line_candidate": l.is_red_line_candidate,
            "lines_count": l.lines_count,
            "polylines_count": l.polylines_count,
        })
    return result


def _create_site_from_params(
    params: dict[str, Any], config: dict[str, Any]
) -> tuple[Site, Any, str, str, str, dict[str, Any]]:
    """Создать и подготовить объект Site по входным параметрам запроса."""
    site_mode = params.get("site_mode", "cadastre")  # 'cadastre' или 'cad'
    site_rotation = float(params.get("site_rotation", 0.0))
    override_lat = float(params.get("override_lat", 0.0))
    override_lon = float(params.get("override_lon", 0.0))

    cad_file_b64 = params.get("cad_file_base64")
    cad_filename = params.get("cad_filename", "contour.dxf")
    boundary_layer = params.get("boundary_layer") or None
    red_lines_layer = params.get("red_lines_layer") or None
    if red_lines_layer in ("(нет)", "none", ""):
        red_lines_layer = None

    site = None
    parcel_region_name = "Самарская область"
    parcel_district_name = "г. Самара"
    parcel_address = "г. Самара"
    norm_id = "russia_sp42"

    # =========================================================================
    # РЕЖИМ: ПО ЧЕРТЕЖУ DWG / DXF (ОСНОВНОЙ РЕЖИМ ПРОЕКТИРОВАНИЯ)
    # =========================================================================
    if site_mode == "cad":
        assigned_cad = (params.get("assigned_cad_query") or "").strip()
        file_bytes = base64.b64decode(cad_file_b64) if cad_file_b64 else None

        # Предварительный парсинг чертежа для извлечения кадастрового номера
        detected_cad = None
        if file_bytes:
            try:
                from src.core.cad_parser import _load_dxf_document, extract_cadastral_info_from_doc
                doc_tmp = _load_dxf_document(file_bytes, filename=cad_filename)
                cads_found = extract_cadastral_info_from_doc(doc_tmp, filename=cad_filename)
                if cads_found:
                    detected_cad = cads_found[0]
            except Exception:
                pass

        if not assigned_cad or assigned_cad == "63:01:0709002:2320":
            if detected_cad:
                assigned_cad = detected_cad
            elif not assigned_cad:
                assigned_cad = "63:01:0709002:2320"

        reg_name, dist_name, resolved_norm_id, c_lat, c_lon = smart_resolve_location(assigned_cad)
        norm_id = resolved_norm_id or "russia_sp42"

        # Если файл еще не загружен пользователем, подгружаем тестовый контур МСК для мгновенной демонстрации
        if not file_bytes:
            sample_dxf_path = PROJECT_ROOT / "output" / "test_boundary_msk.dxf"
            if sample_dxf_path.exists():
                try:
                    with open(sample_dxf_path, "rb") as f_samp:
                        file_bytes = f_samp.read()
                    cad_filename = "test_boundary_msk.dxf"
                except Exception:
                    file_bytes = None

        if file_bytes:
            try:
                site, cad_meta = parse_cad_site(
                    file_bytes,
                    filename=cad_filename,
                    boundary_layer=boundary_layer,
                    red_lines_layer=red_lines_layer,
                    normalize_origin=True,
                )
            except Exception as e:
                print(f"Ошибка парсинга чертежа DXF: {e}")
                site = create_rectangular_site(240, 160, geo_center=(c_lat, c_lon))
                site.georef_source = f"Ошибка чертежа: {e}"
                cad_meta = {
                    "boundary_layer": "Не найден",
                    "red_lines_layer": "",
                    "vertices_count": 4,
                    "error": str(e),
                }
            layers_info = []
            try:
                layers_info = inspect_cad_layers(file_bytes, filename=cad_filename)
            except Exception as e:
                print(f"Ошибка чтения слоев CAD: {e}")

            comps = parse_cadastral_components(assigned_cad)
            reg_code = comps.get("region_code") if comps else "63"

            # Определение системы координат МСК
            is_msk = abs(site.base_offset[0]) > 500 or abs(site.base_offset[1]) > 500
            requested_msk = params.get("msk_zone")
            if requested_msk and requested_msk in MSK_PRESETS:
                detected_msk = requested_msk
            elif is_msk:
                detected_msk = get_msk_key_for_region(reg_code, site.base_offset[0], site.base_offset[1])
                if not detected_msk:
                    detected_msk = detect_msk_by_coordinates(site.base_offset[0], site.base_offset[1], region_hint=reg_code)
                if not detected_msk and reg_code:
                    detected_msk = get_msk_key_for_region(reg_code, site.base_offset[0], site.base_offset[1])
                if not detected_msk:
                    detected_msk = "МСК-63 Зона 1 (Самара)"
            else:
                detected_msk = "МСК-63 Зона 1 (Самара)"

            exp_c = (c_lat, c_lon)
            if detected_msk in MSK_PRESETS:
                preset = MSK_PRESETS[detected_msk]
                exp_c = (preset["default_lat"], preset["default_lon"])
                parcel_region_name = preset.get("region", reg_name)
                if preset.get("city"):
                    parcel_district_name = f"г. {preset['city']}"
                norm_id = "moscow_mngs" if "77" in detected_msk else ("spb_rnp" if "78" in detected_msk else "russia_sp42")

            if override_lat != 0.0 and override_lon != 0.0:
                site.geo_center = (override_lat, override_lon)
                site.georef_source = "Ручные координаты WGS-84"
            elif is_msk:
                cad_lat, cad_lon = msk_to_wgs84_coords(
                    site.base_offset[0],
                    site.base_offset[1],
                    detected_msk,
                    axis_order="auto",
                    expected_center=exp_c,
                )
                site.geo_center = (cad_lat, cad_lon)
                site.georef_source = f"По координатам чертежа ({detected_msk})"
            else:
                site.geo_center = (c_lat, c_lon)
                site.georef_source = "По кадастровому номеру / адресу"

            site.cadastral_number = params.get("assigned_cad_query") or f"Чертёж: {cad_filename}"
            site.address = f"{parcel_region_name}, {parcel_district_name} (чертёж: {cad_filename})"
            parcel_address = site.address

            site.cad_info = {
                "is_cad": True,
                "filename": cad_filename,
                "detected_cadastre": getattr(site, "cadastral_number", None) or cad_meta.get("detected_cadastre"),
                "boundary_layer": boundary_layer or cad_meta.get("boundary_layer") or "0",
                "red_lines_layer": red_lines_layer or cad_meta.get("red_lines_layer") or "",
                "vertices_count": len(site.boundary.exterior.coords) - 1,
                "dimensions": {
                    "width_m": round(site.boundary.bounds[2] - site.boundary.bounds[0], 1),
                    "depth_m": round(site.boundary.bounds[3] - site.boundary.bounds[1], 1),
                },
                "base_offset": {
                    "x": round(site.base_offset[0], 2),
                    "y": round(site.base_offset[1], 2),
                },
                "detected_msk": detected_msk,
                "available_msk_presets": list(MSK_PRESETS.keys()),
                "wgs84": {
                    "lat": round(site.geo_center[0], 6),
                    "lon": round(site.geo_center[1], 6),
                },
                "area_sqm": round(site.area, 1),
                "area_ha": round(site.area / 10000.0, 2),
                "layers": [
                    {
                        "name": l.name,
                        "count": l.total_entities,
                        "is_candidate": l.is_candidate,
                        "is_redline": l.is_red_line_candidate,
                    }
                    for l in layers_info
                ],
            }
        else:
            site = create_rectangular_site(200, 150, geo_center=(c_lat, c_lon))
            site.georef_source = "Прямоугольный участок"
            site.cad_info = {"is_cad": False}

    # =========================================================================
    # РЕЖИМ: КОНЦЕПТУАЛЬНЫЙ УЧАСТОК (СВОБОДНЫЕ РАЗМЕРЫ В МЕТРАХ)
    # =========================================================================
    elif site_mode == "concept":
        c_w = float(params.get("concept_width") or 200.0)
        c_d = float(params.get("concept_depth") or 150.0)
        reg_name, dist_name, resolved_norm_id, c_lat, c_lon = smart_resolve_location("63:01:0709002:2320")
        use_lat = override_lat if override_lat != 0.0 else c_lat
        use_lon = override_lon if override_lon != 0.0 else c_lon
        norm_id = resolved_norm_id or "russia_sp42"

        site = create_rectangular_site(c_w, c_d, geo_center=(use_lat, use_lon))
        parcel_region_name = reg_name
        parcel_district_name = dist_name
        site.cadastral_number = f"Концепт {c_w:.0f}×{c_d:.0f}м"
        site.address = f"{reg_name}, {dist_name} (концепт {c_w:.0f}×{c_d:.0f} м, {site.area:,.0f} м²)"
        parcel_address = site.address
        site.georef_source = f"Концептуальный участок ({c_w:.0f}×{c_d:.0f} м)"
        site.cad_info = {
            "is_cad": False,
            "is_concept": True,
            "dimensions": {"width_m": c_w, "depth_m": c_d},
            "area_sqm": round(site.area, 1),
            "area_ha": round(site.area / 10000.0, 2),
            "vertices_count": 4,
        }

    # =========================================================================
    # РЕЖИМ: ПО КАДАСТРОВОМУ НОМЕРУ / АДРЕСУ РОСРЕЕСТРА
    # =========================================================================
    else:
        cad_query = (params.get("cad_query") or "63:01:0709002:2320").strip()
        custom_area = float(params.get("custom_area") or 32000)
        enable_red_line = bool(params.get("enable_red_line", False))

        reg_name, dist_name, resolved_norm_id, auto_lat, auto_lon = smart_resolve_location(cad_query)
        norm_id = resolved_norm_id or "russia_sp42"

        use_lat = override_lat if override_lat != 0.0 else auto_lat
        use_lon = override_lon if override_lon != 0.0 else auto_lon

        try:
            parcel = get_cadastral_parcel(
                cad_query,
                custom_area_sqm=custom_area,
                override_lat=use_lat,
                override_lon=use_lon,
                add_red_line=enable_red_line,
            )
            site = create_site_from_cadastre(parcel)
            parcel_region_name = parcel.region_name
            parcel_district_name = parcel.district_name
            parcel_address = parcel.address
            site.georef_source = f"По кадастру ({parcel.region_name})"
        except Exception:
            site = create_rectangular_site(200, 150, geo_center=(use_lat, use_lon))
            site.address = f"{reg_name}, {dist_name} (участок)"

        # Если прикреплен файл CAD поверх кадастра
        if cad_file_b64:
            try:
                sub_bytes = base64.b64decode(cad_file_b64)
                sub_site, sub_meta = parse_cad_site(
                    sub_bytes,
                    filename=cad_filename,
                    boundary_layer=boundary_layer,
                    red_lines_layer=red_lines_layer,
                    normalize_origin=True,
                )
                site.boundary = sub_site.boundary
                site.base_offset = sub_site.base_offset
                if sub_site.red_lines:
                    site.red_lines = sub_site.red_lines

                # Если чертеж содержит геодезические координаты МСК и не задан ручной override
                is_sub_msk = abs(sub_site.base_offset[0]) > 500 or abs(sub_site.base_offset[1]) > 500
                det_sub_msk = "МСК-63 Зона 1 (Самара)"
                if is_sub_msk and (override_lat == 0.0 or override_lon == 0.0):
                    requested_msk = params.get("msk_zone")
                    if requested_msk and requested_msk in MSK_PRESETS:
                        det_sub_msk = requested_msk
                    else:
                        c_comps = parse_cadastral_components(cad_query)
                        c_reg = c_comps.get("region_code") if c_comps else None
                        if c_reg:
                            det_sub_msk = get_msk_key_for_region(c_reg, sub_site.base_offset[0], sub_site.base_offset[1])
                        if not det_sub_msk:
                            det_sub_msk = detect_msk_by_coordinates(sub_site.base_offset[0], sub_site.base_offset[1], region_hint=c_reg)
                        if not det_sub_msk:
                            det_sub_msk = "МСК-63 Зона 1 (Самара)"

                    exp_lat, exp_lon = auto_lat, auto_lon
                    if det_sub_msk in MSK_PRESETS:
                        preset = MSK_PRESETS[det_sub_msk]
                        exp_lat, exp_lon = preset["default_lat"], preset["default_lon"]
                    sub_lat, sub_lon = msk_to_wgs84_coords(
                        sub_site.base_offset[0],
                        sub_site.base_offset[1],
                        det_sub_msk,
                        axis_order="auto",
                        expected_center=(exp_lat, exp_lon),
                    )
                    site.geo_center = (sub_lat, sub_lon)

                site.georef_source = f"Контур из чертежа {cad_filename} ({site.area:,.0f} м²)"
                site.cad_info = {
                    "is_cad": True,
                    "filename": cad_filename,
                    "boundary_layer": boundary_layer or sub_meta.get("boundary_layer") or "0",
                    "red_lines_layer": red_lines_layer or sub_meta.get("red_lines_layer") or "",
                    "vertices_count": len(site.boundary.exterior.coords) - 1,
                    "dimensions": {
                        "width_m": round(site.boundary.bounds[2] - site.boundary.bounds[0], 1),
                        "depth_m": round(site.boundary.bounds[3] - site.boundary.bounds[1], 1),
                    },
                    "base_offset": {
                        "x": round(site.base_offset[0], 2),
                        "y": round(site.base_offset[1], 2),
                    },
                    "detected_msk": det_sub_msk,
                    "available_msk_presets": list(MSK_PRESETS.keys()),
                    "wgs84": {
                        "lat": round(site.geo_center[0], 6),
                        "lon": round(site.geo_center[1], 6),
                    },
                    "area_sqm": round(site.area, 1),
                    "area_ha": round(site.area / 10000.0, 2),
                }
            except Exception as e:
                print(f"Ошибка применения CAD-контура: {e}")
        else:
            site.cad_info = {"is_cad": False}

    # Поворот участка вокруг геометрического центра
    if site_rotation != 0.0:
        site.rotate(site_rotation)

    # Нормативы
    chosen_norm_id = params.get("regional_norm_id") or norm_id or "russia_sp42"
    selected_norm = get_regional_norm(chosen_norm_id) or get_regional_norm("russia_sp42")

    max_bcr = float(params.get("max_bcr") or selected_norm.density.max_bcr)
    max_far = float(params.get("max_far") or selected_norm.density.max_far)
    green_ratio_min = float(params.get("green_ratio_min") or selected_norm.density.green_ratio_min)
    config["max_bcr"] = max_bcr
    config["max_far"] = max_far
    config["green_ratio_min"] = green_ratio_min

    # Отступы
    boundary_setback = float(params.get("boundary_setback", config.get("boundary_setback", 6.0)))
    red_line_setback = float(params.get("red_line_setback", config.get("red_line_setback", 5.0)))
    config["boundary_setback"] = boundary_setback
    config["red_line_setback"] = red_line_setback

    floor_height = float(params.get("floor_height", 3.0))
    max_building_height_m = float(params.get("max_building_height_m", 0.0))
    config["floor_height"] = floor_height
    config["max_building_height_m"] = max_building_height_m if max_building_height_m > 0 else None

    # Допустимая зона застройки
    try:
        compute_buildable_area(site, config)
    except Exception:
        pass

    return site, selected_norm, parcel_region_name, parcel_district_name, parcel_address, config


def preview_site(params: dict[str, Any]) -> dict[str, Any]:
    """Сформировать предпросмотр участка для Этапа 1 (Посадка и ориентация).

    Возвращает интерактивную карту Leaflet с transform-ручками для прямого
    перетаскивания и поворота контура, БЕЗ корпусов и секций.
    """
    config = get_config()
    site, selected_norm, parcel_region_name, parcel_district_name, parcel_address, config = (
        _create_site_from_params(params, config)
    )

    # Подготовка SVG контура
    b_minx, b_miny, b_maxx, b_maxy = site.boundary.bounds
    pad_m = 15.0
    minx, miny, maxx, maxy = b_minx - pad_m, b_miny - pad_m, b_maxx + pad_m, b_maxy + pad_m
    svg_w, svg_h = 1000, 700

    site_path = geom_to_svg_path(site.boundary, minx, miny, maxx, maxy, svg_w, svg_h)
    buildable_path = (
        geom_to_svg_path(site.buildable_area, minx, miny, maxx, maxy, svg_w, svg_h)
        if site.buildable_area
        else ""
    )
    red_lines = [
        geom_to_svg_path(rl, minx, miny, maxx, maxy, svg_w, svg_h)
        for rl in getattr(site, "red_lines", [])
    ]

    # Leaflet HTML с interactive_transform=True и БЕЗ зданий
    try:
        leaflet_html = generate_leaflet_map_html(
            site,
            buildings=None,
            tep=None,
            height=640,
            show_sections=False,
            interactive_transform=True,
        )
    except Exception as e:
        leaflet_html = f"<!-- Leaflet Preview Error: {e} -->"

    try:
        viewer_3d_html = generate_3d_viewer_html(
            site,
            buildings=None,
            tep=None,
            height="640px",
            default_basemap="light",
            standalone=False,
        )
    except Exception as e:
        viewer_3d_html = f"<!-- 3D Preview Error: {e} -->"

    geo_lat, geo_lon = site.geo_center if site.geo_center else (53.2502, 50.3184)
    yandex_maps_url = f"https://yandex.ru/maps/?pt={geo_lon:.6f},{geo_lat:.6f}&z=16&l=map"
    pkk_url = f"https://pkk.rosreestr.ru/#/search/{geo_lat:.6f},{geo_lon:.6f}/16"

    return {
        "stage": 1,
        "site_locked": False,
        "id": f"preview_{int(math.floor(math.sin(site.area) * 100000))}",
        "label": f"{parcel_region_name} · Этап 1: Посадка",
        "cadastral_number": site.cadastral_number,
        "region_name": parcel_region_name,
        "district_name": parcel_district_name,
        "address": parcel_address,
        "norm_name": selected_norm.name,
        "site_rotation": round(site.rotation_deg, 1),
        "site_area_sqm": round(site.area, 1),
        "site_area_ha": round(site.area / 10000.0, 2),
        "buildable_area_sqm": round(site.buildable_area.area, 1) if site.buildable_area else 0,
        "geo_center": {"lat": round(geo_lat, 6), "lon": round(geo_lon, 6)},
        "georef_source": getattr(site, "georef_source", ""),
        "base_offset": list(getattr(site, "base_offset", (0.0, 0.0))),
        "cad_info": getattr(site, "cad_info", None),
        "vertices_count": len(site.boundary.exterior.coords) - 1,
        "site_dimensions": [
            round(site.boundary.bounds[2] - site.boundary.bounds[0], 1),
            round(site.boundary.bounds[3] - site.boundary.bounds[1], 1),
        ],
        "yandex_maps_url": yandex_maps_url,
        "pkk_url": pkk_url,
        "svg_viewbox": f"0 0 {svg_w} {svg_h}",
        "site_path": site_path,
        "buildable_path": buildable_path,
        "red_lines_paths": red_lines,
        "optimization_note": "",
        "leaflet_html": leaflet_html,
        "viewer_3d_html": viewer_3d_html,
        "buildings": [],
        "sections": [],
        "tep": {
            "gfa": 0,
            "residential_area": 0,
            "commercial_area": 0,
            "building_area": 0,
            "bcr": 0.0,
            "far": 0.0,
            "apartments_total": 0,
            "population": 0,
            "parking_required": 0,
            "green_area": round(site.area * 0.25),
        },
    }


def run_pipeline(params: dict[str, Any]) -> dict[str, Any]:
    """Запустить полный расчет застройки по параметрам интерфейса (Этап 2)."""
    global _LAST_STATE

    if params.get("stage") == 1 or params.get("preview_only") is True:
        return preview_site(params)

    config = get_config()
    library = get_library()

    site, selected_norm, parcel_region_name, parcel_district_name, parcel_address, config = (
        _create_site_from_params(params, config)
    )

    # 4. Конфигурация расстановки
    typology = params.get("typology", "AUTO")
    courtyard_orientation = params.get("courtyard_orientation", "SOUTH")
    variable_insolation = bool(params.get("variable_insolation", True))
    cascade_floors = bool(params.get("cascade_floors", True))
    asymmetric_wings = bool(params.get("asymmetric_wings", True))
    min_wing_floors = int(params.get("min_wing_floors", 8))
    allow_towers_in_mixed = bool(params.get("allow_towers_in_mixed", True))
    max_sections = int(params.get("max_sections", 8))
    target_floors = int(params.get("target_floors", 14))
    preferred_sections = params.get("preferred_section_ids") or None
    floor_height = float(params.get("floor_height", config.get("floor_height", 3.0)))
    max_building_height_m = float(params.get("max_building_height_m", config.get("max_building_height_m", 0.0) or 0.0))

    urban_block_size = float(params.get("urban_block_size", 100.0))
    internal_road_width = float(params.get("internal_road_width", 16.0))
    perimeter_layout_style = params.get("perimeter_layout_style", "U_SHAPE")
    max_bcr = float(config["max_bcr"]) if config.get("max_bcr") is not None else None
    max_far = float(config["max_far"]) if config.get("max_far") is not None else None

    placement_cfg = PlacementConfig(
        target_floors=target_floors,
        max_sections_per_building=max_sections,
        typology=typology,
        courtyard_orientation=courtyard_orientation,
        variable_insolation=variable_insolation,
        cascade_floors=cascade_floors,
        asymmetric_wings=asymmetric_wings,
        min_wing_floors=min_wing_floors,
        floor_height=floor_height,
        max_building_height_m=max_building_height_m if max_building_height_m > 0 else None,
        allow_towers_in_mixed=allow_towers_in_mixed,
        preferred_section_ids=preferred_sections,
        urban_block_size=urban_block_size,
        internal_road_width=internal_road_width,
        perimeter_layout_style=perimeter_layout_style,
        max_bcr=max_bcr,
        max_far=max_far,
    )

    # 5. Режимы генерации
    gen_mode = params.get("gen_mode", "fixed")
    opt_note = ""

    if gen_mode == "fixed":
        engine = PlacementEngine(site, library, config)
        buildings = engine.generate(placement_cfg)
        tep = calculate_tep(site, buildings, config)

    elif gen_mode == "target":
        target_metric = params.get("target_metric", "far")
        target_val = float(params.get("target_value", 1.5))
        target_tep = {}
        if target_metric == "far":
            target_tep["target_far"] = target_val
        elif target_metric == "apts":
            target_tep["target_apartments"] = int(target_val)
        else:
            target_tep["target_gfa"] = float(target_val)

        optimizer = Optimizer(site, library, config, base_placement_config=placement_cfg)
        result = optimizer.optimize_for_target(target_tep)
        buildings = result.buildings
        tep = result.tep

    elif gen_mode == "maximize":
        respect_norms = bool(params.get("respect_norms", True))
        explore_all_typs = bool(params.get("explore_all_typologies", False))
        optimizer = Optimizer(site, library, config, base_placement_config=placement_cfg)
        result = optimizer.optimize_maximize(
            respect_normatives=respect_norms,
            explore_typologies=explore_all_typs,
        )
        buildings = result.buildings
        tep = result.tep
        opt_note = getattr(result, "note", "")

    else:
        engine = PlacementEngine(site, library, config)
        buildings = engine.generate(placement_cfg)
        tep = calculate_tep(site, buildings, config)

    # 6. Баланс территории и машиномест
    balance: TerritoryBalanceResult = calculate_territory_balance(
        site.area,
        tep.building_area,
        tep.population,
        tep.residential_area,
        tep.apartments_total,
        selected_norm,
    )
    checks = check_normatives(tep, config)

    # Вариант 1 (Целевой / Сбалансированный)
    var1 = _package_single_variant(
        site, buildings, tep, balance, checks, selected_norm,
        parcel_region_name, parcel_district_name, parcel_address,
        opt_note, typology, target_floors,
        variant_id="var_1", variant_name="Сбалансированный", variant_tag="Целевой"
    )

    # Вариант 2 (Максимум GFA)
    v2_floors = min(24, max(target_floors + 3, 16))
    if max_building_height_m and max_building_height_m > 0:
        v2_floors = min(v2_floors, int(max_building_height_m // floor_height))
    v2_cfg = PlacementConfig(
        target_floors=v2_floors,
        max_sections_per_building=max(max_sections, 10),
        typology="AUTO" if typology == "AUTO" else typology,
        courtyard_orientation=courtyard_orientation,
        variable_insolation=True,
        cascade_floors=False,
        asymmetric_wings=asymmetric_wings,
        min_wing_floors=max(min_wing_floors, v2_floors - 2),
        floor_height=floor_height,
        max_building_height_m=max_building_height_m if max_building_height_m > 0 else None,
        allow_towers_in_mixed=True,
        preferred_section_ids=preferred_sections,
        urban_block_size=urban_block_size,
        internal_road_width=internal_road_width,
        perimeter_layout_style=perimeter_layout_style,
        max_bcr=max_bcr,
        max_far=max_far,
    )
    try:
        v2_engine = PlacementEngine(site, library, config)
        v2_buildings = v2_engine.generate(v2_cfg)
        v2_tep = calculate_tep(site, v2_buildings, config)
        v2_balance = calculate_territory_balance(site.area, v2_tep.building_area, v2_tep.population, v2_tep.residential_area, v2_tep.apartments_total, selected_norm)
        v2_checks = check_normatives(v2_tep, config)
        var2 = _package_single_variant(
            site, v2_buildings, v2_tep, v2_balance, v2_checks, selected_norm,
            parcel_region_name, parcel_district_name, parcel_address,
            "Максимум полезного выхода GFA при нормативном соблюдении BCR и FAR", typology, v2_floors,
            variant_id="var_2", variant_name="Максимум GFA", variant_tag="Инвестиционный"
        )
    except Exception as e:
        print(f"Ошибка расчета Варианта 2: {e}")
        v2_buildings, v2_tep, v2_balance = buildings, tep, balance
        var2 = dict(var1)
        var2["variant_id"] = "var_2"
        var2["variant_name"] = "Максимум GFA"
        var2["variant_tag"] = "Инвестиционный"

    # Вариант 3 (Комфорт-класс)
    v3_floors = max(8, min(target_floors - 3, 11))
    v3_cfg = PlacementConfig(
        target_floors=v3_floors,
        max_sections_per_building=max(2, max_sections - 2),
        typology=typology,
        courtyard_orientation="SOUTH",
        variable_insolation=True,
        cascade_floors=True,
        asymmetric_wings=True,
        min_wing_floors=max(6, v3_floors - 3),
        floor_height=floor_height,
        max_building_height_m=max_building_height_m if max_building_height_m > 0 else None,
        allow_towers_in_mixed=False,
        preferred_section_ids=preferred_sections,
        urban_block_size=urban_block_size,
        internal_road_width=internal_road_width,
        perimeter_layout_style=perimeter_layout_style,
        max_bcr=min(max_bcr or 0.40, 0.32),
        max_far=max_far,
    )
    try:
        v3_engine = PlacementEngine(site, library, config)
        v3_buildings = v3_engine.generate(v3_cfg)
        v3_tep = calculate_tep(site, v3_buildings, config)
        v3_balance = calculate_territory_balance(site.area, v3_tep.building_area, v3_tep.population, v3_tep.residential_area, v3_tep.apartments_total, selected_norm)
        v3_checks = check_normatives(v3_tep, config)
        var3 = _package_single_variant(
            site, v3_buildings, v3_tep, v3_balance, v3_checks, selected_norm,
            parcel_region_name, parcel_district_name, parcel_address,
            "Комфортная среда: умеренная этажность, увеличенные дворы, высокая доля озеленения", typology, v3_floors,
            variant_id="var_3", variant_name="Комфорт-класс", variant_tag="Экологичный"
        )
    except Exception as e:
        print(f"Ошибка расчета Варианта 3: {e}")
        v3_buildings, v3_tep, v3_balance = buildings, tep, balance
        var3 = dict(var1)
        var3["variant_id"] = "var_3"
        var3["variant_name"] = "Комфорт-класс"
        var3["variant_tag"] = "Экологичный"

    # Сохраняем состояние для экспорта
    _LAST_STATE["site"] = site
    _LAST_STATE["buildings"] = buildings
    _LAST_STATE["tep"] = tep
    _LAST_STATE["config"] = config
    _LAST_STATE["balance"] = balance
    _LAST_STATE["_variants_cache"] = [
        {"site": site, "buildings": buildings, "tep": tep, "balance": balance},
        {"site": site, "buildings": v2_buildings, "tep": v2_tep, "balance": v2_balance},
        {"site": site, "buildings": v3_buildings, "tep": v3_tep, "balance": v3_balance},
    ]
    _LAST_STATE["active_variant_index"] = 0

    # Важно: создаем независимую копию var1 до добавления списка variants, чтобы исключить циклическую ссылку в JSON
    var1_clean = dict(var1)
    var1["variants"] = [var1_clean, var2, var3]
    var1["active_variant_index"] = 0
    return var1


def _package_single_variant(
    site: Site,
    buildings: list[Building],
    tep: TEP,
    balance: TerritoryBalanceResult,
    checks: dict[str, Any],
    selected_norm: Any,
    parcel_region_name: str,
    parcel_district_name: str,
    parcel_address: str,
    opt_note: str,
    typology: str,
    target_floors: int,
    variant_id: str = "var_1",
    variant_name: str = "Сбалансированный",
    variant_tag: str = "Целевой",
) -> dict[str, Any]:
    """Сформировать сериализуемый словарь данных для конкретного варианта застройки."""
    b_minx, b_miny, b_maxx, b_maxy = site.boundary.bounds
    pad_m = 15.0
    minx, miny, maxx, maxy = b_minx - pad_m, b_miny - pad_m, b_maxx + pad_m, b_maxy + pad_m
    svg_w, svg_h = 1000, 700

    site_path = geom_to_svg_path(site.boundary, minx, miny, maxx, maxy, svg_w, svg_h)
    buildable_path = geom_to_svg_path(site.buildable_area, minx, miny, maxx, maxy, svg_w, svg_h) if site.buildable_area else ""
    red_lines = [geom_to_svg_path(rl, minx, miny, maxx, maxy, svg_w, svg_h) for rl in getattr(site, "red_lines", [])]

    category_labels = {
        "MIDDLE": "Рядовая",
        "CORNER": "Угловая",
        "END": "Торцевая",
        "TOWER": "Точечная (башня)",
    }
    category_colors = {
        "MIDDLE": "#538db2",
        "CORNER": "#c5a35b",
        "END": "#8d9f6b",
        "TOWER": "#924ff7",
    }

    buildings_data = []
    sections_data = []
    section_counter = 0

    for b_idx, b in enumerate(buildings):
        b_id = f"b{b_idx + 1}"
        b_name = f"Дом Д{b_idx + 1}"
        b_path = geom_to_svg_path(b.footprint, minx, miny, maxx, maxy, svg_w, svg_h)
        b_cx, b_cy = geom_centroid_svg(b.footprint, minx, miny, maxx, maxy, svg_w, svg_h)

        buildings_data.append({
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
        })

        for s_idx, s in enumerate(b.sections):
            section_counter += 1
            s_id = f"sec_{section_counter}"
            s_label = f"Д{b_idx + 1} · С{s_idx + 1}"
            s_path = geom_to_svg_path(s.footprint, minx, miny, maxx, maxy, svg_w, svg_h)
            s_cx, s_cy = geom_centroid_svg(s.footprint, minx, miny, maxx, maxy, svg_w, svg_h)
            cat = s.section_type.category.upper()
            st_apts = s.get_apartments()

            sections_data.append({
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
            })

    try:
        leaflet_html = generate_leaflet_map_html(site, buildings, tep, height=640, show_sections=True)
    except Exception as e:
        leaflet_html = f"<!-- Leaflet: {e} -->"

    try:
        viewer_3d_html = generate_3d_viewer_html(site, buildings, tep, height="640px", default_basemap="light", standalone=False)
    except Exception as e:
        viewer_3d_html = f"<!-- 3D: {e} -->"

    geo_lat, geo_lon = site.geo_center if site.geo_center else (53.2502, 50.3184)
    yandex_maps_url = f"https://yandex.ru/maps/?pt={geo_lon:.6f},{geo_lat:.6f}&z=16&l=map"
    pkk_url = f"https://pkk.rosreestr.ru/#/search/{geo_lat:.6f},{geo_lon:.6f}/16"

    return {
        "stage": 2,
        "site_locked": True,
        "variant_id": variant_id,
        "variant_name": variant_name,
        "variant_tag": variant_tag,
        "id": f"gen_{variant_id}_{int(math.floor(math.sin(target_floors) * 100000))}",
        "label": f"{parcel_region_name} · {variant_name}",
        "cadastral_number": site.cadastral_number,
        "region_name": parcel_region_name,
        "district_name": parcel_district_name,
        "address": parcel_address,
        "norm_name": selected_norm.name,
        "typology": typology,
        "site_rotation": round(site.rotation_deg, 1),
        "site_area_sqm": round(site.area, 1),
        "site_area_ha": round(site.area / 10000.0, 2),
        "buildable_area_sqm": round(site.buildable_area.area, 1) if site.buildable_area else 0,
        "geo_center": {"lat": round(geo_lat, 6), "lon": round(geo_lon, 6)},
        "georef_source": getattr(site, "georef_source", ""),
        "base_offset": list(getattr(site, "base_offset", (0.0, 0.0))),
        "cad_info": getattr(site, "cad_info", None),
        "vertices_count": len(site.boundary.exterior.coords) - 1,
        "site_dimensions": [
            round(site.boundary.bounds[2] - site.boundary.bounds[0], 1),
            round(site.boundary.bounds[3] - site.boundary.bounds[1], 1),
        ],
        "yandex_maps_url": yandex_maps_url,
        "pkk_url": pkk_url,
        "svg_viewbox": f"0 0 {svg_w} {svg_h}",
        "site_path": site_path,
        "buildable_path": buildable_path,
        "red_lines_paths": red_lines,
        "optimization_note": opt_note,
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
            "green_area": round(getattr(tep, "green_area", site.area * 0.25)),
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
    }


def set_active_variant(index: int) -> dict[str, Any]:
    """Активировать один из 3-х рассчитанных вариантов для последующего экспорта."""
    global _LAST_STATE
    cache_list = _LAST_STATE.get("_variants_cache") or []
    if 0 <= index < len(cache_list):
        item = cache_list[index]
        _LAST_STATE["site"] = item["site"]
        _LAST_STATE["buildings"] = item["buildings"]
        _LAST_STATE["tep"] = item["tep"]
        _LAST_STATE["balance"] = item["balance"]
        _LAST_STATE["active_variant_index"] = index
        return {"status": "ok", "active_variant_index": index}
    return {"status": "error", "message": "Variant not found"}


def compute_variants_matrix(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Рассчитать матрицу вариантов этажности."""
    config = get_config()
    library = get_library()

    site, selected_norm, _, _, _, config = _create_site_from_params(params, config)
    try:
        compute_buildable_area(site, config)
    except Exception:
        pass

    placement_cfg = PlacementConfig(
        typology=params.get("typology", "AUTO"),
        courtyard_orientation=params.get("courtyard_orientation", "SOUTH"),
        cascade_floors=bool(params.get("cascade_floors", True)),
        asymmetric_wings=bool(params.get("asymmetric_wings", True)),
        max_sections_per_building=int(params.get("max_sections", 8)),
        urban_block_size=float(params.get("urban_block_size", 100.0)),
        internal_road_width=float(params.get("internal_road_width", 16.0)),
        perimeter_layout_style=params.get("perimeter_layout_style", "U_SHAPE"),
        max_bcr=config.get("max_bcr"),
        max_far=config.get("max_far"),
    )

    optimizer = Optimizer(site, library, config, base_placement_config=placement_cfg)
    variants = optimizer.generate_variants(floors_range=range(8, 26, 2))

    matrix = []
    for v in variants:
        matrix.append({
            "floors": v.floors,
            "buildings_count": v.tep.building_count,
            "gfa": round(v.tep.total_gfa),
            "residential_area": round(v.tep.residential_area),
            "apartments_total": v.tep.apartments_total,
            "bcr": round(v.tep.bcr * 100, 1),
            "far": round(v.tep.far, 2),
            "normative_ok": v.normative_ok,
        })
    return matrix


def export_file_dxf(output_path: Path) -> Path:
    """Экспорт DXF чертежа на основе последнего расчета."""
    site = _LAST_STATE["site"]
    buildings = _LAST_STATE["buildings"]
    tep = _LAST_STATE["tep"]
    if not site or not buildings:
        raise ValueError("Сначала выполните генерацию застройки")
    return export_dxf(site, buildings, tep, output_path, restore_cad_coords=True)


def export_file_3d_html(output_path: Path) -> Path:
    """Экспорт автономного 3D HTML файла."""
    site = _LAST_STATE["site"]
    buildings = _LAST_STATE["buildings"]
    tep = _LAST_STATE["tep"]
    if not site or not buildings:
        raise ValueError("Сначала выполните генерацию застройки")
    return export_3d_html(
        site, buildings, tep, output_path,
        title=f"3D-застройка: {site.cadastral_number or 'Участок'}",
        default_basemap="light"
    )


def export_file_geojson(output_path: Path) -> Path:
    """Экспорт GeoJSON файла."""
    site = _LAST_STATE["site"]
    buildings = _LAST_STATE["buildings"]
    tep = _LAST_STATE["tep"]
    if not site or not buildings:
        raise ValueError("Сначала выполните генерацию застройки")
    export_geojson(site, buildings, tep, output_path, as_wgs84=True)
    return output_path


def export_file_report(output_path: Path | None = None) -> str:
    """Экспорт текстового отчета по ТЭП."""
    site = _LAST_STATE["site"]
    buildings = _LAST_STATE["buildings"]
    tep = _LAST_STATE["tep"]
    config = _LAST_STATE["config"] or get_config()
    balance = _LAST_STATE["balance"]
    if not site or not buildings or not tep:
        raise ValueError("Сначала выполните генерацию застройки")
    return generate_report(site, buildings, tep, config, filepath=output_path, balance=balance)
