"""Streamlit-приложение: Генератор застройки по ТЭП.

Интерактивный интерфейс для настройки участка, выбора секций,
генерации расстановки и просмотра ТЭП.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml
import streamlit as st
import streamlit.components.v1 as components
import matplotlib.pyplot as plt

from src.core.site_parser import create_rectangular_site, parse_coordinates
from src.core.buildable_area import compute_buildable_area, get_obb_dimensions
from src.core.placement import PlacementConfig, PlacementEngine
from src.core.tep_calculator import calculate_tep, check_normatives, format_normative_check
from src.core.optimizer import Optimizer
from src.library.section_library import SectionLibrary
from src.models.tep import TEP
from src.visualization.plotter import plot_site_plan
from src.export.geojson_export import export_geojson
from src.export.report import generate_report
from src.core.regional_norms import load_regional_norms, RegionalNorm
from src.core.territory_balance import calculate_territory_balance, TerritoryBalanceResult
from src.core.cad_parser import inspect_cad_layers, parse_cad_site, DWGConversionError
from src.core.cadastre import (
    PRESET_PARCELS,
    get_cadastral_parcel,
    create_site_from_cadastre,
    validate_cadastral_number,
    parse_cadastral_components,
    resolve_cadastral_location,
    smart_resolve_location,
)
from src.core.geo_utils import (
    CITY_PRESETS,
    MSK_PRESETS,
    msk_to_wgs84_coords,
    detect_msk_by_coordinates,
    get_msk_key_for_region,
    geocode_address,
)
from src.visualization.map_view import generate_leaflet_map_html
from src.visualization.viewer_3d import generate_3d_viewer_html
from src.export.html_3d_export import export_3d_html
from src.export.dxf_export import export_dxf


# ─── Настройка страницы ──────────────────────────────────────────────

st.set_page_config(
    page_title="Генератор застройки по ТЭП",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Обработка интерактивной посадки с карты через параметры URL
if "map_lat" in st.query_params and "map_lon" in st.query_params:
    try:
        q_lat = float(st.query_params["map_lat"])
        q_lon = float(st.query_params["map_lon"])
        st.session_state["interactive_map_lat"] = q_lat
        st.session_state["interactive_map_lon"] = q_lon
        st.session_state["use_interactive_pos"] = True
        if "map_rot" in st.query_params:
            st.session_state["site_rotation"] = int(round(float(st.query_params["map_rot"])))
        st.query_params.clear()
    except Exception:
        pass

st.title("🏗️ Генератор застройки по ТЭП")
st.markdown("Расстановка типовых секций на участке с расчётом технико-экономических показателей")


# ─── Загрузка конфигурации ───────────────────────────────────────────

@st.cache_data
def load_config() -> dict:
    """Загрузить нормативные параметры."""
    config_path = PROJECT_ROOT / "config" / "defaults.yaml"
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@st.cache_resource
def load_library() -> SectionLibrary:
    """Загрузить библиотеку секций."""
    sections_dir = PROJECT_ROOT / "config" / "sections"
    return SectionLibrary(sections_dir)


config = load_config()
library = load_library()
regional_norms = load_regional_norms()


# ─── Боковая панель ──────────────────────────────────────────────────

st.sidebar.header("📐 Параметры участка")

site_mode = st.sidebar.radio(
    "Способ задания участка",
    [
        "1. По кадастровому номеру (с ручным поворотом)",
        "2. По чертежу DWG / DXF (с присвоением номера)",
    ],
    help="Выберите способ: по кадастровому номеру любого региона РФ или по файлу чертежа с привязкой к кадастровому номеру",
)

if site_mode == "1. По кадастровому номеру (с ручным поворотом)":
    # Быстрые пресеты по городам РФ для тестирования
    cad_quick_samples = {
        "63:01:0709002:2320 (Самара, пос. Зубчаниновка — 4.2 га)": "63:01:0709002:2320",
        "72:23:0222001:16187 (Тюмень, Алебашево — 4.4 га)": "72:23:0222001:16187",
        "63:01:0603003:54 (Самара, Промышленный — 3.5 га)": "63:01:0603003:54",
        "72:23:0216002:123 (Тюмень, Алебашево / Заречный — 3.3 га)": "72:23:0216002:123",
        "72:17:1707001:500 (Тюмень, д. Патрушева — 3.3 га)": "72:17:1707001:500",
        "72:17:0000000:100 (Тюмень, Московский тракт — 3.2 га)": "72:17:0000000:100",
        "22:63:010101:200 (Барнаул / Алтайский край — 3.2 га)": "22:63:010101:200",
        "77:17:0120316:1024 (Москва, Коммунарка — 3.6 га)": "77:17:0120316:1024",
        "78:34:0004286:115 (Санкт-Петербург, Приморский — 3.4 га)": "78:34:0004286:115",
        "50:27:0010101:500 (Московская обл., Подольск — 3.3 га)": "50:27:0010101:500",
        "23:43:0106012:450 (Краснодар, Зап. обход — 4.3 га)": "23:43:0106012:450",
        "66:41:0101001:500 (Екатеринбург, Академический)": "66:41:0101001:500",
        "16:50:010101:200 (Казань, Ново-Савиновский)": "16:50:010101:200",
        "(ввести свой номер вручную)": "",
    }

    if "cad_input_str" not in st.session_state:
        st.session_state["cad_input_str"] = "63:01:0709002:2320"

    def _on_cad_sample_select():
        sel = st.session_state.get("cad_sample_selector")
        if sel and sel in cad_quick_samples and cad_quick_samples[sel]:
            st.session_state["cad_input_str"] = cad_quick_samples[sel]

    sample_list = list(cad_quick_samples.keys())
    curr_input = st.session_state.get("cad_input_str", "63:01:0709002:2320")
    matching_idx = 0
    for idx, name in enumerate(sample_list):
        if cad_quick_samples[name] == curr_input:
            matching_idx = idx
            break

    st.sidebar.selectbox(
        "Примеры участков из каталога",
        sample_list,
        index=matching_idx,
        key="cad_sample_selector",
        on_change=_on_cad_sample_select,
        help="Выберите пример участка для быстрой загрузки",
    )

    entered_location = st.sidebar.text_input(
        "Кадастровый номер, адрес или координаты",
        key="cad_input_str",
        help="Введите кадастровый номер (72:23:0222001:16187), адрес ('Тюмень, Алебашево') или координаты WGS-84 ('57.1754, 65.5810')",
    )

    clean_query = entered_location.strip() or "63:01:0709002:2320"
    reg_name, dist_name, norm_id, auto_lat, auto_lon = smart_resolve_location(clean_query)
    st.session_state["cadastral_norm_id"] = norm_id

    # Экспандер для тонких настроек и прикрепления DXF
    with st.sidebar.expander("⚙️ Настройка площади и координат WGS-84", expanded=False):
        custom_area = st.number_input(
            "Площадь участка, м²",
            min_value=5000,
            max_value=300000,
            value=32000,
            step=1000,
            help="Используется для расчёта формы синтетического участка",
        )
        col_m1_lat, col_m1_lon = st.columns(2)
        override_lat = col_m1_lat.number_input(
            "Широта (Lat)", value=float(auto_lat), format="%.5f", step=0.0001, key="m1_override_lat"
        )
        override_lon = col_m1_lon.number_input(
            "Долгота (Lon)", value=float(auto_lon), format="%.5f", step=0.0001, key="m1_override_lon"
        )
        enable_red_line = st.checkbox(
            "Добавить красную линию (отступ УДС)",
            value=False,
            help="Включает красную линию вдоль южной границы участка.",
        )
        cad_override_file = st.file_uploader(
            "📎 Прикрепить контур из чертежа (.dxf, .dwg) — опционально",
            type=["dxf", "dwg"],
            key="cad_sub_uploader",
            help="Заменяет синтетический контур точной геометрией из чертежа",
        )

    use_lat = override_lat if override_lat != 0.0 else auto_lat
    use_lon = override_lon if override_lon != 0.0 else auto_lon

    try:
        parcel_info = get_cadastral_parcel(
            clean_query,
            custom_area_sqm=custom_area,
            override_lat=use_lat,
            override_lon=use_lon,
            add_red_line=enable_red_line,
        )
        site = create_site_from_cadastre(parcel_info)
        site.georef_source = f"По кадастровому номеру / адресу ({parcel_info.region_name})"

        if cad_override_file is not None:
            try:
                sub_bytes = cad_override_file.getvalue()
                sub_site, sub_meta = parse_cad_site(
                    sub_bytes,
                    filename=cad_override_file.name,
                    normalize_origin=True,
                )
                site.boundary = sub_site.boundary
                site.base_offset = sub_site.base_offset
                if sub_site.red_lines:
                    site.red_lines = sub_site.red_lines
                st.sidebar.caption(f"📐 Контур из чертежа `{cad_override_file.name}` ({site.area:,.0f} м²)")
            except Exception as e:
                st.sidebar.warning(f"Не удалось применить геометрию из CAD: {e}")

        st.session_state["cadastral_norm_id"] = parcel_info.regional_norm_id

        st.sidebar.success(
            f"✓ **{parcel_info.region_name}**\n\n*{parcel_info.district_name}*: {site.area:,.0f} м² ({site.area / 10000.0:.2f} га)"
        )
        st.sidebar.caption(f"📍 {parcel_info.address}")
        st.sidebar.markdown(
            f"[🌐 Проверить на Яндекс.Картах ↗](https://yandex.ru/maps/?pt={use_lon:.6f},{use_lat:.6f}&z=16&l=map)"
        )
        if site.red_lines:
            st.sidebar.caption(f"⛔ Красная линия УДС активна ({len(site.red_lines)} шт.)")

    except Exception as e:
        st.sidebar.error(f"Ошибка получения участка: {e}")
        site = create_rectangular_site(200, 150, geo_center=(use_lat, use_lon))
        site.address = f"{reg_name}, {dist_name} (демо-участок)"
        st.session_state["cadastral_norm_id"] = "russia_sp42"

else:
    # ─── 2. По чертежу DWG / DXF (с присвоением номера) ─────────────────
    cad_file = st.sidebar.file_uploader(
        "Загрузите чертёж границы (.dxf, .dwg)",
        type=["dxf", "dwg"],
        help="Загрузите чертёж генплана с контуром участка. DXF читается нативно, DWG конвертируется через ODA.",
    )

    dwg_quick_regions = {
        "Самара, пос. Зубчаниновка (63:01:0709002:2320)": "63:01:0709002:2320",
        "Тюмень, Алебашево (72:23:0222001:16187)": "72:23:0222001:16187",
        "Тюмень, Заречный / Алебашево (72:23:0216002:123)": "72:23:0216002:123",
        "Тюмень, д. Патрушева (72:17:1707001:500)": "72:17:1707001:500",
        "Тюмень, Московский тракт (72:17:0000000:100)": "72:17:0000000:100",
        "Барнаул / Алтайский край (22:63:010101:200)": "22:63:010101:200",
        "Москва, Коммунарка (77:17:0120316:1024)": "77:17:0120316:1024",
        "Санкт-Петербург, Приморский (78:34:0004286:115)": "78:34:0004286:115",
        "Московская обл., Подольск (50:27:0010101:500)": "50:27:0010101:500",
        "Краснодар, Зап. обход (23:43:0106012:450)": "23:43:0106012:450",
        "Екатеринбург, Академический (66:41:0101001:500)": "66:41:0101001:500",
        "Казань, Ново-Савиновский (16:50:010101:200)": "16:50:010101:200",
        "(ввести свой номер вручную)": "",
    }

    if "assigned_cad_number" not in st.session_state:
        st.session_state["assigned_cad_number"] = "63:01:0709002:2320"

    def _on_dwg_region_change():
        sel_r = st.session_state.get("dwg_region_selector")
        if sel_r and sel_r in dwg_quick_regions and dwg_quick_regions[sel_r]:
            st.session_state["assigned_cad_number"] = dwg_quick_regions[sel_r]

    curr_dwg_cad = st.session_state.get("assigned_cad_number", "63:01:0709002:2320")
    matched_dwg_idx = 0
    for idx, k in enumerate(dwg_quick_regions.keys()):
        if dwg_quick_regions[k] == curr_dwg_cad:
            matched_dwg_idx = idx
            break

    st.sidebar.selectbox(
        "Быстрый выбор региона привязки чертежа",
        list(dwg_quick_regions.keys()),
        index=matched_dwg_idx,
        key="dwg_region_selector",
        on_change=_on_dwg_region_change,
        help="Выберите регион для быстрой подстановки кадастрового номера",
    )

    assigned_location = st.sidebar.text_input(
        "Кадастровый номер, адрес или координаты",
        key="assigned_cad_number",
        help="Укажите кадастровый номер (72:23:0222001:16187), адрес ('Тюмень, Алебашево') или координаты WGS-84 ('57.1754, 65.5810')",
    )

    clean_dwg_query = assigned_location.strip() or "63:01:0709002:2320"
    reg_name, dist_name, norm_id, c_lat, c_lon = smart_resolve_location(clean_dwg_query)
    st.session_state["cadastral_norm_id"] = norm_id

    if cad_file is not None:
        try:
            file_bytes = cad_file.getvalue()
            layers_info = inspect_cad_layers(file_bytes, cad_file.name)
            if not layers_info:
                st.sidebar.error("В чертеже не найдено геометрических линий или полилиний.")
                st.stop()

            layer_names = [l.name for l in layers_info]
            cand_idx = next((i for i, l in enumerate(layers_info) if l.is_candidate), 0)

            # Экспандер настроек слоев и ручной посадки
            with st.sidebar.expander("⚙️ Настройки слоёв и ручная корректировка", expanded=False):
                sel_layer = st.selectbox(
                    "Слой границы участка",
                    layer_names,
                    index=cand_idx,
                    help="Слой CAD с внешним контуром границы",
                )
                rl_names = ["(нет)"] + layer_names
                rl_cand_idx = 0
                for idx, l in enumerate(layers_info):
                    if l.is_red_line_candidate and l.name != sel_layer:
                        rl_cand_idx = idx + 1
                        break
                sel_rl = st.selectbox("Слой красных линий", rl_names, index=rl_cand_idx)
                rl_param = None if sel_rl == "(нет)" else sel_rl

                col_rw1, col_rw2 = st.columns(2)
                manual_lat = col_rw1.number_input(
                    "Широта (Lat)", value=0.0, format="%.5f", step=0.0001,
                    help="Оставьте 0.0 для автопосадки по чертежу/кадастру",
                )
                manual_lon = col_rw2.number_input(
                    "Долгота (Lon)", value=0.0, format="%.5f", step=0.0001,
                    help="Оставьте 0.0 для автопосадки по чертежу/кадастру",
                )

            site, cad_meta = parse_cad_site(
                file_bytes,
                filename=cad_file.name,
                boundary_layer=sel_layer,
                red_lines_layer=rl_param,
                normalize_origin=True,
            )

            comps = parse_cadastral_components(clean_dwg_query)
            site.cadastral_number = comps["formatted"] if comps else clean_dwg_query
            site.address = f"{reg_name}, {dist_name} (чертёж: {cad_file.name})"

            # Проверяем, содержит ли чертёж геодезические координаты (МСК)
            is_msk = abs(site.base_offset[0]) > 500 or abs(site.base_offset[1]) > 500
            cad_lat, cad_lon = None, None
            detected_msk = None
            dist_km = 0.0

            if is_msk:
                reg_code = comps["region_code"] if comps else "63"
                detected_msk = get_msk_key_for_region(reg_code, site.base_offset[0], site.base_offset[1])
                if not detected_msk:
                    detected_msk = detect_msk_by_coordinates(site.base_offset[0], site.base_offset[1])
                if not detected_msk:
                    detected_msk = "МСК-72 Зона 1 (Тюмень)" if reg_code == "72" else "МСК-63 Зона 1 (Самара)"

                target_center = (c_lat, c_lon)
                cad_lat, cad_lon = msk_to_wgs84_coords(
                    site.base_offset[0],
                    site.base_offset[1],
                    detected_msk,
                    axis_order="auto",
                    expected_center=target_center,
                )
                cos_lat = math.cos(math.radians(c_lat))
                dist_km = math.sqrt(((cad_lat - c_lat) * 111.0) ** 2 + ((cad_lon - c_lon) * 111.0 * cos_lat) ** 2)

            # Выбор точки посадки на карту
            if manual_lat != 0.0 and manual_lon != 0.0:
                site.geo_center = (manual_lat, manual_lon)
                site.georef_source = "Ручные координаты"
                pos_desc = f"✏️ Ручные координаты: `[{manual_lat:.5f}, {manual_lon:.5f}]`"
            elif is_msk and cad_lat is not None and cad_lon is not None:
                opt_cadastre = f"📍 По кадастру/адресу: [{c_lat:.5f}, {c_lon:.5f}]"
                opt_cad = f"🛰️ По координатам чертежа ({detected_msk}): [{cad_lat:.5f}, {cad_lon:.5f}]"
                georef_options = [opt_cadastre, opt_cad]

                # Если координаты чертежа расходятся с кадастровым районом более чем на 15 км —
                # по умолчанию выбираем кадастр, чтобы участок не улетал в поле/другой район!
                default_idx = 0 if dist_km > 15.0 else 1

                if dist_km > 15.0:
                    st.sidebar.warning(
                        f"⚠️ Координаты в файле чертежа расходятся с выбранным адресом/кадастром ({dist_name}) на {dist_km:.0f} км. "
                        "По умолчанию участок посажен по кадастровому номеру."
                    )

                chosen_georef = st.sidebar.radio(
                    "📍 Посадка участка на карту:",
                    georef_options,
                    index=default_idx,
                    key="cad_georef_choice",
                    help="Выберите, куда посадить контур: в район кадастрового номера или по абсолютным координатам МСК из чертежа",
                )

                if chosen_georef == opt_cadastre:
                    site.geo_center = (c_lat, c_lon)
                    site.georef_source = f"По кадастру/адресу ({dist_name})"
                    pos_desc = f"📍 По кадастру/адресу: `[{c_lat:.5f}, {c_lon:.5f}]`"
                else:
                    site.geo_center = (cad_lat, cad_lon)
                    site.georef_source = f"По координатам чертежа ({detected_msk})"
                    pos_desc = f"🛰️ По чертежу ({detected_msk}): `[{cad_lat:.5f}, {cad_lon:.5f}]`"
            else:
                site.geo_center = (c_lat, c_lon)
                site.georef_source = f"По кадастру/адресу ({dist_name})"
                pos_desc = f"📍 По кадастру/адресу ({dist_name}): `[{c_lat:.5f}, {c_lon:.5f}]`"

            st.sidebar.success(
                f"✓ **{site.area:,.0f} м²** ({site.area / 10000.0:.2f} га)\n\n"
                f"{pos_desc}"
            )
            st.sidebar.markdown(
                f"[🌐 Проверить на Яндекс.Картах ↗](https://yandex.ru/maps/?pt={site.geo_center[1]:.6f},{site.geo_center[0]:.6f}&z=16&l=map)"
            )
            if cad_meta["red_lines_count"] > 0:
                st.sidebar.caption(f"⛔ Красных линий: {cad_meta['red_lines_count']} шт.")
            st.sidebar.caption(f"🏛️ Нормативы: **{reg_name}** ({dist_name})")

        except DWGConversionError as e:
            st.sidebar.warning(str(e))
            st.sidebar.info("💡 Сохраните чертеж в AutoCAD/nanoCAD в формат DXF (`DXFOUT`) и загрузите .dxf файл.")
            st.stop()
        except Exception as e:
            st.sidebar.error(f"Ошибка обработки CAD файла: {e}")
            st.stop()
    else:
        st.sidebar.info("Загрузите чертёж границы участка (.dxf или .dwg).")
        st.sidebar.caption("💡 Совет: команда `DXFOUT` в AutoCAD или «Сохранить как → DXF».")
        try:
            parcel_info = get_cadastral_parcel(clean_dwg_query)
            site = create_site_from_cadastre(parcel_info)
            site.cadastral_number = parcel_info.cadastral_number
            site.address = parcel_info.address
            site.georef_source = f"По кадастровому номеру ({parcel_info.district_name})"
            if parcel_info.source == "preset":
                st.sidebar.success(
                    f"✓ Контур участка загружен по кадастру: **{site.area:,.0f} м²** ({site.area / 10000.0:.2f} га)"
                )
            else:
                st.sidebar.caption(f"📍 Контур по району: **{reg_name} ({dist_name})** `[{c_lat:.5f}, {c_lon:.5f}]`")
        except Exception:
            site = create_rectangular_site(200, 150, geo_center=(c_lat, c_lon))
            site.cadastral_number = clean_dwg_query
            site.address = f"{reg_name}, {dist_name} (демо-участок)"
            site.georef_source = f"По кадастровому номеру / адресу ({dist_name})"

        st.sidebar.markdown(
            f"[🌐 Проверить на Яндекс.Картах ↗](https://yandex.ru/maps/?pt={c_lon:.6f},{c_lat:.6f}&z=16&l=map)"
        )
        st.sidebar.caption(f"📍 Центр участка: **{reg_name} ({dist_name})** `[{c_lat:.5f}, {c_lon:.5f}]`")

st.sidebar.markdown(f"**Площадь участка:** {site.area:,.0f} м²")

# ─── Интерактивная посадка и микро-выравнивание на карте ───────────────
st.sidebar.subheader("🎯 Посадка и выравнивание на карте")

if "interactive_map_lat" in st.session_state:
    inter_lat = st.session_state["interactive_map_lat"]
    inter_lon = st.session_state["interactive_map_lon"]
    st.sidebar.success(f"📍 Положение с карты:\n`[{inter_lat:.6f}, {inter_lon:.6f}]`")
    site.geo_center = (inter_lat, inter_lon)
    site.georef_source = f"Интерактивно на карте `[{inter_lat:.6f}, {inter_lon:.6f}]`"
    if st.sidebar.button("↺ Сбросить к исходным координатам", key="btn_reset_inter_pt", use_container_width=True):
        del st.session_state["interactive_map_lat"]
        del st.session_state["interactive_map_lon"]
        st.session_state["use_interactive_pos"] = False
        st.session_state["site_rotation"] = 0
        st.rerun()
else:
    st.sidebar.info(
        "💡 **Прямое выравнивание на карте:**\n"
        "Зажмите контур участка мышью и перетащите его. "
        "Крутите за верхний круглый маркер для поворота."
    )
# ─── Ориентация участка и стороны света ──────────────────────────────
st.sidebar.subheader("🧭 Ориентация участка и стороны света")

cardinal_presets = {
    "(произвольный угол)": None,
    "Юг (0° - строго по меридиану)": 0,
    "Юго-Восток (45°)": 45,
    "Восток (90°)": 90,
    "Северо-Восток (135°)": 135,
    "Север (180°)": 180,
    "Северо-Запад (-135°)": -135,
    "Запад (-90°)": -90,
    "Юго-Запад (-45°)": -45,
}

if "site_rotation" not in st.session_state:
    st.session_state["site_rotation"] = 0

def _on_cardinal_select():
    sel = st.session_state.get("sel_cardinal_widget")
    if sel and sel in cardinal_presets and cardinal_presets[sel] is not None:
        st.session_state["site_rotation"] = cardinal_presets[sel]

st.sidebar.selectbox(
    "Назначить ориентацию фасада / улицы",
    list(cardinal_presets.keys()),
    index=0,
    key="sel_cardinal_widget",
    on_change=_on_cardinal_select,
    help="Быстро назначить ориентацию главного фасада участка по сторонам света (истинному северу)",
)

rot_btn1, rot_btn2, rot_btn3, rot_btn4 = st.sidebar.columns(4)
current_rot = int(st.session_state.get("site_rotation", 0))

if rot_btn1.button("↺ -15°", use_container_width=True, help="Повернуть против часовой стрелки на 15°"):
    st.session_state["site_rotation"] = current_rot - 15
    st.rerun()

if rot_btn2.button("↺ -5°", use_container_width=True, help="Повернуть против часовой стрелки на 5°"):
    st.session_state["site_rotation"] = current_rot - 5
    st.rerun()

if rot_btn3.button("↻ +5°", use_container_width=True, help="Повернуть по часовой стрелке на 5°"):
    st.session_state["site_rotation"] = current_rot + 5
    st.rerun()

if rot_btn4.button("↻ +15°", use_container_width=True, help="Повернуть по часовой стрелке на 15°"):
    st.session_state["site_rotation"] = current_rot + 15
    st.rerun()

col_rot_s, col_rot_n = st.sidebar.columns([3, 2])
site_rot_val = col_rot_s.slider(
    "Точный угол к северу, °",
    min_value=-180,
    max_value=180,
    value=int(st.session_state.get("site_rotation", 0)),
    step=1,
    help="Поверните участок, чтобы состыковать его границу с направлением улиц, дорог и кварталов на карте OSM",
)
st.session_state["site_rotation"] = site_rot_val

if site_rot_val != 0:
    site.rotate(float(site_rot_val))

# Индикация азимута главной оси участка
from src.core.buildable_area import get_primary_axes
p_axis, _ = get_primary_axes(site.boundary)
col_rot_n.metric("Азимут оси", f"{p_axis:.0f}°")

if site_rot_val != 0 and st.sidebar.button("Сбросить поворот (0°)", use_container_width=True):
    st.session_state["site_rotation"] = 0
    st.rerun()

st.sidebar.caption("💡 *При загрузке чертежа DXF или вставке координат ЕГРН истинный север и форма считываются автоматически.*")

# ─── Градостроительные нормативы ─────────────────────────────────────

st.sidebar.header("📏 Градостроительные нормативы")

region_ids = list(regional_norms.keys())
region_labels = {k: v.name for k, v in regional_norms.items()}
default_reg_idx = 0
target_norm_id = st.session_state.get("cadastral_norm_id")
if target_norm_id and target_norm_id in region_ids:
    default_reg_idx = region_ids.index(target_norm_id)

selected_region_id = st.sidebar.selectbox(
    "Региональные нормативы (РНГП / МНГП)",
    region_ids,
    index=default_reg_idx,
    format_func=lambda x: region_labels.get(x, x),
    help="Определяет требования к парковкам, детским и спортивным площадкам по региональным градостроительным нормам",
)
selected_norm = regional_norms[selected_region_id]
st.sidebar.caption(f"📌 {selected_norm.description}")

config["boundary_setback"] = st.sidebar.slider(
    "Отступ от границы, м", 0, 20, int(config.get("boundary_setback", 6))
)
config["fire_gap_min"] = st.sidebar.slider(
    "Пожарный разрыв (мин.), м", 3, 30, int(config.get("fire_gap_min", 6))
)
config["fire_gap_high_rise"] = st.sidebar.slider(
    "Пожарный разрыв (выс.), м", 6, 50, int(config.get("fire_gap_high_rise", 15))
)
config["insolation_factor"] = st.sidebar.slider(
    "Коэфф. инсоляции", 0.1, 1.5, float(config.get("insolation_factor", 0.5)), 0.1
)
config["max_bcr"] = st.sidebar.slider(
    "Макс. % застройки (КЗ)", 0.1, 0.8, float(selected_norm.density.max_bcr), 0.05
)
config["max_far"] = st.sidebar.slider(
    "Макс. плотность (FAR)", 0.5, 5.0, float(selected_norm.density.max_far), 0.1
)
config["green_ratio_min"] = float(selected_norm.density.green_ratio_min)

# ─── Параметры генерации ─────────────────────────────────────────────

st.sidebar.header("🏛️ Архитектурно-градостроительная концепция")

typology_choice = st.sidebar.selectbox(
    "Типология застройки",
    [
        "Квартальная / Смешанная (AUTO)",
        "Точечная / Башенная (Towers)",
        "П-образные дворы (U-Shape)",
        "Г-образные корпуса (L-Shape)",
        "Линейная застройка (Пластины)",
    ],
    help="Выберите градостроительный тип застройки участка",
)
typology_map = {
    "Квартальная / Смешанная (AUTO)": "AUTO",
    "Точечная / Башенная (Towers)": "TOWER",
    "П-образные дворы (U-Shape)": "U_SHAPE",
    "Г-образные корпуса (L-Shape)": "L_SHAPE",
    "Линейная застройка (Пластины)": "LINEAR",
}
typology_val = typology_map[typology_choice]

allow_towers_in_mixed = True
if typology_val == "AUTO":
    allow_towers_in_mixed = st.sidebar.checkbox(
        "Размещать башни-акценты на флангах",
        value=True,
        help="Разрешить размещение компактных башенных секций на свободных флангах в смешанной застройке",
    )

court_orient_choice = st.sidebar.selectbox(
    "Ориентация дворов",
    [
        "На Юг (макс. инсоляция)",
        "По оси участка (AUTO)",
        "На Восток",
        "На Запад",
        "На Север",
    ],
    help="Сторона света, в которую раскрываются дворы для лучшего освещения солнцем",
)
court_orient_map = {
    "На Юг (макс. инсоляция)": "SOUTH",
    "По оси участка (AUTO)": "AUTO",
    "На Восток": "EAST",
    "На Запад": "WEST",
    "На Север": "NORTH",
}
court_orient_val = court_orient_map[court_orient_choice]

var_insolation = st.sidebar.checkbox(
    "Переменный шаг инсоляции",
    value=True,
    help="Сокращает противопожарный разрыв с глухих торцов, освобождая место для просторных дворов",
)

st.sidebar.header("⚙️ Параметры генерации")

available_sections = library.get_all()
section_names = {s.id: f"{s.name} ({s.width}×{s.depth}м)" for s in available_sections}

with st.sidebar.expander("📦 Предпочтительные секции", expanded=False):
    pref_section_ids = st.multiselect(
        "Использовать типы секций:",
        options=list(section_names.keys()),
        default=[],
        format_func=lambda sid: f"{section_names.get(sid, sid)} [{getattr(library.get_by_id(sid), 'category', '')}]",
        help="Оставьте пустым для автоматического выбора оптимальных секций движком",
    )

gen_mode = st.sidebar.radio(
    "Режим генерации",
    ["Заданная этажность", "Подбор под ТЭП", "Максимизация"],
    help=(
        "• Заданная этажность — фиксированная этажность\n"
        "• Подбор под ТЭП — автоматический подбор этажности\n"
        "• Максимизация — максимум площади при соблюдении нормативов"
    ),
)

target_floors = 17
target_tep = {}

if gen_mode == "Заданная этажность":
    target_floors = st.sidebar.slider("Этажность", 3, 30, 17)
elif gen_mode == "Подбор под ТЭП":
    target_metric = st.sidebar.selectbox(
        "Целевой показатель",
        ["Плотность (FAR)", "Количество квартир", "Общая площадь (GFA)"],
    )
    if target_metric == "Плотность (FAR)":
        target_tep["target_far"] = st.sidebar.number_input(
            "Целевой FAR", 0.5, 5.0, 1.5, 0.1
        )
    elif target_metric == "Количество квартир":
        target_tep["target_apartments"] = st.sidebar.number_input(
            "Целевое кол-во квартир", 50, 5000, 500, 50
        )
    else:
        target_tep["target_gfa"] = st.sidebar.number_input(
            "Целевая GFA, м²", 5000, 500000, 50000, 5000
        )
elif gen_mode == "Максимизация":
    respect_norms = st.sidebar.checkbox(
        "Соблюдать нормативы плотности (FAR / BCR)",
        value=True,
        help="Если включено — этажность подбирается так, чтобы плотность застройки не превышала норматив (СП 42.13330 / РНГП). Если выключено — абсолютная максимизация площади без ограничений.",
    )
    explore_all_typs = st.sidebar.checkbox(
        "Сравнивать все типологии застройки",
        value=False,
        help="Автоматически протестирует все типы застройки (квартальная, линейная, Г- и П-образная) и выберет самую вместительную",
    )

max_sections = st.sidebar.slider(
    "Макс. секций в здании", 2, 12, 8,
    help="Максимальное количество секций в одном здании",
)

st.sidebar.subheader("🏙️ Пластика и разноэтажность")
cascade_floors = st.sidebar.checkbox(
    "Понижение этажности к югу",
    value=True,
    help="Северные секции повышенной этажности, южные крылья каскадно спускаются до 7–9 эт. для инсоляции дворов",
)
asymmetric_wings = st.sidebar.checkbox(
    "Асимметричные крылья",
    value=True,
    help="Разная длина крыльев у П- и Г-образных скоб для живой урбанистической композиции",
)
min_wing_fl = 8
if cascade_floors:
    min_wing_fl = st.sidebar.slider("Этажность южных торцов", 5, 10, 8)

st.sidebar.subheader("📏 Высотность и этажи")
col_h1, col_h2 = st.sidebar.columns(2)
with col_h1:
    floor_height_val = st.number_input(
        "Высота этажа (м)",
        min_value=2.5,
        max_value=5.0,
        value=float(config.get("floor_height", 3.0)),
        step=0.1,
        help="Высота типового этажа (от пола до пола) для расчета высоты здания, строительного объема и инсоляции",
    )
with col_h2:
    max_height_val = st.number_input(
        "Макс. высота (м)",
        min_value=0.0,
        max_value=200.0,
        value=float(config.get("max_building_height_m", 0.0) or 0.0),
        step=1.0,
        help="Предельная высота здания в метрах (по ПЗЗ/ГПЗУ). 0 — без ограничения.",
    )

if max_height_val > 0.0:
    max_floors_allowed = max(1, int(max_height_val // floor_height_val))
    st.sidebar.caption(
        f"📐 Лимит по высоте: **не более {max_floors_allowed} эт.** "
        f"({max_height_val:.1f} м при h_эт={floor_height_val:.2f} м)"
    )
    if target_floors > max_floors_allowed:
        target_floors = max_floors_allowed

config["floor_height"] = floor_height_val
config["max_building_height_m"] = max_height_val if max_height_val > 0.0 else None


# ─── Генерация ───────────────────────────────────────────────────────

generate_btn = st.sidebar.button("🚀 Сгенерировать", type="primary", use_container_width=True)

# Формируем уникальный отпечаток текущего состояния участка
active_query = clean_query if site_mode.startswith("1") else clean_dwg_query
site_fingerprint = (
    site_mode,
    str(site.cadastral_number),
    active_query,
    round(site.area, 1),
    tuple(round(c, 5) for c in (site.geo_center or (0.0, 0.0))),
    site.address,
    tuple(round(b, 2) for b in site.boundary.bounds),
    site.rotation_deg,
)
site_has_changed = (
    "last_site_fingerprint" in st.session_state
    and st.session_state["last_site_fingerprint"] != site_fingerprint
)

if generate_btn or ("buildings" not in st.session_state) or site_has_changed:
    st.session_state["last_site_fingerprint"] = site_fingerprint
    with st.spinner("Генерация расстановки..."):
        # 1. Вычисляем зону застройки
        try:
            compute_buildable_area(site, config)
        except ValueError as e:
            st.error(f"Ошибка: {e}")
            st.stop()

        # 2. Генерация
        try:
            placement_cfg = PlacementConfig(
                target_floors=target_floors,
                max_sections_per_building=max_sections,
                typology=typology_val,
                courtyard_orientation=court_orient_val,
                variable_insolation=var_insolation,
                cascade_floors=cascade_floors,
                asymmetric_wings=asymmetric_wings,
                min_wing_floors=min_wing_fl,
                floor_height=floor_height_val,
                max_building_height_m=max_height_val if max_height_val > 0.0 else None,
                preferred_section_ids=pref_section_ids if pref_section_ids else None,
                allow_towers_in_mixed=allow_towers_in_mixed,
            )

            if gen_mode == "Заданная этажность":
                engine = PlacementEngine(site, library, config)
                buildings = engine.generate(placement_cfg)
                tep = calculate_tep(site, buildings, config)

            elif gen_mode == "Подбор под ТЭП":
                optimizer = Optimizer(site, library, config, base_placement_config=placement_cfg)
                result = optimizer.optimize_for_target(target_tep)
                buildings = result.buildings
                tep = result.tep

            elif gen_mode == "Максимизация":
                optimizer = Optimizer(site, library, config, base_placement_config=placement_cfg)
                result = optimizer.optimize_maximize(
                    respect_normatives=respect_norms,
                    explore_typologies=explore_all_typs,
                )
                buildings = result.buildings
                tep = result.tep
                optimization_note = result.note

        except Exception as e:
            st.error(f"Ошибка генерации: {e}")
            import traceback
            st.code(traceback.format_exc())
            st.stop()

        if not buildings:
            st.warning("Не удалось разместить ни одного здания. "
                       "Попробуйте увеличить участок или уменьшить отступы.")
            st.stop()

        # 3. Баланс территории по региональным нормативам
        balance = calculate_territory_balance(
            site_area=site.area,
            building_footprint_area=tep.building_area,
            population=tep.population,
            residential_area=tep.residential_area,
            apartments_total=tep.apartments_total,
            regional_norm=selected_norm,
        )

        # Сохраняем в session state
        st.session_state["buildings"] = buildings
        st.session_state["tep"] = tep
        st.session_state["site"] = site
        st.session_state["config"] = config
        st.session_state["balance"] = balance
        st.session_state["selected_norm"] = selected_norm
        st.session_state["gen_mode"] = gen_mode
        st.session_state["optimization_note"] = optimization_note if gen_mode == "Максимизация" else ""


# ─── Отображение результатов ─────────────────────────────────────────

if "buildings" in st.session_state:
    buildings = st.session_state["buildings"]
    tep = st.session_state["tep"]
    st.session_state["site"] = site

    # Пояснительные баннеры режима расчёта
    current_mode = st.session_state.get("gen_mode", "")
    if current_mode == "Максимизация":
        note = st.session_state.get("optimization_note", "")
        if note:
            if "Внимание" in note or "без лимитов" in note:
                st.warning(f"⚠️ **Режим максимизации:** {note}")
            else:
                st.info(f"💡 **Режим максимизации:** {note}")
    elif current_mode == "Заданная этажность":
        checks = check_normatives(tep, st.session_state["config"])
        violations = [
            f"{c['name']} ({c['value']:.2f} > {c['limit']:.2f})"
            for c in checks.values()
            if not c["ok"] and c["name"] in ("Плотность застройки", "Процент застройки")
        ]
        if violations:
            st.warning(
                f"⚠️ **Внимание: в режиме 'Заданная этажность' превышены нормативы:** {', '.join(violations)}. "
                f"В режиме 'Максимизация' генератор автоматически подбирает этажность для строгого соблюдения этих лимитов."
            )

    # Две колонки: план и ТЭП
    col_plan, col_tep = st.columns([2, 1])

    with col_plan:
        st.subheader("🗺️ План застройки")
        map_tab1, map_tab2, map_tab3 = st.tabs([
            "🗺️ 2D Подложка OSM",
            "📐 2D Генплан (Схема)",
            "🛰️ Сведения о геопривязке",
        ])

        with map_tab1:
            col_mhdr1, col_mhdr2 = st.columns([3, 1])
            with col_mhdr2:
                show_sections_osm = st.toggle(
                    "🧱 Показывать секции",
                    value=st.session_state.get("show_sections_osm", True),
                    key="tog_show_sections_osm",
                    help="Включить / отключить потиповое отображение секций на подложке карты",
                )
                st.session_state["show_sections_osm"] = show_sections_osm

            map_html = generate_leaflet_map_html(site, buildings, tep, height=580, show_sections=show_sections_osm)
            components.html(map_html, height=600)
            st.caption(
                "💡 **Интерактивная посадка и выравнивание (Figma / AutoCAD стиль):** "
                "Зажмите мышью **сам контур участка** и переместите его по спутнику или схеме улиц. "
                "За **оранжевый круглый маркер сверху** поверните участок вдоль улицы или красной линии. "
                "В появившейся плашке нажмите **«💾 Применить»**, чтобы зафиксировать координаты и пересчитать застройку. "
                "Слой секций также можно переключать в меню слоёв в правом верхнем углу карты."
            )

        with map_tab2:
            col_ghdr1, col_ghdr2 = st.columns([3, 1])
            with col_ghdr2:
                show_sections_gp = st.toggle(
                    "🧱 Показывать секции",
                    value=st.session_state.get("show_sections_gp", True),
                    key="tog_show_sections_gp",
                    help="Включить / отключить потиповое отображение секций на генплане",
                )
                st.session_state["show_sections_gp"] = show_sections_gp

            fig = plot_site_plan(site, buildings, tep, show_sections=show_sections_gp)
            st.pyplot(fig)
            plt.close(fig)

        with map_tab3:
            st.markdown(f"**Кадастровый номер:** `{site.cadastral_number or 'Не задан'}`")
            if site.geo_center:
                st.markdown(f"**Координаты центра (WGS-84):** `{site.geo_center[0]:.6f}, {site.geo_center[1]:.6f}`")
            georef_src = getattr(site, "georef_source", "")
            if georef_src:
                st.markdown(f"**Способ геопривязки:** {georef_src}")
            if site.address:
                st.markdown(f"**Ориентир / Адрес:** {site.address}")
            if site.base_offset and (abs(site.base_offset[0]) > 0.1 or abs(site.base_offset[1]) > 0.1):
                st.markdown(f"**Смещение в чертеже (CAD Offset):** `X = {site.base_offset[0]:,.1f} м, Y = {site.base_offset[1]:,.1f} м`")
            st.markdown(f"**Площадь участка:** {site.area:,.1f} м² ({site.area / 10000.0:.2f} га)")
            if site.buildable_area:
                st.markdown(f"**Площадь зоны застройки:** {site.buildable_area.area:,.1f} м² ({site.buildable_area.area / 10000.0:.2f} га)")
            if site.red_lines:
                st.markdown(f"**Красных линий (УДС):** {len(site.red_lines)} шт.")

            st.divider()
            if site.geo_center:
                c_lat, c_lon = site.geo_center
                col_lnk1, col_lnk2 = st.columns(2)
                col_lnk1.markdown(f"[🌐 Открыть на Яндекс.Картах ↗](https://yandex.ru/maps/?pt={c_lon:.6f},{c_lat:.6f}&z=16&l=map)")
                col_lnk2.markdown(f"[🗺️ Публичная кадастровая карта (ПКК) ↗](https://pkk.rosreestr.ru/#/search/{c_lat:.6f},{c_lon:.6f}/16)")

    with col_tep:
        st.subheader("📊 Технико-экономические показатели")

        # ТЭП в таблице
        tep_dict = tep.to_dict()
        for key, value in tep_dict.items():
            if isinstance(value, float):
                if value < 1:
                    st.metric(key, f"{value:.1%}")
                else:
                    st.metric(key, f"{value:,.1f}")
            else:
                st.metric(key, f"{value}")

    # Проверка нормативов
    st.subheader("✅ Проверка нормативов")
    checks = check_normatives(tep, st.session_state["config"])

    check_cols = st.columns(len(checks))
    for col, (key, check) in zip(check_cols, checks.items()):
        with col:
            icon = "✅" if check["ok"] else "❌"
            if check["unit"] == "%":
                val_str = f"{check['value']:.1%}"
                lim_str = f"≤ {check['limit']:.0%}" if key != "green_ratio" else f"≥ {check['limit']:.0%}"
            else:
                val_str = f"{check['value']:.2f}"
                lim_str = f"≤ {check['limit']:.1f}"
            st.metric(f"{icon} {check['name']}", val_str, lim_str)

    # Баланс территории и машиномест по региональным нормативам
    if "balance" in st.session_state:
        balance: TerritoryBalanceResult = st.session_state["balance"]
        st.subheader(f"🏛️ Баланс территории и машиномест ({balance.regional_norm_name})")

        # Особые предупреждения
        for w in balance.warnings:
            if "подземный" in w.lower():
                st.info(f"🚗 {w}")
            else:
                st.warning(f"⚠️ {w}")

        # Карточки парковок
        st.markdown("**Обеспеченность автостоянками:**")
        p_col1, p_col2, p_col3 = st.columns(3)
        with p_col1:
            st.metric(
                "Требуется по нормативу",
                f"{balance.parking.required_total} м/м",
                f"в т.ч. гостевых: {balance.parking.required_guest} м/м",
            )
        with p_col2:
            st.metric(
                "Наземная емкость на участке",
                f"{balance.parking.ground_capacity} м/м",
                f"{balance.parking.ground_area:,.0f} м² открытых стоянок",
            )
        with p_col3:
            deficit_text = f"{balance.parking.underground_deficit} м/м"
            deficit_delta = (
                f"Требуется ~{balance.parking.underground_area_est:,.0f} м²"
                if balance.parking.underground_deficit > 0
                else "Дефицита нет"
            )
            st.metric(
                "Дефицит в подземный паркинг",
                deficit_text,
                deficit_delta,
                delta_color="inverse" if balance.parking.underground_deficit > 0 else "normal",
            )

        # Дворовые площадки
        st.markdown("**Обязательные дворовые площадки (м²):**")
        pl_c1, pl_c2, pl_c3, pl_c4, pl_c5 = st.columns(5)
        with pl_c1:
            st.metric("Детские игровые", f"{balance.playgrounds.children:,.0f} м²")
        with pl_c2:
            st.metric("Спортивные", f"{balance.playgrounds.sport:,.0f} м²")
        with pl_c3:
            st.metric("Отдых взрослых", f"{balance.playgrounds.relax:,.0f} м²")
        with pl_c4:
            st.metric("Хоз. цели и ТКО", f"{balance.playgrounds.utility + balance.playgrounds.waste:,.0f} м²")
        with pl_c5:
            st.metric("Всего площадок", f"{balance.playgrounds.total:,.0f} м²")

        # Структура использования земельного участка
        with st.expander("📊 Детализация баланса площади земельного участка"):
            shares = balance.get_structure_shares()
            cols = st.columns(len(shares))
            for col, (item_name, share_val) in zip(cols, shares.items()):
                with col:
                    st.metric(item_name, f"{share_val:.1f}%")

    # Квартирография
    st.subheader("🏠 Квартирография")

    apt_data = []
    for i, building in enumerate(buildings):
        apts = building.total_apartments
        fl_str = f"{building.floors}" if building.min_floors == building.floors else f"{building.min_floors}–{building.floors}"
        apt_data.append({
            "Дом": f"Д{i + 1}",
            "Этажность": fl_str,
            "Секций": len(building.sections),
            "Студии": apts.get("studio", 0),
            "1-комн.": apts.get("1k", 0),
            "2-комн.": apts.get("2k", 0),
            "3-комн.": apts.get("3k", 0),
            "4-комн.": apts.get("4k", 0),
            "Всего кв.": sum(apts.values()),
            "GFA, м²": f"{building.total_gfa:,.0f}",
        })

    st.table(apt_data)

    # Сравнение вариантов
    with st.expander("📋 Варианты по этажности"):
        if st.button("Сгенерировать сравнение"):
            with st.spinner("Генерация вариантов..."):
                if site.buildable_area is None:
                    compute_buildable_area(site, st.session_state["config"])
                optimizer = Optimizer(
                    site, library, st.session_state["config"],
                    base_placement_config=PlacementConfig(
                        typology=typology_val,
                        courtyard_orientation=court_orient_val,
                        variable_insolation=var_insolation,
                        cascade_floors=cascade_floors,
                        asymmetric_wings=asymmetric_wings,
                        min_wing_floors=min_wing_fl,
                        max_sections_per_building=max_sections,
                        preferred_section_ids=pref_section_ids if pref_section_ids else None,
                        allow_towers_in_mixed=allow_towers_in_mixed,
                    )
                )
                variants = optimizer.generate_variants()

                if variants:
                    var_data = []
                    for v in variants:
                        var_data.append({
                            "Этажность": v.floors,
                            "Зданий": v.tep.building_count,
                            "GFA, м²": f"{v.tep.total_gfa:,.0f}",
                            "Жил.пл., м²": f"{v.tep.residential_area:,.0f}",
                            "Квартир": v.tep.apartments_total,
                            "BCR": f"{v.tep.bcr:.0%}",
                            "FAR": f"{v.tep.far:.2f}",
                            "Нормативы": "✅" if v.normative_ok else "❌",
                        })
                    st.table(var_data)

    # Экспорт
    st.subheader("📥 Экспорт")
    col_exp1, col_exp2, col_exp3, col_exp4 = st.columns(4)

    with col_exp1:
        if st.button("📐 Скачать DXF (AutoCAD)", use_container_width=True):
            export_path_dxf = PROJECT_ROOT / "output" / "plan_cad.dxf"
            export_dxf(
                site=site,
                buildings=buildings,
                tep=tep,
                filepath=export_path_dxf,
                restore_cad_coords=True,
            )
            st.success(f"Сохранено: {export_path_dxf.name}")
            with open(export_path_dxf, "rb") as f_dxf:
                st.download_button(
                    label="⬇️ Загрузить DXF",
                    data=f_dxf,
                    file_name="plan_cad.dxf",
                    mime="application/dxf",
                    use_container_width=True,
                )

    with col_exp2:
        if st.button("🏙️ Скачать 3D-модель (HTML)", use_container_width=True):
            export_path_3d = PROJECT_ROOT / "output" / "plan_3d.html"
            export_3d_html(
                site=site,
                buildings=buildings,
                tep=tep,
                filepath=export_path_3d,
                title=f"3D-застройка: {site.cadastral_number or 'Участок'}",
                default_basemap="light",
            )
            st.success(f"Сохранено: {export_path_3d.name}")
            with open(export_path_3d, "rb") as f_3d:
                st.download_button(
                    label="⬇️ Загрузить HTML в браузер",
                    data=f_3d,
                    file_name="plan_3d.html",
                    mime="text/html",
                    use_container_width=True,
                )

    with col_exp3:
        if st.button("💾 Скачать GeoJSON", use_container_width=True):
            export_path = PROJECT_ROOT / "output" / "plan.geojson"
            export_geojson(site, buildings, tep, export_path, as_wgs84=True)
            st.success(f"Сохранено: {export_path.name}")
            with open(export_path, "rb") as f_geo:
                st.download_button(
                    label="⬇️ Загрузить GeoJSON",
                    data=f_geo,
                    file_name="plan.geojson",
                    mime="application/geo+json",
                    use_container_width=True,
                )

    with col_exp4:
        if st.button("📄 Скачать отчёт", use_container_width=True):
            report_path = PROJECT_ROOT / "output" / "report.txt"
            report_text = generate_report(
                site, buildings, tep,
                st.session_state["config"], report_path,
                balance=st.session_state.get("balance"),
            )
            st.success(f"Сохранено: {report_path.name}")
            with st.expander("Просмотр отчёта"):
                st.code(report_text)

else:
    # Начальный экран
    st.info(
        "👈 Настройте параметры участка и нажмите **«Сгенерировать»** "
        "в боковой панели для создания плана застройки."
    )

    st.subheader("🗺️ Предпросмотр участка")
    map_html = generate_leaflet_map_html(site, buildings=None, tep=None, height=500)
    components.html(map_html, height=520)
    st.caption("Нажмите кнопку **«🚀 Сгенерировать»** в боковой панели, чтобы расставить жилые корпуса на этом участке.")


# ─── Библиотека типовых секций (доступна всегда) ──────────────────────
st.divider()
with st.expander(f"📦 Библиотека типовых секций ({library.count} типов секций в каталоге)", expanded=False):
    st.markdown(
        "Параметрический каталог секций жилых корпусов, используемых алгоритмом расстановки. "
        "Секции сгруппированы по градостроительным категориям и типам лифтовых узлов."
    )

    category_meta = [
        ("TOWER", "🏢 Точечные башни (TOWER) — отдельно стоящие доминанты"),
        ("MIDDLE", "🏙️ Рядовые секции (MIDDLE) — центральные звенья корпусов"),
        ("CORNER", "📐 Угловые поворотные секции (CORNER) — замкнутые и П/Г-образные дворы"),
        ("END", "🚪 Торцевые секции (END) — завершающие секции фасадов с торцевыми окнами"),
    ]

    for cat_code, cat_title in category_meta:
        cat_secs = [s for s in library.get_all() if s.category.upper() == cat_code]
        if not cat_secs:
            continue
        st.markdown(f"#### {cat_title}")
        for s in cat_secs:
            code_label = getattr(s, "section_code", "") or s.id
            with st.expander(f"{s.name} ({code_label}) — {s.width} × {s.depth} м | {s.min_floors}–{s.max_floors} эт."):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown(f"- **Габариты фасада:** {s.width} × {s.depth} м")
                    st.markdown(f"- **Площадь типового этажа:** {s.floor_area:,.1f} м²")
                    st.markdown(f"- **Количество лифтов:** {s.elevators} шт.")
                with c2:
                    st.markdown(f"- **Диапазон этажности:** {s.min_floors}–{s.max_floors} эт.")
                    st.markdown(f"- **Этажность по умолчанию:** {s.default_floors} эт.")
                    st.markdown(f"- **Коммерческий 1-й этаж:** {'Да' if s.has_commercial_ground else 'Нет'}")
                with c3:
                    total_apts = sum(s.apartments_per_floor.values())
                    st.markdown(f"- **Квартир на этаже:** {total_apts} шт.")
                    st.markdown(f"- **Квартирография:** {s.apartments_per_floor}")
                    st.markdown(f"- **Площади квартир:** {s.apt_areas}")
