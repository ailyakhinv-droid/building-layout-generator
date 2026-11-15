"""Визуальный аудит и графические снимки (Visual Snapshots) всех параметров Шага 3."""

from __future__ import annotations

import unittest
from pathlib import Path
import matplotlib
matplotlib.use("Agg")  # Headless
import matplotlib.pyplot as plt
from shapely.geometry import MultiPolygon

from src.models.site import Site
from src.core.tep_calculator import calculate_tep
from src.core.placement import PlacementConfig
import dashboard_studio.server  # Применяет zero-touch патчи (калибровка высоты и типологии)
from dashboard_prototype.generator_service import run_pipeline

OUTPUT_DIR = Path("output/visual_tests/step3_audit")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def render_snapshot(res: dict, out_png: Path, title: str = ""):
    """Отрендерить визуальный снапшот мастер-плана из результатов run_pipeline."""
    site = res.get("_site_obj")
    buildings = res.get("_buildings_obj", [])
    
    fig, ax = plt.subplots(figsize=(9, 7), dpi=100)
    ax.set_aspect("equal", "box")
    ax.set_facecolor("#0f172a")  # Темная подложка Studio
    fig.patch.set_facecolor("#020617")

    # 1. Граница участка
    if site and getattr(site, "boundary", None) and not site.boundary.is_empty:
        bx, by = site.boundary.exterior.xy
        ax.plot(bx, by, color="#38bdf8", linewidth=2.5, label="Граница ЗУ")
        ax.fill(bx, by, color="#0284c7", alpha=0.08)

    # 2. Зона допустимого строительства
    if site and getattr(site, "buildable_area", None) and not site.buildable_area.is_empty:
        ba = site.buildable_area
        geoms = ba.geoms if isinstance(ba, MultiPolygon) else [ba]
        for g in geoms:
            gx, gy = g.exterior.xy
            ax.plot(gx, gy, color="#10b981", linewidth=1.5, linestyle=":", label="Зона застройки")

    # 3. Секции зданий с цветовым кодированием по этажности и типам
    cat_colors = {
        "MIDDLE": "#3b82f6",
        "END": "#06b6d4",
        "CORNER": "#8b5cf6",
        "TOWER": "#f59e0b",
        "UNIVERSAL": "#10b981",
    }

    sec_count = 0
    max_h = 0.0
    for b in buildings:
        for s in b.sections:
            sec_count += 1
            fp = s.footprint
            if fp and not fp.is_empty:
                fx, fy = fp.exterior.xy
                cat = getattr(s.section_type, "category", "MIDDLE")
                c = cat_colors.get(cat, "#38bdf8")
                ax.fill(fx, fy, color=c, alpha=0.85, edgecolor="#ffffff", linewidth=0.8)
                max_h = max(max_h, s.height)
                # Подпись этажности на полигоне секции
                cx, cy = fp.centroid.x, fp.centroid.y
                ax.text(cx, cy, f"{s.floors}", color="#ffffff", fontsize=7.5, fontweight="bold",
                        ha="center", va="center")

    ax.axis("off")
    subtitle = f"Корпусов: {len(buildings)}, Секций: {sec_count}, Макс. высота: {max_h:.1f} м"
    ax.set_title(f"{title}\n{subtitle}", color="#f1f5f9", fontsize=11, fontweight="bold", pad=12)
    fig.tight_layout()
    fig.savefig(out_png, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)


def get_base_payload():
    return {
        "site_mode": "cadastre",
        "custom_area": 35000,
        "boundary_setback": 6.0,
        "red_line_setback": 5.0,
        "target_floors": 14,
        "max_building_height_m": 50.0,
        "floor_height": 3.0,
        "cascade_floors": True,
        "asymmetric_wings": True,
        "car_free_courtyard": True,
        "only_ground_parking": False,
        "typology": "AUTO",
        "courtyard_orientation": "SOUTH",
        "max_far": 2.5,
        "max_bcr": 0.4,
        "road_preset": "none",
        "max_sections": 8,
        "stage": 2,
        "site_locked": True,
        "allow_parking_in_zouit": False,
        "allow_towers_in_mixed": True,
        "regional_norm_id": "russia_sp42",
        "insolation": {
            "enabled": False,
            "norm_hours": 2.0,
            "include_surroundings": False,
            "default_surrounding_height": 15.0,
            "grid_step_m": 3.0,
            "auto_cascade_reduction": True,
        },
        "respect_norms": True,
        "gen_mode": "fixed",
    }


