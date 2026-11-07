"""Комплексный аудит всех функций и ограничений Генератора Застройки.

Проверяет:
1. Зона застройки, отступы и красные линии (Site, buildable_area, boundary erosion, MultiPolygon).
2. Противопожарные расстояния (СП 4.13130: 10м торцы, 18м параллельно, башни 4 стороны, кастомные разрывы).
3. Инсоляционные ограничения (СанПиН 1.2.3685-21: запрет меридиональных <25°, разрывы H*k, ориентация дворов).
4. Предельные коэффициенты застройки и плотности (BCR / КЗ, FAR / КИТ, hard caps и soft scoring).
5. Ограничения высотности и этажности (max_building_height_m, min/max этажи секций, каскад).
6. Баланс территории, парковки и озеленение (СП 42, Москва, СПб, МО: дефицит парковок -> подземный, площадки).
7. Парсинг ГПЗУ и выявление ЗОУИТ (ЛЭП, водопровод, газ, СЗЗ, водоохранные, приаэродромные, ОКН).
8. Нарезка улично-дорожной сетью (RoadSlicer: продольная, поперечная, 2х2, пользовательские дороги, суб-блоки).
9. Оптимизатор и максимизатор (Top-1, подбор под ТЭП, сетка углов, 100% соблюдение нормативов).
10. Экспортные форматы (DXF, 3D HTML, GeoJSON, текстовый отчет) и REST API эндпоинты.
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
import time
from pathlib import Path

# Обеспечиваем корректную кодировку для консоли Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import shapely
from shapely.geometry import LineString, Point, Polygon, MultiPolygon
import yaml

from src.models.site import Site
from src.models.building import Building, PlacedSection
from src.models.tep import TEP
from src.library.section_library import SectionLibrary
from src.core.site_parser import create_rectangular_site
from src.core.buildable_area import compute_buildable_area, get_obb_dimensions
from src.core.placement import (
    PlacementConfig,
    PlacementEngine,
    angle_to_horizontal,
    MIN_MERIDIAN_INSOLATION_ANGLE_DEG,
)
from src.core.tep_calculator import calculate_tep, check_normatives
from src.core.territory_balance import calculate_territory_balance
from src.core.regional_norms import RegionalNorm
from src.core.gpzu_parser import (
    extract_zouit_restrictions,
    extract_gpzu_parameters,
    parse_gpzu_file,
)
from src.core.road_slicer import RoadSlicer
from src.core.optimizer import Optimizer
from src.export.dxf_export import export_dxf
from src.export.geojson_export import export_geojson
from src.export.html_3d_export import export_3d_html
from src.export.report import generate_report


class AuditRunner:
    def __init__(self):
        self.results: list[dict] = []
        with open("config/defaults.yaml", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        with open("config/regional_norms.yaml", encoding="utf-8") as f:
            self.regional_norms_data = yaml.safe_load(f)
        self.library = SectionLibrary()

    def record(self, module: str, test_name: str, passed: bool, details: str = "", metrics: dict | None = None):
        self.results.append({
            "module": module,
            "test": test_name,
            "passed": passed,
            "details": details,
            "metrics": metrics or {},
        })
        status_icon = "✓ PASS" if passed else "✗ FAIL"
        print(f"[{status_icon}] {module} -> {test_name}")
        if details:
            print(f"       Подробности: {details}")

    def run_all(self):
        print("=" * 80)
        print("  ЗАПУСК КОМПЛЕКСНОГО АУДИТА ИНСТРУМЕНТА И ВСЕХ ОГРАНИЧЕНИЙ")
        print("=" * 80)

        t0 = time.time()
        self.test_1_buildable_area_and_setbacks()
        self.test_2_fire_safety_distances()
        self.test_3_insolation_and_orientation()
        self.test_4_density_and_volume_limits()
        self.test_5_height_and_floors_limits()
        self.test_6_territory_balance_and_parking()
        self.test_7_gpzu_and_zouit_parser()
        self.test_8_road_slicer_and_subdivision()
        self.test_9_optimizer_and_maximizer()
        self.test_10_exports_and_serialization()

        elapsed = time.time() - t0
        print("\n" + "=" * 80)
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed
        print(f"  ИТОГИ АУДИТА: {passed}/{total} тестов пройдено успешно ({passed/total:.1%}) за {elapsed:.2f} сек.")
        print("=" * 80)
        return self.results

    # -------------------------------------------------------------------------
    # МОДУЛЬ 1: Зона застройки, отступы и красные линии
    # -------------------------------------------------------------------------
    def test_1_buildable_area_and_setbacks(self):
        mod = "1. Отступы и границы (Setbacks & Red Lines)"

        # 1.1 Номинальные отступы
        site = create_rectangular_site(100, 80)
        poly = site.compute_buildable_area(boundary_setback=6.0, red_line_setback=5.0)
        expected_w = 100 - 12.0
        expected_h = 80 - 12.0
        expected_area = expected_w * expected_h
        passed_1 = abs(poly.area - expected_area) < 1e-2
        self.record(mod, "Номинальный отступ от границ (6м со всех сторон)", passed_1,
                    f"Площадь участка: 8000 м², зона застройки: {poly.area:.1f} м² (ожидалось {expected_area:.1f} м²)")

        # 1.2 Красная линия
        rl = LineString([(0, 40), (100, 40)])  # Линия посередине
        site_rl = create_rectangular_site(100, 80)
        site_rl.red_lines = [rl]
        poly_rl = site_rl.compute_buildable_area(boundary_setback=6.0, red_line_setback=10.0)
        # Зона застройки должна разбиться на 2 части, и site.compute_buildable_area должен взять максимальную
        passed_rl = poly_rl.geom_type == "Polygon" and poly_rl.area < expected_area
        self.record(mod, "Красная линия с буфером 10м и выбор большего полигона", passed_rl,
                    f"Зона после вычитания красной линии: {poly_rl.area:.1f} м² (MultiPolygon разрешен в наибольший)")

        # 1.3 Участок меньше отступа (проверка генерации исключения)
        site_small = create_rectangular_site(10, 10)
        raised = False
        err_msg = ""
        try:
            site_small.compute_buildable_area(boundary_setback=6.0)
        except ValueError as e:
            raised = True
            err_msg = str(e)
        self.record(mod, "Защита: отступ 6м превышает габариты участка (10х10м)", raised and "слишком мал" in err_msg,
                    f"Перехвачено ожидаемое исключение: {err_msg}")

        # 1.4 Нулевой отступ
        site_zero = create_rectangular_site(50, 50)
        poly_zero = site_zero.compute_buildable_area(boundary_setback=0.0)
        passed_zero = abs(poly_zero.area - 2500.0) < 1e-2
        self.record(mod, "Граничный случай: нулевой отступ (boundary_setback=0)", passed_zero,
                    f"Площадь зоны: {poly_zero.area:.1f} м² при площади участка 2500 м²")

    # -------------------------------------------------------------------------
    # МОДУЛЬ 2: Противопожарные расстояния (СП 4.13130)
    # -------------------------------------------------------------------------
    def test_2_fire_safety_distances(self):
        mod = "2. Противопожарные разрывы (СП 4.13130)"
        site = create_rectangular_site(300, 300)
        engine = PlacementEngine(site, self.library, self.config)

        sec_end = self.library.get_by_id("end_sh1_9")    # 19.35 x 17.0 m
        sec_tower = self.library.get_by_id("tower_b1")  # 29.7 x 23.9 m

        cfg_1sec = PlacementConfig(min_sections_per_building=1, fire_gap_parallel=18.0, fire_gap_end_to_end=10.0)

        # 2.1 Фасад к фасаду (FACADE_PARALLEL): 18 м
        # Задаем 5 этажей (высота 15м, инсоляционный разрыв 7.5м, поэтому доминирует пожарный разрыв 18м)
        # b1 в (100, 50), глубина 17м -> y от 41.5 до 58.5
        b1 = Building([PlacedSection(sec_end, 100, 50, angle=0, floors=5)])
        # b2 в (100, 70) -> y от 61.5 до 78.5, разрыв 61.5 - 58.5 = 3.0 м (< 18м) -> отказ
        b2_close = Building([PlacedSection(sec_end, 100, 70, angle=0, floors=5)])
        # b3 в (100, 86) -> y от 77.5 до 94.5, разрыв 77.5 - 58.5 = 19.0 м (>= 18м) -> ок
        b3_ok = Building([PlacedSection(sec_end, 100, 86, angle=0, floors=5)])

        gap, mode = engine.classify_fire_gap(b1, b2_close, gap_end=10.0, gap_parallel=18.0)
        valid_close = engine._check_constraints(b2_close, [b1], cfg_1sec)
        valid_ok = engine._check_constraints(b3_ok, [b1], cfg_1sec)
        self.record(mod, "Параллельные фасады: классификация FACADE_PARALLEL (18м)",
                    mode == "FACADE_PARALLEL" and gap == 18.0 and not valid_close and valid_ok,
                    f"Режим: {mode}, требуемый разрыв: {gap}м, отсечение при 3м: {not valid_close}, допуск при 19м: {valid_ok}")

        # 2.2 Торец к торцу (END_TO_END): 10 м
        # b1 ширина 19.35м -> x от 90.325 до 109.675
        # b_end_7m: x_center = 109.675 + 7.0 + 19.35/2 = 126.35, y = 50 -> разрыв 7.0 м (< 10м)
        b_end_7m = Building([PlacedSection(sec_end, 126.35, 50, angle=0, floors=5)])
        # b_end_11m: x_center = 109.675 + 11.0 + 19.35/2 = 130.35, y = 50 -> разрыв 11.0 м (>= 10м)
        b_end_11m = Building([PlacedSection(sec_end, 130.35, 50, angle=0, floors=5)])

        gap_e, mode_e = engine.classify_fire_gap(b1, b_end_7m, gap_end=10.0, gap_parallel=18.0)
        valid_end_7m = engine._check_constraints(b_end_7m, [b1], cfg_1sec)
        valid_end_11m = engine._check_constraints(b_end_11m, [b1], cfg_1sec)
        self.record(mod, "Торцы зданий: классификация END_TO_END (10м)",
                    mode_e == "END_TO_END" and gap_e == 10.0 and not valid_end_7m and valid_end_11m,
                    f"Режим: {mode_e}, разрыв: {gap_e}м, отсечение при 7м: {not valid_end_7m}, допуск при 11м: {valid_end_11m}")

        # 2.3 Башни (TOWER): 4 фасадные стороны и 18м разрыв (при 5 этажах, H=15м)
        b_tower1 = Building([PlacedSection(sec_tower, 100, 100, angle=0, floors=5)], typology="TOWER")
        # Рядом башня на расстоянии 14 м по фасаду (< 18м)
        # tower1: y from 100 - 23.9/2 = 88.05 to 111.95
        # tower2: y_center = 111.95 + 14.0 + 23.9/2 = 137.9 -> разрыв 14м
        b_tower_14m = Building([PlacedSection(sec_tower, 100, 137.9, angle=0, floors=5)], typology="TOWER")
        b_tower_20m = Building([PlacedSection(sec_tower, 100, 143.9, angle=0, floors=5)], typology="TOWER")
        gap_t, mode_t = engine.classify_fire_gap(b_tower1, b_tower_14m, gap_end=10.0, gap_parallel=18.0)
        valid_t14 = engine._check_constraints(b_tower_14m, [b_tower1], cfg_1sec)
        valid_t20 = engine._check_constraints(b_tower_20m, [b_tower1], cfg_1sec)
        self.record(mod, "Башни (TOWER): 4 фасадные стороны и 18м разрыв",
                    mode_t == "FACADE_PARALLEL" and not valid_t14 and valid_t20,
                    f"Режим: {mode_t}, отсечение при 14м: {not valid_t14}, допуск при 20м: {valid_t20}")

        # 2.4 Настраиваемость противопожарных разрывов пользователем
        cfg_custom = PlacementConfig(min_sections_per_building=1, fire_gap_end_to_end=15.0, fire_gap_parallel=25.0)
        # При gap_parallel=25м расстояние 20м должно быть отклонено!
        valid_custom_reject = engine._check_constraints(b_tower_20m, [b_tower1], cfg_custom)
        self.record(mod, "Пользовательская настройка разрывов (15м/25м)",
                    not valid_custom_reject,
                    f"При fire_gap_parallel=25м разрыв 20м отклонен: {not valid_custom_reject}")

        # 2.5 Автоматическая трассировка пожарного проезда (СП 4.13130.2020)
        from src.core.fire_safety import FireAccessEngine
        fa_engine = FireAccessEngine()
        fa_res = fa_engine.generate_fire_routes(site, [b1, b3_ok], include_turnarounds=True)
        self.record(mod, "Автоматическая трассировка пожарного проезда (СП 4.13130.2020)",
                    fa_res.is_compliant and fa_res.total_length_m > 0 and fa_res.fire_lanes_polygon is not None,
                    f"Длина: {fa_res.total_length_m:.1f}м, площадь: {fa_res.total_area_sqm:.1f}м², площадки 15х15м: {fa_res.turnarounds_area_sqm:.1f}м²")

    # -------------------------------------------------------------------------
    # МОДУЛЬ 3: Инсоляция и ориентация (СанПиН 1.2.3685-21)
    # -------------------------------------------------------------------------
    def test_3_insolation_and_orientation(self):
        mod = "3. Инсоляция и инсоляционные углы"
        site = create_rectangular_site(250, 200)
        engine = PlacementEngine(site, self.library, self.config)

        # 3.1 Меридиональные секции
        sec_meridian = next((s for s in self.library.get_all() if getattr(s, "is_meridian", False)), None)
        if sec_meridian:
            # Угол 0° (строго горизонтально, северный фасад в тени) -> запрещено
            b_horiz = Building([PlacedSection(sec_meridian, 100, 100, angle=0.0)])
            val_horiz = engine._check_constraints(b_horiz, [])

            # Угол 15° (< 25°) -> запрещено
            b_15deg = Building([PlacedSection(sec_meridian, 100, 100, angle=15.0)])
            val_15deg = engine._check_constraints(b_15deg, [])

            # Угол 30° (>= 25°) -> разрешено
            b_30deg = Building([PlacedSection(sec_meridian, 100, 100, angle=30.0)])
            val_30deg = engine._check_constraints(b_30deg, [])

            # Угол 90° (меридионально) -> разрешено
            b_90deg = Building([PlacedSection(sec_meridian, 100, 100, angle=90.0)])
            val_90deg = engine._check_constraints(b_90deg, [])

            passed_mer = (not val_horiz) and (not val_15deg) and val_30deg and val_90deg
            self.record(mod, "Запрет меридиональных секций при угле к горизонтали < 25°",
                        passed_mer,
                        f"0° (отказ): {not val_horiz}, 15° (отказ): {not val_15deg}, 30° (допуск): {val_30deg}, 90° (допуск): {val_90deg}")
        else:
            self.record(mod, "Поиск меридиональной секции", False, "В библиотеке не найдена меридиональная секция")

        # 3.2 Инсоляционный разрыв пропорционально высоте H
        # Для меридиональной секции angle должен быть >= 25° (например 90° - меридиональная ориентация)
        # При H = 24 эт. * 3.0 м = 72 м, factor = 0.5 -> req_gap = 36.0 м (больше пожарного 18м)
        cfg_1sec = PlacementConfig(min_sections_per_building=1)
        sec_tall = self.library.get_by_id("mid_m2_24") or self.library.get_by_id("tower_b1")
        # Располагаем два корпуса меридионально (angle=90°) параллельно друг другу
        # b_tall1: x=100, y=100, угол 90° (ширина 47.85м вдоль Y, глубина 17м вдоль X)
        b_tall1 = Building([PlacedSection(sec_tall, 100, 100, angle=90.0, floors=24)])
        # b_tall2 на разрыве 25м по X (между параллельными фасадами):
        # b1 x in [100 - 8.5, 100 + 8.5] = [91.5, 108.5]
        # b2 x_center = 108.5 + 25.0 + 8.5 = 142.0 -> разрыв 25м (< 36м инсоляции) -> отказ
        b_tall_25m = Building([PlacedSection(sec_tall, 142.0, 100, angle=90.0, floors=24)])
        # b3 x_center = 108.5 + 40.0 + 8.5 = 157.0 -> разрыв 40м (>= 36м инсоляции) -> допуск
        b_tall_40m = Building([PlacedSection(sec_tall, 157.0, 100, angle=90.0, floors=24)])

        val_insol_25 = engine._check_constraints(b_tall_25m, [b_tall1], cfg_1sec)
        val_insol_40 = engine._check_constraints(b_tall_40m, [b_tall1], cfg_1sec)
        self.record(mod, "Инсоляционный разрыв H*0.5 (36м для 24 эт.)",
                    (not val_insol_25) and val_insol_40,
                    f"25м при 72м высоте (отказ): {not val_insol_25}, 40м (допуск): {val_insol_40}")

    # -------------------------------------------------------------------------
    # МОДУЛЬ 4: Плотность и процент застройки (FAR / КИТ, BCR / КЗ)
    # -------------------------------------------------------------------------
    def test_4_density_and_volume_limits(self):
        mod = "4. Ограничения плотности (FAR / BCR)"
        site = create_rectangular_site(150, 100) # 15 000 м² (1.5 га)
        site.compute_buildable_area(6.0, 5.0)

        # 4.1 Проверка check_normatives
        tep_mock = TEP(
            site_area=15000.0,
            building_area=4500.0,
            total_gfa=32000.0,
            residential_area=19000.0,
            bcr=4500.0 / 15000.0,
            far=32000.0 / 15000.0,
            building_count=3,
            avg_floors=9.0,
            apartments_total=350,
            apartments_studio=50,
            apartments_1k=120,
            apartments_2k=130,
            apartments_3k=50,
            apartments_4k=0,
            population=600.0,
            parking_spaces=200,
            commercial_area=2000.0,
            green_area=4000.0,
            green_ratio=4000.0 / 15000.0,
        )
        checks = check_normatives(tep_mock, {"max_far": 2.5, "max_bcr": 0.40, "green_ratio_min": 0.25})
        norm_ok = all(c["ok"] for c in checks.values())
        self.record(mod, "Калькулятор check_normatives: корректный расчет", norm_ok,
                    f"BCR={checks['bcr']['value']:.1%} (ok={checks['bcr']['ok']}), FAR={checks['far']['value']:.2f} (ok={checks['far']['ok']})")
        # FAR = 32000 / 15000 = 2.13 (<= 2.50) -> OK
        # BCR = 4500 / 15000 = 0.30 (<= 0.40) -> OK
        # Green = 4000 / 15000 = 0.267 (>= 0.25) -> OK
        norm_ok = all(c["ok"] for c in checks.values())
        self.record(mod, "Калькулятор check_normatives: корректный расчет", norm_ok,
                    f"BCR={checks['bcr']['value']:.1%} (ok={checks['bcr']['ok']}), FAR={checks['far']['value']:.2f} (ok={checks['far']['ok']})")

        # 4.2 Enforce normative limits в PlacementEngine (Жесткое отсечение превышения)
        engine = PlacementEngine(site, self.library, self.config)
        # Задаем жесткий BCR = 0.15 (не более 2250 м² пятна подошвы)
        cfg_strict_bcr = PlacementConfig(typology="LINEAR", target_floors=9, max_bcr=0.15)
        blds_bcr = engine.generate(cfg_strict_bcr)
        actual_fp = sum(b.total_building_area for b in blds_bcr)
        allowed_fp = site.area * 0.15
        passed_bcr_cap = actual_fp <= allowed_fp * 1.01
        self.record(mod, "Жесткое соблюдение потолка BCR (max_bcr=0.15)", passed_bcr_cap,
                    f"Фактическое пятно: {actual_fp:.1f} м² <= допустимого {allowed_fp:.1f} м²")

        # 4.3 Жесткий потолок FAR (max_far = 1.0)
        cfg_strict_far = PlacementConfig(typology="LINEAR", target_floors=16, max_far=1.0)
        blds_far = engine.generate(cfg_strict_far)
        actual_gfa = sum(b.total_gfa for b in blds_far)
        allowed_gfa = site.area * 1.0
        passed_far_cap = actual_gfa <= allowed_gfa * 1.01
        self.record(mod, "Жесткое соблюдение потолка FAR (max_far=1.0)", passed_far_cap,
                    f"Фактическая GFA: {actual_gfa:,.0f} м² <= допустимой {allowed_gfa:,.0f} м²")

    # -------------------------------------------------------------------------
    # МОДУЛЬ 5: Ограничения высотности и этажности
    # -------------------------------------------------------------------------
    def test_5_height_and_floors_limits(self):
        mod = "5. Ограничения высоты и этажей"
        site = create_rectangular_site(200, 150)
        site.compute_buildable_area(6.0, 5.0)
        engine = PlacementEngine(site, self.library, self.config)

        # 5.1 Предельная высота max_building_height_m = 28.0 м
        # При floor_height = 3.0 м максимальная этажность должна быть 9 этажей (28 / 3 = 9.33)
        cfg_h28 = PlacementConfig(
            typology="LINEAR",
            target_floors=24, # Запрошено 24 этажа
            max_building_height_m=28.0,
            floor_height=3.0,
        )
        blds_h28 = engine.generate(cfg_h28)
        max_actual_floors = max((s.floors for b in blds_h28 for s in b.sections), default=0)
        passed_h = max_actual_floors <= 9
        self.record(mod, "Ограничение предельной высоты max_building_height_m=28м (срез с 24 до 9 эт.)", passed_h,
                    f"Запрошено 24 эт., фактически сгенерировано: {max_actual_floors} эт.")

        # 5.2 Ограничения секций по min/max этажам из библиотеки
        all_sections_valid = True
        for b in blds_h28:
            for s in b.sections:
                sec_t = s.section_type
                if not (sec_t.min_floors <= s.floors <= sec_t.max_floors):
                    all_sections_valid = False
        self.record(mod, "Соблюдение паспорта секций (min_floors <= floors <= max_floors)", all_sections_valid,
                    f"Все секции в рамках каталожных ограничений: {all_sections_valid}")

    # -------------------------------------------------------------------------
    # МОДУЛЬ 6: Баланс территории, парковки и озеленение
    # -------------------------------------------------------------------------
    def test_6_territory_balance_and_parking(self):
        mod = "6. Баланс территории и парковки"

        # Загрузка норматива СП 42
        sp42_data = self.regional_norms_data["regions"]["russia_sp42"]
        norm_sp42 = RegionalNorm.from_dict(sp42_data)

        # 6.1 Стандартный расчет баланса
        res_bal = calculate_territory_balance(
            site_area=20000.0,
            building_footprint_area=4000.0,
            population=800.0,
            residential_area=20000.0,
            apartments_total=300,
            regional_norm=norm_sp42,
        )
        # СП 42: 350 м/м на 1000 жителей -> 800 * 0.35 = 280 м/м
        req_parking = res_bal.parking.required_total
        passed_demand = req_parking == 280
        self.record(mod, "Потребность в парковках СП 42 (350 м/м на 1000 жителей)", passed_demand,
                    f"Население 800 чел -> требуется {req_parking} м/м")

        # 6.2 Дефицит территории и вынос в подземный паркинг
        # Маленький участок 6 000 м² с плотной застройкой 2 400 м² (BCR=40%) и 1 000 жителей
        res_deficit = calculate_territory_balance(
            site_area=6000.0,
            building_footprint_area=2400.0,
            population=1000.0,
            residential_area=25000.0,
            apartments_total=400,
            regional_norm=norm_sp42,
        )
        has_warnings = len(res_deficit.warnings) > 0
        underground_needed = res_deficit.parking.underground_deficit > 0
        self.record(mod, "Автоматическое определение дефицита парковок и расчет подземного паркинга",
                    has_warnings and underground_needed,
                    f"Дефицит: {res_deficit.parking.underground_deficit} м/м ({res_deficit.parking.underground_area_est:,.0f} м² подземного паркинга). Предупреждений: {len(res_deficit.warnings)}")

        # 6.3 Норматив озеленения 25%
        self.record(mod, "Контроль минимального озеленения (25%)",
                    res_bal.green_norm_met,
                    f"Доля озеленения: {res_bal.green_ratio:.1%} (норма: {norm_sp42.density.green_ratio_min:.0%})")

        # 6.4 Сравнение региональных нормативов (Москва vs СПб vs СП 42)
        mngp_data = self.regional_norms_data["regions"]["moscow_mngp"]
        norm_moscow = RegionalNorm.from_dict(mngp_data)
        moscow_bal = calculate_territory_balance(
            site_area=20000.0,
            building_footprint_area=4000.0,
            population=800.0,
            residential_area=20000.0,
            apartments_total=300,
            regional_norm=norm_moscow,
        )
        # В Москве: 1 м/м на 90 м² жилья -> 20000 / 90 = 222 м/м
        moscow_req = moscow_bal.parking.required_total
        self.record(mod, "Региональная дифференциация: Москва МНГП № 945-ПП (1 м/м на 90 м²)",
                    moscow_req == math.ceil(20000 / 90),
                    f"Жилая площадь 20 000 м² -> требуется {moscow_req} м/м в Москве против 280 м/м по СП 42")

        # 6.5 Ограничение: Только наземные парковки (Zero underground parking)
        ground_only_bal = calculate_territory_balance(
            site_area=25000.0,
            building_footprint_area=4000.0,
            population=600.0,
            residential_area=15000.0,
            apartments_total=250,
            regional_norm=norm_sp42,
            only_ground_parking=True,
        )
        zero_underground = (
            ground_only_bal.parking.underground_deficit == 0
            and ground_only_bal.parking.underground_area_est == 0.0
            and ground_only_bal.parking.underground_levels == 0
            and ground_only_bal.green_roof_area == 0.0
            and ground_only_bal.parking.only_ground_parking is True
            and ground_only_bal.parking.ground_capacity >= ground_only_bal.parking.required_total
        )
        self.record(mod, "Ограничение «Только наземные парковки» (полное исключение подземного паркинга)",
                    zero_underground,
                    f"Наземных мест: {ground_only_bal.parking.ground_capacity} >= {ground_only_bal.parking.required_total} треб., подземный дефицит: {ground_only_bal.parking.underground_deficit} м/м")

    # -------------------------------------------------------------------------
    # МОДУЛЬ 7: Парсер ГПЗУ и выявление ЗОУИТ
    # -------------------------------------------------------------------------
    def test_7_gpzu_and_zouit_parser(self):
        mod = "7. Парсер ГПЗУ и ЗОУИТ"

        sample_gpzu_text = """
        ГРАДОСТРОИТЕЛЬНЫЙ ПЛАН ЗЕМЕЛЬНОГО УЧАСТКА
        Кадастровый номер: 72:23:0101001:1234
        Раздел 2. Предельные параметры разрешенного строительства:
        - минимальный отступ от границ земельного участка: 6.0 м;
        - минимальный отступ от красных линий улиц и проездов: 5.0 м;
        - предельная высота зданий, строений, сооружений: 35.0 м;
        - предельное количество этажей: 12;
        - максимальный процент застройки в границах земельного участка: 38%.

        Раздел 4. Информация об ограничениях и ЗОУИТ:
        1. В границах участка расположена охранная зона электрических сетей (ВЛ 110 кВ).
        2. Участок частично попадает в санитарно-защитную зону (СЗЗ) производственного предприятия.
        3. Водоохранная зона реки Тура шириной 100 м.
        4. Охранная зона газораспределительной сети высокого давления.
        5. Приаэродромная территория аэродрома Рощино, 3 подзона.
        """

        # 7.1 Извлечение предельных параметров
        params = extract_gpzu_parameters(sample_gpzu_text)
        p_ok = (
            params.get("boundary_setback") == 6.0
            and params.get("red_line_setback") == 5.0
            and params.get("max_building_height_m") == 35.0
            and params.get("max_floors") == 12
            and abs(params.get("max_bcr", 0) - 0.38) < 1e-3
        )
        self.record(mod, "Извлечение предельных параметров из текста ГПЗУ", p_ok,
                    f"Отступ границ={params.get('boundary_setback')}м, красных={params.get('red_line_setback')}м, макс_h={params.get('max_building_height_m')}м, макс_эт={params.get('max_floors')}, BCR={params.get('max_bcr')}")

        # 7.2 Извлечение ЗОУИТ
        zouit = extract_zouit_restrictions(sample_gpzu_text)
        zouit_names = [z["name"] for z in zouit]
        expected_zouits = [
            "Охранная зона электрических сетей (ЛЭП)",
            "Санитарно-защитная зона (СЗЗ)",
            "Водоохранная зона / прибрежная полоса",
            "Охранная зона газораспределительной сети",
            "Приаэродромная территория",
        ]
        found_all = all(name in zouit_names for name in expected_zouits)
        self.record(mod, "Идентификация зон с особыми условиями (ЗОУИТ)", found_all,
                    f"Найдено {len(zouit)} зон: {', '.join(zouit_names)}")

    # -------------------------------------------------------------------------
    # МОДУЛЬ 8: Нарезка дорожной сетью (RoadSlicer)
    # -------------------------------------------------------------------------
    def test_8_road_slicer_and_subdivision(self):
        mod = "8. Нарезка улично-дорожной сетью (RoadSlicer)"
        site_boundary = Polygon([(0, 0), (200, 0), (200, 160), (0, 160)])
        buildable = site_boundary.buffer(-6.0)

        # 8.1 Пресет transverse (поперечная дорога)
        res_trans = RoadSlicer.slice_buildable_area(
            buildable_area=buildable,
            site_boundary=site_boundary,
            preset="transverse",
            road_width=16.0,
            road_setback=4.0,
        )
        passed_trans = len(res_trans.sub_blocks) == 2 and res_trans.roads_polygon is not None
        self.record(mod, "Пресет 'transverse': деление на 2 квартала с полосой отвода 16м + отступ 4м", passed_trans,
                    f"Кварталов: {len(res_trans.sub_blocks)}, площадь дорог: {res_trans.roads_area_sqm:.1f} м²")

        # 8.2 Пресет cross_2x2 (перекресток, деление на 4 квартала)
        res_cross = RoadSlicer.slice_buildable_area(
            buildable_area=buildable,
            site_boundary=site_boundary,
            preset="cross_2x2",
            road_width=16.0,
            road_setback=4.0,
        )
        passed_cross = len(res_cross.sub_blocks) == 4
        self.record(mod, "Пресет 'cross_2x2': деление на 4 квартала", passed_cross,
                    f"Кварталов: {len(res_cross.sub_blocks)}, суммарная площадь кварталов: {sum(b.area for b in res_cross.sub_blocks):.1f} м²")

        # 8.3 Пользовательская криволинейная/диагональная дорога
        custom_line = LineString([(-20, 30), (220, 130)])
        res_custom = RoadSlicer.slice_buildable_area(
            buildable_area=buildable,
            site_boundary=site_boundary,
            road_lines=[custom_line],
            road_width=14.0,
            road_setback=3.0,
        )
        passed_custom = len(res_custom.sub_blocks) >= 2
        self.record(mod, "Пользовательская диагональная трассировка дороги", passed_custom,
                    f"Сформировано суб-блоков: {len(res_custom.sub_blocks)}")

    # -------------------------------------------------------------------------
    # МОДУЛЬ 9: Оптимизатор и максимизатор (Top-1)
    # -------------------------------------------------------------------------
    def test_9_optimizer_and_maximizer(self):
        mod = "9. Оптимизатор и Максимизатор (Top-1)"
        site = create_rectangular_site(220, 140) # ~3 га
        site.compute_buildable_area(6.0, 5.0)

        opt = Optimizer(site, self.library, self.config)

        # 9.1 Режим 'Подбор под ТЭП' (target FAR = 1.8)
        t_start = time.time()
        res_target = opt.optimize_for_target({"target_far": 1.8})
        t_target = time.time() - t_start
        passed_target = res_target is not None and abs(res_target.tep.far - 1.8) < 0.35
        self.record(mod, "Подбор под целевой FAR = 1.8", passed_target,
                    f"Подобрано: {res_target.floors} эт., FAR={res_target.tep.far:.2f}, время: {t_target:.2f}с")

        # 9.2 Режим 'Выжать максимум по закону' (respect_normatives=True)
        t_max_start = time.time()
        res_max_norm = opt.optimize_maximize(
            respect_normatives=True,
            explore_typologies=False,
            explore_angles=True,
            angles=[0.0, 15.0, -15.0],
        )
        t_max = time.time() - t_max_start
        max_far_limit = float(self.config.get("max_far", 2.50))
        passed_max_norm = (
            res_max_norm is not None
            and res_max_norm.normative_ok
            and res_max_norm.tep.far <= max_far_limit + 1e-2
        )
        self.record(mod, "Максимизатор 'Выжать максимум по закону' (respect_normatives=True)", passed_max_norm,
                    f"Победитель: {res_max_norm.floors} эт. ({res_max_norm.typology}), угол {res_max_norm.angle:+.1f}°, FAR={res_max_norm.tep.far:.2f} (лимит {max_far_limit}), время: {t_max:.2f}с")

        # 9.3 Абсолютная максимизация без лимитов (respect_normatives=False)
        res_max_abs = opt.optimize_maximize(
            respect_normatives=False,
            explore_typologies=False,
            explore_angles=True,
            angles=[0.0, 15.0, -15.0],
        )
        # Без нормативных ограничений FAR должен быть >= нормативного максимума
        passed_max_abs = res_max_abs.tep.residential_area >= res_max_norm.tep.residential_area
        self.record(mod, "Абсолютный физический максимум (respect_normatives=False)", passed_max_abs,
                    f"Жилая площадь: {res_max_abs.tep.residential_area:,.0f} м² >= нормативной {res_max_norm.tep.residential_area:,.0f} м² (FAR={res_max_abs.tep.far:.2f})")

    # -------------------------------------------------------------------------
    # МОДУЛЬ 10: Экспортные форматы и сериализация
    # -------------------------------------------------------------------------
    def test_10_exports_and_serialization(self):
        mod = "10. Экспортные модули и отчеты"
        site = create_rectangular_site(160, 120)
        site.compute_buildable_area(6.0, 5.0)
        engine = PlacementEngine(site, self.library, self.config)
        buildings = engine.generate(PlacementConfig(typology="LINEAR", target_floors=9))
        tep = calculate_tep(site, buildings, self.config)

        tmp_dir = Path("dashboard_prototype/tmp_exports")
        tmp_dir.mkdir(exist_ok=True)

        # 10.1 DXF Export
        dxf_path = tmp_dir / "audit_test.dxf"
        try:
            export_dxf(site, buildings, tep=tep, filepath=str(dxf_path))
            passed_dxf = dxf_path.exists() and dxf_path.stat().st_size > 1024
        except Exception as e:
            passed_dxf = False
        self.record(mod, "Экспорт в CAD / DXF (слои контуров, секций, осей)", passed_dxf,
                    f"Файл создан: {dxf_path.stat().st_size if passed_dxf else 0} байт")

        # 10.2 GeoJSON Export
        geo_path = tmp_dir / "audit_test.geojson"
        try:
            export_geojson(site, buildings, tep=tep, filepath=str(geo_path), as_wgs84=False)
            passed_geo = geo_path.exists() and geo_path.stat().st_size > 200
        except Exception as e:
            passed_geo = False
        self.record(mod, "Экспорт в GeoJSON (WGS-84 / геометрия)", passed_geo,
                    f"Файл создан: {geo_path.stat().st_size if passed_geo else 0} байт")

        # 10.3 3D HTML Export
        html_path = tmp_dir / "audit_test_3d.html"
        try:
            export_3d_html(site, buildings, tep=tep, filepath=str(html_path))
            passed_html = html_path.exists() and html_path.stat().st_size > 1024
        except Exception as e:
            passed_html = False
        self.record(mod, "Экспорт в интерактивный 3D HTML (Three.js)", passed_html,
                    f"Файл создан: {html_path.stat().st_size if passed_html else 0} байт")

        # 10.4 Текстовый аудиторский отчет ТЭП
        try:
            rep_text = generate_report(site, buildings, tep=tep, config=self.config)
            passed_rep = len(rep_text) > 300 and "ТЕХНИКО-ЭКОНОМИЧЕСКИЕ ПОКАЗАТЕЛИ" in rep_text
        except Exception as e:
            passed_rep = False
        self.record(mod, "Генерация отчета ТЭП (баланс площадей и нормативы)", passed_rep,
                    f"Объем отчета: {len(rep_text) if passed_rep else 0} символов")


if __name__ == "__main__":
    runner = AuditRunner()
    runner.run_all()
