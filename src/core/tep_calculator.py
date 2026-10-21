"""Калькулятор технико-экономических показателей.

Обёртка над TEP.from_placement() с дополнительной
логикой расчёта и проверки нормативов.
"""

from __future__ import annotations

from typing import Any

from src.models.building import Building
from src.models.site import Site
from src.models.tep import TEP


def calculate_tep(
    site: Site,
    buildings: list[Building],
    config: dict[str, Any],
) -> TEP:
    """Рассчитать ТЭП для размещения зданий.

    Args:
        site: Земельный участок.
        buildings: Список размещённых зданий.
        config: Нормативные параметры.

    Returns:
        Объект TEP с рассчитанными показателями.
    """
    return TEP.from_placement(site, buildings, config)


def check_normatives(tep: TEP, config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Проверить соответствие ТЭП нормативам.

    Args:
        tep: Рассчитанные ТЭП.
        config: Нормативные параметры.

    Returns:
        Словарь результатов проверки:
        {
            "bcr": {"value": 0.35, "limit": 0.40, "ok": True},
            "far": {"value": 2.1, "limit": 2.5, "ok": True},
            "green_ratio": {"value": 0.30, "limit": 0.25, "ok": True},
        }
    """
    max_bcr = config.get("max_bcr", 0.40)
    max_far = config.get("max_far", 2.5)
    min_green = config.get("green_ratio_min", 0.25)

    results: dict[str, dict[str, Any]] = {
        "bcr": {
            "name": "Процент застройки",
            "value": tep.bcr,
            "limit": max_bcr,
            "ok": tep.bcr <= max_bcr,
            "unit": "%",
        },
        "far": {
            "name": "Плотность застройки",
            "value": tep.far,
            "limit": max_far,
            "ok": tep.far <= max_far,
            "unit": "",
        },
        "green_ratio": {
            "name": "Доля озеленения",
            "value": tep.green_ratio,
            "limit": min_green,
            "ok": tep.green_ratio >= min_green,
            "unit": "%",
        },
    }

    return results


def format_normative_check(checks: dict[str, dict[str, Any]]) -> str:
    """Отформатировать результаты проверки нормативов.

    Args:
        checks: Результат check_normatives().

    Returns:
        Отформатированная строка для вывода.
    """
    lines: list[str] = []
    lines.append("=" * 50)
    lines.append("  ПРОВЕРКА НОРМАТИВОВ")
    lines.append("=" * 50)

    all_ok = True
    for key, check in checks.items():
        status = "✓" if check["ok"] else "✗"
        if not check["ok"]:
            all_ok = False

        if check["unit"] == "%":
            val_str = f"{check['value']:.1%}"
            lim_str = f"{check['limit']:.1%}"
        else:
            val_str = f"{check['value']:.2f}"
            lim_str = f"{check['limit']:.2f}"

        name = check["name"]
        lines.append(f"  [{status}] {name:<25} {val_str:>10} / {lim_str:>10}")

    lines.append("-" * 50)
    if all_ok:
        lines.append("  Все нормативы соблюдены ✓")
    else:
        lines.append("  ВНИМАНИЕ: Есть нарушения нормативов! ✗")
    lines.append("=" * 50)

    return "\n".join(lines)
