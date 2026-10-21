"""Streamlit-приложение: Генератор застройки по ТЭП.

Интерактивный интерфейс для настройки участка, выбора секций,
генерации расстановки и просмотра ТЭП.
"""

from __future__ import annotations

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
)
from src.visualization.map_view import generate_leaflet_map_html


# ─── Настройка страницы ──────────────────────────────────────────────

st.set_page_config(
    page_title="Генератор застройки по ТЭП",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
    ["Кадастровый номер (OSM подложка)", "Прямоугольник", "Координаты", "Загрузка CAD (DWG / DXF)"],
    help="Выберите способ задания границ участка: по кадастровому номеру РФ с подложкой OpenStreetMap, типовой прямоугольник, координаты вершин или импорт из CAD чертежа",
)

if site_mode == "Кадастровый номер (OSM подложка)":
    # 1. Поле прямого ввода кадастрового номера
    entered_cad = st.sidebar.text_input(
        "Кадастровый номер участка (РФ)",
        value=st.session_state.get("last_cadastral", "50:27:0010101:500"),
        help="Введите кадастровый номер любого региона РФ (например, 50:27:..., 78:34:..., 23:43:..., 66:41:..., 16:50:...). Регион и город определятся автоматически.",
    )
    st.session_state["last_cadastral"] = entered_cad.strip()

    # Быстрые пресеты по городам РФ для тестирования
    cad_quick_samples = {
        "(свой номер выше)": "",
        "50:27:0010101:500 (МО, Подольск — 3.3 га)": "50:27:0010101:500",
        "50:04:0010101:300 (МО, Дмитров — 3.2 га)": "50:04:0010101:300",
        "77:17:0120316:1024 (Москва, Коммунарка — 3.6 га)": "77:17:0120316:1024",
        "78:34:0004286:115 (СПб, Приморский — 3.4 га)": "78:34:0004286:115",
        "23:43:0106012:450 (Краснодар, Зап. обход — 4.3 га)": "23:43:0106012:450",
        "66:41:0101001:500 (Екатеринбург, Академический)": "66:41:0101001:500",
        "16:50:010101:200 (Казань, Ново-Савиновский)": "16:50:010101:200",
        "54:35:010101:300 (Новосибирск)": "54:35:010101:300",
        "52:18:0010101:400 (Нижний Новгород)": "52:18:0010101:400",
        "42:24:010101:500 (Кемерово / Кузбасс)": "42:24:010101:500",
        "74:36:010101:200 (Челябинск)": "74:36:010101:200",
    }
    sel_sample = st.sidebar.selectbox(
        "Или выберите пример из каталога",
        list(cad_quick_samples.keys()),
        index=0,
        help="Выберите пример, чтобы автоматически подставить его кадастровый номер",
    )
    if sel_sample != "(свой номер выше)":
        sample_code = cad_quick_samples[sel_sample]
        if sample_code != entered_cad:
            entered_cad = sample_code
            st.session_state["last_cadastral"] = sample_code
            st.rerun()

    # Опциональная настройка параметров и координат
    with st.sidebar.expander("📍 Настройка координат и площади", expanded=False):
        custom_area = st.number_input(
            "Площадь участка, м²",
            min_value=5000,
            max_value=300000,
            value=32000,
            step=1000,
            help="Используется для расчёта формы, если введён произвольный номер",
        )
        col_lat, col_lon = st.columns(2)
        override_lat = col_lat.number_input(
            "Широта (Lat)", value=0.0, format="%.5f", help="Оставьте 0.0 для автоопределения по кадастровому номеру"
        )
        override_lon = col_lon.number_input(
            "Долгота (Lon)", value=0.0, format="%.5f", help="Оставьте 0.0 для автоопределения по кадастровому номеру"
        )
        ov_lat = override_lat if override_lat != 0.0 else None
        ov_lon = override_lon if override_lon != 0.0 else None

        enable_red_line = st.checkbox(
            "Добавить красную линию (отступ УДС)",
            value=False,
            help="По умолчанию выключено. Включает градостроительную красную линию вдоль южной границы участка.",
        )

        egrn_coords_raw = st.text_area(
            "Координаты из выписки ЕГРН (WGS-84: lon, lat)",
            placeholder="37.5458, 55.4312\n37.5490, 55.4312\n37.5490, 55.4330\n...",
            help="Вставьте координаты вершин участка в формате долгота, широта, если у вас есть официальная выписка ЕГРН",
        )
        custom_wgs = None
        if egrn_coords_raw.strip():
            custom_wgs = []
            for line in egrn_coords_raw.strip().split("\n"):
                parts = line.strip().replace(";", ",").split(",")
                if len(parts) >= 2:
                    try:
                        custom_wgs.append((float(parts[0].strip()), float(parts[1].strip())))
                    except ValueError:
                        pass

    try:
        parcel_info = get_cadastral_parcel(
            entered_cad,
            custom_area_sqm=custom_area,
            custom_wgs84_coords=custom_wgs,
            override_lat=ov_lat,
            override_lon=ov_lon,
            add_red_line=enable_red_line,
        )
        site = create_site_from_cadastre(parcel_info)
        st.session_state["cadastral_norm_id"] = parcel_info.regional_norm_id

        st.sidebar.success(
            f"✓ **{parcel_info.region_name}**\n\n*{parcel_info.district_name}*: {site.area:,.0f} м² ({site.area / 10000.0:.2f} га)"
        )
        st.sidebar.caption(f"📍 {parcel_info.address}")
        st.sidebar.caption(f"🌐 Центр WGS-84: `{parcel_info.center_lat:.5f}, {parcel_info.center_lon:.5f}`")
        if site.red_lines:
            st.sidebar.caption(f"⛔ Красная линия УДС активна ({len(site.red_lines)} шт.)")

    except Exception as e:
        st.sidebar.error(f"Ошибка получения участка: {e}")
        site = create_rectangular_site(200, 150)

