"""Генерация текстового отчёта ТЭП.

Формирует подробный текстовый отчёт с ТЭП и квартирографией.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import datetime

from src.models.building import Building
from src.models.site import Site
from src.models.tep import TEP
from src.core.tep_calculator import check_normatives, format_normative_check


def generate_report(
    site: Site,
    buildings: list[Building],
    tep: TEP,
    config: dict[str, Any],
    filepath: str | Path | None = None,
) -> str:
    """Сгенерировать текстовый отчёт.

    Args:
        site: Участок.
        buildings: Здания.
        tep: ТЭП.
        config: Конфигурация.
        filepath: Путь для сохранения (опционально).

    Returns:
        Текст отчёта.
    """
    lines: list[str] = []

    # Шапка
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    lines.append("╔" + "═" * 58 + "╗")
    lines.append("║  ОТЧЁТ: ГЕНЕРАТОР ЗАСТРОЙКИ ПО ТЭП" + " " * 21 + "║")
    lines.append("║  Дата: " + now + " " * (50 - len(now)) + "║")
    lines.append("╚" + "═" * 58 + "╝")
    lines.append("")

    # ТЭП
    lines.append(tep.to_table_str())
    lines.append("")

    # Проверка нормативов
    checks = check_normatives(tep, config)
    lines.append(format_normative_check(checks))
    lines.append("")

    # Квартирография по зданиям
    lines.append("=" * 60)
    lines.append("  КВАРТИРОГРАФИЯ ПО ЗДАНИЯМ")
    lines.append("=" * 60)

    for i, building in enumerate(buildings):
        apts = building.total_apartments
        total = sum(apts.values())
        lines.append(f"\n  Дом {i + 1}: {building.floors} эт., "
                     f"{len(building.sections)} секций, "
                     f"{total} кв.")
        lines.append(f"    Пятно застройки: {building.total_building_area:.0f} м²")
        lines.append(f"    Общая площадь:   {building.total_gfa:.0f} м²")

        for apt_type, count in sorted(apts.items()):
            if count > 0:
                lines.append(f"    {apt_type}: {count} кв.")

        lines.append(f"    Секции:")
        for j, section in enumerate(building.sections):
            lines.append(
                f"      [{j + 1}] {section.section_type.name} "
                f"({section.section_type.category})"
            )

    lines.append("")
    lines.append("=" * 60)

    report_text = "\n".join(lines)

    # Сохранение
    if filepath is not None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            f.write(report_text)

    return report_text
