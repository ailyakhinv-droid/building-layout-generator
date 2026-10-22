"""Комплексная диагностика алгоритмов расстановки, режимов и предпочтительных секций."""

import os
import sys
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from src.core.site_parser import create_rectangular_site
from src.core.buildable_area import compute_buildable_area
from src.core.placement import PlacementConfig, PlacementEngine
from src.core.tep_calculator import calculate_tep
from src.core.optimizer import Optimizer
from src.library.section_library import SectionLibrary


def run_diagnostics():
    print("=" * 80)
    print("  КОМПЛЕКСНАЯ ДИАГНОСТИКА: РАССТАНОВКА, РЕЖИМЫ, ПРЕДПОЧТИТЕЛЬНЫЕ СЕКЦИИ")
    print("=" * 80)

    with open("config/defaults.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    library = SectionLibrary()
    site = create_rectangular_site(200, 150)
    compute_buildable_area(site, config)

    # -------------------------------------------------------------
    # ТЕСТ 1: Предпочтительные секции и cascade_floors
    # -------------------------------------------------------------
    print("\n--- ТЕСТ 1: Влияние cascade_floors на preferred_section_ids ---")
    engine = PlacementEngine(site, library, config)
    cfg1 = PlacementConfig(
        typology="LINEAR",
        target_floors=9,
        preferred_section_ids=["mid_m9_7", "end_sh2_8"],
        cascade_floors=True,
    )
    blds1 = engine.generate(cfg1)
    secs1 = [s.section_type.id for b in blds1 for s in b.sections]
    print(f"Запрошено: mid_m9_7, end_sh2_8 (cascade=True)")
    print(f"Фактически размещены секции: {set(secs1)}")
    if "mid_m9_7" not in secs1:
        print("❌ БАГ 1.1: Предпочтительная секция mid_m9_7 проигнорирована и заменена на другую!")

    cfg1_nocascade = PlacementConfig(
        typology="LINEAR",
        target_floors=7,
        preferred_section_ids=["mid_m9_7", "end_sh2_8"],
        cascade_floors=False,
    )
    blds1_nc = engine.generate(cfg1_nocascade)
    secs1_nc = [s.section_type.id for b in blds1_nc for s in b.sections]
    print(f"Запрошено: mid_m9_7, end_sh2_8 (cascade=False)")
    print(f"Фактически размещены секции: {set(secs1_nc)}")

    # -------------------------------------------------------------
    # ТЕСТ 2: Недобор длины и корпуса без рядовых секций (двойные торцы)
    # -------------------------------------------------------------
    print("\n--- ТЕСТ 2: Раскладка длины в LINEAR при высокой этажности (24 эт.) ---")
    cfg2 = PlacementConfig(typology="LINEAR", target_floors=24, cascade_floors=False)
    blds2 = engine.generate(cfg2)
    print(f"Зданий создано: {len(blds2)}")
    has_only_ends = any(all(s.section_type.category == "END" for s in b.sections) for b in blds2)
    zero_mid = sum(1 for b in blds2 if len(b.sections) == 2 and all(s.section_type.category == "END" for s in b.sections))
    print(f"Корпусов, состоящих ТОЛЬКО из двух торцов (0 рядовых секций): {zero_mid} из {len(blds2)}")
    if has_only_ends:
        print(f"❌ БАГ 2: Корпуса состоят только из торцов ({blds2[0].sections[0].floors} эт.) вместо 24 эт. Рядовые 24-эт. секции M2 не помещаются из-за жесткого шага деления линии!")

    # -------------------------------------------------------------
    # ТЕСТ 3: Этажность торцевых и угловых секций при высотном строительстве
    # -------------------------------------------------------------
    print("\n--- ТЕСТ 3: Ограничения этажности угловых и торцевых секций ---")
    for s in library.get_all():
        if s.category in ("END", "CORNER"):
            print(f"  {s.category:<6}: {s.id:<12} min={s.min_floors}, max={s.max_floors}, лифтов={s.elevators}")

    # Случай A: Без каскада (cascade_floors=False)
    cfg3_no_casc = PlacementConfig(typology="U_SHAPE", target_floors=24, cascade_floors=False)
    blds3_a = engine.generate(cfg3_no_casc)
    if blds3_a:
        u_bldg = blds3_a[0]
        floors_per_cat = {s.section_type.category: s.floors for s in u_bldg.sections}
        print(f"Фактические этажи при cascade=False (целевые 24 эт.):")
        for cat, fl in floors_per_cat.items():
            print(f"  - {cat}: {fl} эт.")
        if floors_per_cat.get("CORNER", 0) <= 9 and floors_per_cat.get("MIDDLE", 0) == 24:
            print("  ℹ️ При cascade=False и 24 эт.: углы ограничены 9 эт. из-за библиотеки (будет дополнена позже).")

    # Случай B: С каскадом (cascade_floors=True)
    cfg3_casc = PlacementConfig(typology="U_SHAPE", target_floors=24, cascade_floors=True)
    blds3_b = engine.generate(cfg3_casc)
    if blds3_b:
        u_bldg = blds3_b[0]
        print(f"Фактические этажи при cascade=True (целевые 24 эт., плавный силуэт):")
        for s in u_bldg.sections:
            print(f"  • {s.section_type.id} ({s.section_type.category}): {s.floors} эт.")

    # -------------------------------------------------------------
    # ТЕСТ 4: Потеря параметров в Optimizer (высота этажа, лимит высоты, башни)
    # -------------------------------------------------------------
    print("\n--- ТЕСТ 4: Сохранение параметров в Optimizer ---")
    base_cfg = PlacementConfig(
        typology="AUTO",
        floor_height=3.3,
        ground_floor_height=4.5,
        max_building_height_m=35.0,
        allow_towers_in_mixed=True,
    )
    opt = Optimizer(site, library, config, base_placement_config=base_cfg)
    res_try = opt._try_placement(floors=10)
    if res_try and res_try.buildings:
        first_sec = res_try.buildings[0].sections[0]
        print(f"Базовый PlacementConfig: floor_height={base_cfg.floor_height}, max_h={base_cfg.max_building_height_m}")
        print(f"Фактический PlacedSection в _try_placement: floor_height={first_sec.floor_height}, ground_floor_height={first_sec.ground_floor_height}")
        if first_sec.floor_height is None:
            print("❌ БАГ 4: Optimizer._try_placement теряет floor_height, ground_floor_height и max_building_height_m!")

    # -------------------------------------------------------------
    # ТЕСТ 5: Режим 'Подбор под ТЭП' (optimize_for_target)
    # -------------------------------------------------------------
    print("\n--- ТЕСТ 5: Режим 'Подбор под ТЭП' ---")
    try:
        opt_target = opt.optimize_for_target({"target_far": 1.8})
        print(f"Целевой FAR=1.8, полученный вариант: {opt_target.floors} эт., FAR={opt_target.tep.far:.2f}, GFA={opt_target.tep.total_gfa:,.0f} м²")
    except Exception as e:
        print(f"❌ Ошибка в optimize_for_target: {e}")

    # -------------------------------------------------------------
    # ТЕСТ 6: Режим 'Максимизация' (optimize_maximize)
    # -------------------------------------------------------------
    print("\n--- ТЕСТ 6: Режим 'Максимизация' ---")
    try:
        opt_max_norm = opt.optimize_maximize(respect_normatives=True, explore_typologies=False)
        print(f"Максимизация с нормами: {opt_max_norm.floors} эт. ({opt_max_norm.typology}), FAR={opt_max_norm.tep.far:.2f}, норматив_ok={opt_max_norm.normative_ok}")
        
        opt_max_abs = opt.optimize_maximize(respect_normatives=False, explore_typologies=False)
        print(f"Максимизация абсолютная: {opt_max_abs.floors} эт. ({opt_max_abs.typology}), FAR={opt_max_abs.tep.far:.2f}, note: {opt_max_abs.note}")
    except Exception as e:
        print(f"❌ Ошибка в optimize_maximize: {e}")

    # -------------------------------------------------------------
    # ТЕСТ 7: Выбор предпочтительных секций одного типа
    # -------------------------------------------------------------
    print("\n--- ТЕСТ 7: Поведение при выборе нескольких секций одной категории ---")
    cfg7 = PlacementConfig(
        typology="LINEAR",
        target_floors=15,
        preferred_section_ids=["mid_m5_15", "mid_m2_24"],
        cascade_floors=False,
    )
    blds7 = engine.generate(cfg7)
    mid_used = {s.section_type.id for b in blds7 for s in b.sections if s.section_type.category == "MIDDLE"}
    print(f"Запрошены две секции MIDDLE: mid_m5_15 и mid_m2_24")
    print(f"Фактически использованы: {mid_used}")


if __name__ == "__main__":
    run_diagnostics()