elif site_mode == "Прямоугольник":
    col1, col2 = st.sidebar.columns(2)
    site_width = col1.number_input("Ширина, м", 50, 1000, 200, step=10)
    site_height = col2.number_input("Высота, м", 50, 1000, 150, step=10)
    site = create_rectangular_site(site_width, site_height)
elif site_mode == "Координаты":
    coords_text = st.sidebar.text_area(
        "Координаты (x,y по одной на строку)",
        value="0,0\n200,0\n200,150\n0,150",
        height=150,
        help="Введите координаты вершин участка в метрах",
    )
    try:
        coords = []
        for line in coords_text.strip().split("\n"):
            parts = line.strip().split(",")
            if len(parts) >= 2:
                coords.append((float(parts[0]), float(parts[1])))
        site = parse_coordinates(coords)
    except Exception as e:
        st.sidebar.error(f"Ошибка разбора координат: {e}")
        st.stop()
else:
    cad_file = st.sidebar.file_uploader(
        "Чертеж границы (.dxf, .dwg)",
        type=["dxf", "dwg"],
        help="Загрузите чертеж генплана с контуром участка. DXF читается нативно, DWG конвертируется через ODA.",
    )
    if cad_file is not None:
        try:
            file_bytes = cad_file.getvalue()
            layers_info = inspect_cad_layers(file_bytes, cad_file.name)
            if not layers_info:
                st.sidebar.error("В чертеже не найдено геометрических линий или полилиний.")
                st.stop()

            layer_names = [l.name for l in layers_info]
            cand_idx = 0
            for idx, l in enumerate(layers_info):
                if l.is_candidate:
                    cand_idx = idx
                    break

            sel_layer = st.sidebar.selectbox(
                "Слой границы участка",
                layer_names,
                index=cand_idx,
                help="Слой CAD, на котором начерчен внешний контур границы участка",
            )

            rl_names = ["(нет)"] + layer_names
            rl_idx = 0
            for idx, l in enumerate(layers_info):
                if l.is_red_line_candidate and l.name != sel_layer:
                    rl_idx = idx + 1
                    break
            sel_rl = st.sidebar.selectbox("Слой красных линий", rl_names, index=rl_idx)
            rl_param = None if sel_rl == "(нет)" else sel_rl

            site, cad_meta = parse_cad_site(
                file_bytes,
                filename=cad_file.name,
                boundary_layer=sel_layer,
                red_lines_layer=rl_param,
                normalize_origin=True,
            )

            st.sidebar.success(
                f"✓ Участок: {site.area:,.0f} м² ({cad_meta['vertices_count']} вершин)"
            )
            if site.base_offset != (0.0, 0.0):
                st.sidebar.caption(f"📍 МСК привязка: ({site.base_offset[0]:,.0f}, {site.base_offset[1]:,.0f})")
            if cad_meta["red_lines_count"] > 0:
                st.sidebar.caption(f"⛔ Красных линий: {cad_meta['red_lines_count']} шт.")

        except DWGConversionError as e:
            st.sidebar.warning(str(e))
            st.sidebar.info("💡 Сохраните чертеж в AutoCAD/nanoCAD в формат DXF (`DXFOUT`) и загрузите .dxf файл.")
            st.stop()
        except Exception as e:
            st.sidebar.error(f"Ошибка обработки CAD файла: {e}")
            st.stop()
    else:
        st.sidebar.info("Загрузите чертеж границы участка (.dxf или .dwg).")
        st.sidebar.caption("💡 Совет: команда `DXFOUT` в AutoCAD или «Сохранить как → DXF».")
        # Тестовый полигон по умолчанию пока файл не выбран
        site = create_rectangular_site(200, 150)

st.sidebar.markdown(f"**Площадь участка:** {site.area:,.0f} м²")

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

