"""Тестовый скрипт — полный пайплайн генератора застройки.

Создаёт прямоугольный участок, загружает секции, генерирует
расстановку и выводит ТЭП.
"""

import sys
import os
from pathlib import Path

# Кодировка UTF-8 для Windows-консоли
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from src.core.site_parser import create_rectangular_site
from src.core.buildable_area import compute_buildable_area, get_obb_dimensions
from src.core.placement import PlacementConfig, PlacementEngine
from src.core.tep_calculator import calculate_tep, check_normatives, format_normative_check
from src.core.optimizer import Optimizer
from src.core.regional_norms import get_regional_norm
from src.core.territory_balance import calculate_territory_balance
from src.library.section_library import SectionLibrary
from src.visualization.plotter import plot_site_plan
from src.export.report import generate_report


def main():
    print("=" * 60)
    print("  ГЕНЕРАТОР ЗАСТРОЙКИ ПО ТЭП — ТЕСТОВЫЙ ЗАПУСК")
    print("=" * 60)
    print()

    # 1. Загрузка конфигурации
    config_path = PROJECT_ROOT / "config" / "defaults.yaml"
    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    print(f"✓ Конфигурация загружена из {config_path.name}")

    # 2. Загрузка библиотеки секций
    library = SectionLibrary(PROJECT_ROOT / "config" / "sections")
    print(f"✓ {library}")

    for section in library.get_all():
        print(f"  • {section}")

    # 3. Создание тестового участка (200 × 150 м)
    site = create_rectangular_site(200, 150)
    print(f"\n✓ Участок создан: {site}")

    # 4. Вычисление зоны застройки
    compute_buildable_area(site, config)
    print(f"✓ Зона застройки: {site.buildable_area.area:.0f} м²")

    # 5. Габариты участка
    length, width, angle = get_obb_dimensions(site.buildable_area)
    print(f"  Ориентированный ОВВ: {length:.0f} × {width:.0f} м, угол: {angle:.1f}°")

    # 6. Генерация расстановки
    print("\n--- Режим 1: Заданная этажность (17 эт.) ---")
    engine = PlacementEngine(site, library, config)
    placement_cfg = PlacementConfig(target_floors=17)
    buildings = engine.generate(placement_cfg)
    print(f"✓ Размещено зданий: {len(buildings)}")

    for i, b in enumerate(buildings):
        print(f"  Дом {i+1}: {b}")

    # 7. Расчёт ТЭП
    tep = calculate_tep(site, buildings, config)
    print(f"\n{tep.to_table_str()}")

    # 8. Проверка нормативов
    checks = check_normatives(tep, config)
    print(f"\n{format_normative_check(checks)}")

    # 9. Визуализация
    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(exist_ok=True)

    fig = plot_site_plan(
        site, buildings, tep,
        title="Тестовая застройка 200×150 м, 17 эт.",
        save_path=output_dir / "test_plan.png",
    )
    print(f"\n✓ План сохранён: {output_dir / 'test_plan.png'}")

    # 10. Градостроительный баланс территории и отчёт
    reg_norm = get_regional_norm("russia_sp42")
    balance = calculate_territory_balance(
        site_area=site.area,
        building_footprint_area=tep.building_area,
        population=tep.population,
        residential_area=tep.residential_area,
        apartments_total=tep.apartments_total,
        regional_norm=reg_norm,
    )
    print(f"\n✓ Градостроительный баланс территории ({balance.regional_norm_name}):")
    print(f"  • Машиномест по норме:      {balance.parking.required_total} м/м")
    print(f"  • Наземная емкость участка: {balance.parking.ground_capacity} м/м")
    print(f"  • Дефицит (в подземный):    {balance.parking.underground_deficit} м/м (~{balance.parking.underground_area_est:,.0f} м²)")
    print(f"  • Дворовые площадки всего:  {balance.playgrounds.total:,.0f} м² (дети: {balance.playgrounds.children:,.0f} м², спорт: {balance.playgrounds.sport:,.0f} м²)")

    report = generate_report(
        site, buildings, tep, config,
        output_dir / "test_report.txt",
        balance=balance,
    )
    print(f"✓ Отчёт сохранён: {output_dir / 'test_report.txt'}")

    # 11. Оптимизация — максимизация
    print("\n--- Режим 2: Максимизация площади ---")
    optimizer = Optimizer(site, library, config)
    best = optimizer.optimize_maximize()
    print(f"✓ Лучший вариант: {best.floors} эт., "
          f"FAR={best.tep.far:.2f}, {best.tep.apartments_total} кв.")
    print(f"  Нормативы: {'✓' if best.normative_ok else '✗'}")

    # 12. Сравнение вариантов
    print("\n--- Сравнение вариантов ---")
    variants = optimizer.generate_variants()
    print(optimizer.compare_variants(variants))

    print("\n✓ Тест завершён успешно!")


if __name__ == "__main__":
    main()