class TestStep3VisualAudit(unittest.TestCase):
    """Тесты с визуальными проверками и генерацией снимков PNG."""

    def test_01_tower_height_limit_50m(self):
        """Проверка 1: Ограничение высоты 50.0 м для башен."""
        payload = get_base_payload()
        payload["typology"] = "TOWER"
        payload["target_floors"] = 16
        payload["max_building_height_m"] = 50.0

        res = run_pipeline(payload)
        out_png = OUTPUT_DIR / "01_tower_height_limit_50m.png"
        render_snapshot(res, out_png, "Контроль высоты: Башни при лимите 50.0 м")

        heights = [s["height_m"] for s in res.get("sections", [])]
        self.assertGreater(len(heights), 0)
        max_h = max(heights)
        print(f"\n[SNAP 1] Башня Б1 при лимите 50 м: макс. высота = {max_h} м (<= 50.0 м)")
        self.assertLessEqual(max_h, 50.0, f"Высота {max_h} м превышает лимит 50.0 м!")

    def test_02_floors_slider_8_vs_14(self):
        """Проверка 2: Ползунок этажности (8 эт. vs 14 эт.)."""
        # 8 этажей
        p8 = get_base_payload()
        p8["target_floors"] = 8
        p8["typology"] = "AUTO"
        res8 = run_pipeline(p8)
        render_snapshot(res8, OUTPUT_DIR / "02_floors_8.png", "Базовая этажность: 8 этажей")
        f8 = [s["floors"] for s in res8.get("sections", [])]
        max_f8 = max(f8) if f8 else 0

        # 14 этажей
        p14 = get_base_payload()
        p14["target_floors"] = 14
        p14["typology"] = "AUTO"
        res14 = run_pipeline(p14)
        render_snapshot(res14, OUTPUT_DIR / "02_floors_14.png", "Базовая этажность: 14 этажей")
        f14 = [s["floors"] for s in res14.get("sections", [])]
        max_f14 = max(f14) if f14 else 0

        print(f"\n[SNAP 2] Ползунок этажей: 8 эт -> {max_f8} эт, 14 эт -> {max_f14} эт")
        self.assertLessEqual(max_f8, 9)
        self.assertGreater(max_f14, max_f8)

    def test_03_boundary_setback_3m_vs_12m(self):
        """Проверка 3: Ползунок отступа границ ЗУ (3 м vs 12 м)."""
        p3 = get_base_payload()
        p3["boundary_setback"] = 3.0
        res3 = run_pipeline(p3)
        render_snapshot(res3, OUTPUT_DIR / "03_setback_3m.png", "Строительный отступ: 3.0 м")
        area3 = res3.get("buildable_area_sqm", 0)

        p12 = get_base_payload()
        p12["boundary_setback"] = 12.0
        res12 = run_pipeline(p12)
        render_snapshot(res12, OUTPUT_DIR / "03_setback_12m.png", "Строительный отступ: 12.0 м")
        area12 = res12.get("buildable_area_sqm", 0)

        print(f"\n[SNAP 3] Отступ ЗУ: 3 м -> {area3:.0f} м², 12 м -> {area12:.0f} м²")
        self.assertGreater(area3, area12 + 2000)

    def test_04_max_sections_slider_3_vs_8(self):
        """Проверка 4: Макс. секций в корпусе (3 секции vs 8 секций)."""
        p3 = get_base_payload()
        p3["typology"] = "SECTIONAL"
        p3["max_sections"] = 3
        res3 = run_pipeline(p3)
        render_snapshot(res3, OUTPUT_DIR / "04_max_sections_3.png", "Макс. секций в корпусе: 3 секции")
        b3 = res3.get("buildings", [])
        max_sec_3 = max(b.get("sections_count", 0) for b in b3) if b3 else 0

        p8 = get_base_payload()
        p8["typology"] = "SECTIONAL"
        p8["max_sections"] = 8
        res8 = run_pipeline(p8)
        render_snapshot(res8, OUTPUT_DIR / "04_max_sections_8.png", "Макс. секций в корпусе: 8 секций")
        b8 = res8.get("buildings", [])
        max_sec_8 = max(b.get("sections_count", 0) for b in b8) if b8 else 0

        print(f"\n[SNAP 4] Макс. секций: ограничение 3 -> факт {max_sec_3}, ограничение 8 -> факт {max_sec_8}")
        self.assertLessEqual(max_sec_3, 3)

    def test_05_all_typologies(self):
        """Проверка 5: Все кнопки типологий (AUTO, U_SHAPE, TOWER, SECTIONAL)."""
        typologies = {
            "AUTO": "Квартальная адаптивная (AUTO)",
            "U_SHAPE": "П-образные дворы (U_SHAPE)",
            "TOWER": "Точечные башни (TOWER)",
            "SECTIONAL": "Секционная широтная (SECTIONAL)",
        }
        for typ, label in typologies.items():
            p = get_base_payload()
            p["typology"] = typ
            res = run_pipeline(p)
            out_png = OUTPUT_DIR / f"05_typology_{typ.lower()}.png"
            render_snapshot(res, out_png, f"Типология: {label}")
            b_list = res.get("buildings", [])
            print(f"[SNAP 5] Типология {typ}: размещено {len(b_list)} корпусов")
            self.assertGreater(len(b_list), 0)

    def test_06_only_ground_parking(self):
        """Проверка 6: Чекбокс 'Все парковки на участке (без подземного)'."""
        p = get_base_payload()
        p["only_ground_parking"] = True
        res = run_pipeline(p)
        render_snapshot(res, OUTPUT_DIR / "06_only_ground_parking.png", "Концепция: 100% наземных парковок")
        tep = res.get("tep", {})
        parking = tep.get("parking", {})
        underground = parking.get("underground_spaces", 0)
        print(f"\n[SNAP 6] 100% открытые парковки: подземных м/м = {underground}")
        self.assertEqual(underground, 0)


if __name__ == "__main__":
    unittest.main()