sel_cardinal = st.sidebar.selectbox(
    "Назначить ориентацию фасада / улицы",
    list(cardinal_presets.keys()),
    index=0,
    help="Быстро назначить ориентацию главного фасада участка по сторонам света (истинному северу)",
)

if sel_cardinal != "(произвольный угол)" and cardinal_presets[sel_cardinal] is not None:
    preset_angle = cardinal_presets[sel_cardinal]
    if st.session_state.get("site_rotation", 0) != preset_angle:
        st.session_state["site_rotation"] = preset_angle
        st.rerun()

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
    value=current_rot,
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
        "П-образные дворы (U-Shape)",
        "Г-образные корпуса (L-Shape)",
        "Линейная застройка (Пластины)",
    ],
    help="Выберите градостроительный тип застройки участка",
)
typology_map = {
    "Квартальная / Смешанная (AUTO)": "AUTO",
    "П-образные дворы (U-Shape)": "U_SHAPE",
    "Г-образные корпуса (L-Shape)": "L_SHAPE",
    "Линейная застройка (Пластины)": "LINEAR",
}
typology_val = typology_map[typology_choice]

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


# ─── Генерация ───────────────────────────────────────────────────────

generate_btn = st.sidebar.button("🚀 Сгенерировать", type="primary", use_container_width=True)

if generate_btn:
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
    site = st.session_state["site"]

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
            "🗺️ Векторная подложка OSM",
            "📐 2D Генплан (Схема)",
            "🛰️ Сведения о геопривязке",
        ])

        with map_tab1:
            map_html = generate_leaflet_map_html(site, buildings, tep, height=580)
            components.html(map_html, height=600)
            st.caption(
                "💡 Интерактивная векторная карта OpenStreetMap. "
                "Кликните на здание для просмотра карточки ТЭП. В правом верхнем углу доступен выбор слоёв."
            )

        with map_tab2:
            fig = plot_site_plan(site, buildings, tep)
            st.pyplot(fig)
            plt.close(fig)

        with map_tab3:
            st.markdown(f"**Кадастровый номер:** `{site.cadastral_number or 'Не задан'}`")
            if site.geo_center:
                st.markdown(f"**Координаты центра (WGS-84):** `{site.geo_center[0]:.6f}, {site.geo_center[1]:.6f}`")
            if site.address:
                st.markdown(f"**Ориентир / Адрес:** {site.address}")
            st.markdown(f"**Площадь участка:** {site.area:,.1f} м² ({site.area / 10000.0:.2f} га)")
            if site.buildable_area:
                st.markdown(f"**Площадь зоны застройки:** {site.buildable_area.area:,.1f} м²")
            if site.red_lines:
                st.markdown(f"**Красных линий:** {len(site.red_lines)} шт.")

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
    col_exp1, col_exp2 = st.columns(2)

    with col_exp1:
        if st.button("💾 Скачать GeoJSON"):
            export_path = PROJECT_ROOT / "output" / "plan.geojson"
            export_geojson(site, buildings, tep, export_path)
            st.success(f"Сохранено: {export_path}")

    with col_exp2:
        if st.button("📄 Скачать отчёт"):
            report_path = PROJECT_ROOT / "output" / "report.txt"
            report_text = generate_report(
                site, buildings, tep,
                st.session_state["config"], report_path,
                balance=st.session_state.get("balance"),
            )
            st.success(f"Сохранено: {report_path}")
            with st.expander("Просмотр отчёта"):
                st.code(report_text)

else:
    # Начальный экран
    st.info(
        "👈 Настройте параметры участка и нажмите **«Сгенерировать»** "
        "в боковой панели для создания плана застройки."
    )

    if site_mode == "Кадастровый номер (OSM подложка)" or site.geo_center:
        st.subheader("🗺️ Предпросмотр участка на карте OpenStreetMap")
        map_html = generate_leaflet_map_html(site, buildings=None, tep=None, height=460)
        components.html(map_html, height=480)
        st.caption("Нажмите кнопку **«🚀 Сгенерировать»** в боковой панели, чтобы расставить жилые корпуса на этом участке.")

    # Демо-информация о библиотеке секций
    st.subheader("📦 Библиотека типовых секций")

    for section in library.get_all():
        with st.expander(f"{section.name} ({section.category})"):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"- **Размеры:** {section.width} × {section.depth} м")
                st.markdown(f"- **Этажность:** {section.min_floors}–{section.max_floors} "
                            f"(по умолч. {section.default_floors})")
                st.markdown(f"- **Площадь этажа:** {section.floor_area} м²")
            with col2:
                st.markdown(f"- **Квартиры/этаж:** {section.apartments_per_floor}")
                st.markdown(f"- **Площади кв.:** {section.apt_areas}")
                st.markdown(f"- **Коммерч. 1 эт.:** "
                            f"{'Да' if section.has_commercial_ground else 'Нет'}")
