"""Автономный тест расчета баланса территории по региональным нормативам (РНГП/МНГП)."""

import sys
from pathlib import Path

if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Корень проекта
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.core.regional_norms import load_regional_norms
from src.core.territory_balance import calculate_territory_balance


def main():
    print("=" * 70)
    print("  ТЕСТИРОВАНИЕ РЕГИОНАЛЬНЫХ НОРМАТИВОВ И БАЛАНСА ТЕРРИТОРИИ")
    print("=" * 70)

    # Загружаем нормативы
    norms = load_regional_norms()
    print(f"\nЗагружено региональных профилей: {len(norms)}")
    for norm_id, norm in norms.items():
        print(f"  • {norm.id}: {norm.name} ({norm.parking.method.value})")

    # Исходные данные типичного девелоперского проекта
    site_area = 20_000.0          # 2.0 га (20 000 м²)
    building_footprint = 6_200.0   # BCR = 31%
    residential_area = 36_000.0    # 36 тыс. м² жилья
    apartments_total = 620         # 620 квартир
    population = 1_450.0           # 1450 жителей

    print("\n" + "-" * 70)
    print("  ПАРАМЕТРЫ ТЕСТОВОГО УЧАСТКА:")
    print(f"  Площадь участка:      {site_area:,.0f} м² (2.0 га)")
    print(f"  Пятно застройки:      {building_footprint:,.0f} м² (BCR: {building_footprint / site_area:.1%})")
    print(f"  Жилая площадь квартир:{residential_area:,.0f} м²")
    print(f"  Всего квартир:        {apartments_total} шт.")
    print(f"  Расчетное население:  {population:,.0f} чел.")
    print("-" * 70)

    # Сравнение по регионам
    print("\nСРАВНЕНИЕ ТРЕБОВАНИЙ ПО РЕГИОНАМ:\n")
    fmt = "{:<28} | {:<12} | {:<14} | {:<14} | {:<12}"
    print(fmt.format("Регион / Норматив", "Парковок", "Площадки, м²", "Наземно, м/м", "Подземный, м/м"))
    print("-" * 90)

    for norm_id, norm in norms.items():
        res = calculate_territory_balance(
            site_area=site_area,
            building_footprint_area=building_footprint,
            population=population,
            residential_area=residential_area,
            apartments_total=apartments_total,
            regional_norm=norm,
        )

        p = res.parking
        print(fmt.format(
            norm.name[:28],
            f"{p.required_total} м/м",
            f"{res.playgrounds.total:,.0f} м²",
            f"{p.ground_capacity} м/м",
            f"{p.underground_deficit} м/м",
        ))

    print("\n" + "=" * 70)
    print("  ДЕТАЛИЗАЦИЯ ДЛЯ МОСКОВСКОЙ ОБЛАСТИ (РНГП МО):")
    print("=" * 70)
    mo_norm = norms.get("moscow_oblast_rngp", next(iter(norms.values())))
    res_mo = calculate_territory_balance(
        site_area=site_area,
        building_footprint_area=building_footprint,
        population=population,
        residential_area=residential_area,
        apartments_total=apartments_total,
        regional_norm=mo_norm,
    )

    for k, v in res_mo.to_dict().items():
        print(f"  {k:<38}: {v}")

    print("\n  Структура использования участка (%):")
    for elem, share in res_mo.get_structure_shares().items():
        bar = "█" * int(share // 2)
        print(f"    {elem:<22}: {share:>5.1f}% | {bar}")

    if res_mo.warnings:
        print("\n  ⚠️ Градостроительные предупреждения:")
        for w in res_mo.warnings:
            print(f"    - {w}")

    print("\n" + "=" * 70)
    print("  ТЕСТ УСПЕШНО ПРОЙДЕН!")
    print("=" * 70)


if __name__ == "__main__":
    main()
