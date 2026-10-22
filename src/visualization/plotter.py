"""Визуализация плана застройки.

Модуль для отрисовки плана размещения зданий на участке
с помощью matplotlib.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # Бэкенд без GUI

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import PatchCollection
import numpy as np

from shapely.geometry import Polygon

from src.models.building import Building
from src.models.site import Site
from src.models.tep import TEP


# Цветовая палитра для зданий
BUILDING_COLORS = [
    "#4A90D9",  # Синий
    "#E07B39",  # Оранжевый
    "#50B86C",  # Зелёный
    "#D94E5D",  # Красный
    "#9B59B6",  # Фиолетовый
    "#F5A623",  # Жёлтый
    "#3498DB",  # Голубой
    "#E74C3C",  # Алый
]

# Цвета для типов секций
SECTION_CATEGORY_COLORS = {
    "MIDDLE": "#5B9BD5",
    "CORNER": "#ED7D31",
    "END": "#70AD47",
    "TOWER": "#9B59B6",
}


def plot_site_plan(
    site: Site,
    buildings: list[Building],
    tep: TEP | None = None,
    title: str = "План застройки",
    save_path: str | Path | None = None,
    show_labels: bool = True,
    show_dimensions: bool = True,
    figsize: tuple[float, float] = (14, 10),
    show_sections: bool = True,
) -> plt.Figure:
    """Отрисовать план застройки.

    Args:
        site: Участок.
        buildings: Список зданий.
        tep: ТЭП (для отображения в легенде).
        title: Заголовок плана.
        save_path: Путь для сохранения изображения.
        show_labels: Показывать подписи зданий.
        show_dimensions: Показывать размеры.
        figsize: Размер фигуры.

    Returns:
        Объект matplotlib Figure.
    """
    fig, ax = plt.subplots(1, 1, figsize=figsize)

    # 1. Рисуем границу участка
    _draw_polygon(ax, site.boundary, facecolor="#F5F5DC", edgecolor="#333333",
                  linewidth=2, alpha=0.3, label="Граница участка")

    # 2. Рисуем зону застройки
    if site.buildable_area is not None:
        _draw_polygon(ax, site.buildable_area, facecolor="none",
                      edgecolor="#00AA00", linewidth=1.5, linestyle="--",
                      alpha=0.8, label="Зона застройки")

    # 3. Рисуем красные линии
    for red_line in site.red_lines:
        xs, ys = red_line.xy
        ax.plot(xs, ys, color="red", linewidth=2.5, linestyle="-",
                label="Красная линия", zorder=5)

    # 4. Рисуем здания
    for i, building in enumerate(buildings):
        color = BUILDING_COLORS[i % len(BUILDING_COLORS)]

        if show_sections:
            # Рисуем каждую секцию отдельно
            for j, section in enumerate(building.sections):
                footprint = section.footprint
                cat_color = SECTION_CATEGORY_COLORS.get(
                    section.section_type.category, color
                )
                _draw_polygon(
                    ax, footprint,
                    facecolor=cat_color,
                    edgecolor="#222222",
                    linewidth=1.0,
                    alpha=0.75,
                )
                # Отметка этажности и кода на каждой секции
                s_code = getattr(section.section_type, "section_code", "") or section.section_type.name.split()[0]
                ax.annotate(
                    f"{s_code}\n{section.floors}э",
                    xy=(section.x, section.y),
                    fontsize=6.5,
                    color="#111111",
                    fontweight="bold",
                    ha="center",
                    va="center",
                    zorder=7,
                )
        else:
            # Рисуем общий контур корпуса
            _draw_polygon(
                ax, building.footprint,
                facecolor=color,
                edgecolor="#1A5276",
                linewidth=1.8,
                alpha=0.85,
            )
            c_pt = building.footprint.centroid
            ax.annotate(
                f"Корпус {i + 1}\n{building.floors} эт.",
                xy=(c_pt.x, c_pt.y),
                fontsize=8,
                color="#FFFFFF",
                fontweight="bold",
                ha="center",
                va="center",
                zorder=7,
                bbox=dict(boxstyle="round,pad=0.2", facecolor=color, edgecolor="#1A5276", alpha=0.9),
            )

        # Выделяем внутренний двор для П-образных и Г-образных корпусов
        if getattr(building, "typology", "LINEAR") in ("U_SHAPE", "L_SHAPE", "COURTYARD"):
            try:
                hull = building.footprint.convex_hull
                court_poly = hull.difference(building.footprint)
                if not court_poly.is_empty and court_poly.area > 50.0:
                    _draw_polygon(
                        ax, court_poly,
                        facecolor="#E8F8F5",
                        edgecolor="#27AE60",
                        linewidth=1.5,
                        linestyle=":",
                        alpha=0.55,
                    )
                    c_pt = court_poly.centroid
                    ax.annotate(
                        "Двор",
                        xy=(c_pt.x, c_pt.y),
                        fontsize=8,
                        color="#196F3D",
                        fontweight="bold",
                        ha="center",
                        va="center",
                        bbox=dict(boxstyle="round,pad=0.25", facecolor="#E8F8F5", edgecolor="#27AE60", alpha=0.8),
                        zorder=8,
                    )
            except Exception:
                pass

        # Подпись здания с указанием типологии и диапазона этажей
        if show_labels:
            centroid = building.footprint.centroid
            typo_name = {
                "U_SHAPE": "П-обр.",
                "L_SHAPE": "Г-обр.",
                "COURTYARD": "Квартал",
                "LINEAR": "Линейн."
            }.get(getattr(building, "typology", "LINEAR"), "")
            fl_text = (
                f"{building.floors} эт."
                if building.min_floors == building.floors
                else f"{building.min_floors}–{building.floors} эт."
            )
            label_text = f"Д{i + 1} ({typo_name})\n{fl_text}"
            ax.annotate(
                label_text,
                xy=(centroid.x, centroid.y),
                fontsize=8,
                fontweight="bold",
                ha="center",
                va="center",
                color="white",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#333333", alpha=0.85),
                zorder=10,
            )

    # 5. Настройка осей
    ax.set_aspect("equal")
    ax.set_xlabel("X, м", fontsize=10)
    ax.set_ylabel("Y, м", fontsize=10)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
    ax.grid(True, alpha=0.3, linestyle="--")

    # 6. Масштабная линейка
    _add_scale_bar(ax, site.boundary)

    # 7. Легенда
    legend_items = [
        mpatches.Patch(facecolor="#F5F5DC", edgecolor="#333333", label="Участок"),
        mpatches.Patch(facecolor="none", edgecolor="#00AA00", linestyle="--", label="Зона застройки"),
        mpatches.Patch(facecolor=SECTION_CATEGORY_COLORS["MIDDLE"], edgecolor="#222", label="Рядовая секция"),
        mpatches.Patch(facecolor=SECTION_CATEGORY_COLORS["END"], edgecolor="#222", label="Торцевая секция"),
        mpatches.Patch(facecolor=SECTION_CATEGORY_COLORS["CORNER"], edgecolor="#222", label="Угловая секция"),
        mpatches.Patch(facecolor=SECTION_CATEGORY_COLORS["TOWER"], edgecolor="#222", label="Точечная (башня)"),
        mpatches.Patch(facecolor="#E8F8F5", edgecolor="#27AE60", linestyle=":", label="Внутренний двор"),
    ]
    ax.legend(handles=legend_items, loc="upper right", fontsize=8,
              framealpha=0.9)

    # 8. Блок ТЭП
    if tep is not None:
        tep_text = (
            f"Площадь участка: {tep.site_area:,.0f} м²\n"
            f"Застройка: {tep.building_area:,.0f} м² ({tep.bcr:.0%})\n"
            f"GFA: {tep.total_gfa:,.0f} м² (FAR {tep.far:.2f})\n"
            f"Зданий: {tep.building_count}, эт.: {tep.avg_floors:.0f}\n"
            f"Квартир: {tep.apartments_total}\n"
            f"Население: {tep.population:,.0f} чел."
        )
        ax.text(
            0.02, 0.02, tep_text,
            transform=ax.transAxes,
            fontsize=8,
            verticalalignment="bottom",
            fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="white",
                      edgecolor="#CCCCCC", alpha=0.9),
            zorder=15,
        )

    plt.tight_layout()

    # Сохранение
    if save_path is not None:
        fig.savefig(str(save_path), dpi=150, bbox_inches="tight",
                    facecolor="white")

    return fig


def _draw_polygon(
    ax: plt.Axes,
    polygon: Polygon,
    facecolor: str = "blue",
    edgecolor: str = "black",
    linewidth: float = 1.0,
    linestyle: str = "-",
    alpha: float = 0.5,
    label: str | None = None,
) -> None:
    """Нарисовать Shapely-полигон на matplotlib axes."""
    if polygon.is_empty:
        return

    if polygon.geom_type == "MultiPolygon":
        for geom in polygon.geoms:
            _draw_polygon(ax, geom, facecolor, edgecolor, linewidth,
                          linestyle, alpha)
        return

    xs, ys = polygon.exterior.xy
    ax.fill(xs, ys, facecolor=facecolor, edgecolor=edgecolor,
            linewidth=linewidth, linestyle=linestyle, alpha=alpha,
            label=label)


def _add_scale_bar(ax: plt.Axes, boundary: Polygon) -> None:
    """Добавить масштабную линейку на план."""
    minx, miny, maxx, maxy = boundary.bounds
    total_width = maxx - minx

    # Подбираем удобную длину линейки
    for bar_length in [10, 20, 50, 100, 200, 500]:
        if bar_length <= total_width * 0.3:
            continue
        break
    else:
        bar_length = round(total_width * 0.25, -1)

    # Позиция линейки
    bar_x = minx + (maxx - minx) * 0.05
    bar_y = miny - (maxy - miny) * 0.05

    ax.plot(
        [bar_x, bar_x + bar_length], [bar_y, bar_y],
        color="black", linewidth=3, solid_capstyle="butt",
    )
    ax.text(
        bar_x + bar_length / 2, bar_y - (maxy - miny) * 0.02,
        f"{bar_length:.0f} м",
        ha="center", va="top", fontsize=8, fontweight="bold",
    )
