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


# ─── Боковая панель ──────────────────────────────────────────────────

st.sidebar.header("📐 Параметры участка")

site_mode = st.sidebar.radio(
    "Способ задания участка",
    ["Прямоугольник", "Координаты"],
    help="Выберите способ задания границ участка",
)

if site_mode == "Прямоугольник":
    col1, col2 = st.sidebar.columns(2)
    site_width = col1.number_input("Ширина, м", 50, 1000, 200, step=10)
    site_height = col2.number_input("Высота, м", 50, 1000, 150, step=10)
    site = create_rectangular_site(site_width, site_height)
else:
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

st.sidebar.markdown(f"**Площадь участка:** {site.area:,.0f} м²")

# ─── Нормативы ───────────────────────────────────────────────────────

st.sidebar.header("📏 Нормативы")

config["boundary_setback"] = st.sidebar.slider(
    "Отступ от границы, м", 0, 20, int(config.get("boundary_setback", 3))
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
    "Макс. % застройки", 0.1, 0.8, float(config.get("max_bcr", 0.4)), 0.05
)
config["max_far"] = st.sidebar.slider(
    "Макс. FAR", 0.5, 5.0, float(config.get("max_far", 2.5)), 0.1
)

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

max_sections = st.sidebar.slider(
    "Макс. секций в здании", 2, 12, 8,
    help="Максимальное количество секций в одном здании",
)


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
                result = optimizer.optimize_maximize()
                buildings = result.buildings
                tep = result.tep

        except Exception as e:
            st.error(f"Ошибка генерации: {e}")
            import traceback
            st.code(traceback.format_exc())
            st.stop()

        if not buildings:
            st.warning("Не удалось разместить ни одного здания. "
                       "Попробуйте увеличить участок или уменьшить отступы.")
            st.stop()

        # Сохраняем в session state
        st.session_state["buildings"] = buildings
        st.session_state["tep"] = tep
        st.session_state["site"] = site
        st.session_state["config"] = config


# ─── Отображение результатов ─────────────────────────────────────────

if "buildings" in st.session_state:
    buildings = st.session_state["buildings"]
    tep = st.session_state["tep"]
    site = st.session_state["site"]

    # Две колонки: план и ТЭП
    col_plan, col_tep = st.columns([2, 1])

    with col_plan:
        st.subheader("🗺️ План застройки")
        fig = plot_site_plan(site, buildings, tep)
        st.pyplot(fig)
        plt.close(fig)

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

    # Квартирография
    st.subheader("🏠 Квартирография")

    apt_data = []
    for i, building in enumerate(buildings):
        apts = building.total_apartments
        apt_data.append({
            "Дом": f"Д{i + 1}",
            "Этажность": building.floors,
            "Секций": len(building.sections),
            "1-комн.": apts.get("1k", 0),
            "2-комн.": apts.get("2k", 0),
            "3-комн.": apts.get("3k", 0),
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
                st.session_state["config"], report_path
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
