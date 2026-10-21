"""Модель технико-экономических показателей (ТЭП).

Содержит класс TEP для расчёта и хранения
технико-экономических показателей проекта застройки.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from src.models.building import Building
from src.models.site import Site


@dataclass
class TEP:
    """Технико-экономические показатели проекта застройки.

    Attributes:
        site_area: Площадь участка в м².
        building_area: Суммарная площадь застройки (пятен) в м².
        total_gfa: Общая площадь зданий (GFA) в м².
        residential_area: Жилая площадь в м².
        bcr: Процент застройки (Building Coverage Ratio).
        far: Коэффициент плотности застройки (Floor Area Ratio).
        building_count: Количество зданий.
        avg_floors: Средняя этажность.
        apartments_total: Общее количество квартир.
        apartments_1k: Количество 1-комнатных квартир.
        apartments_2k: Количество 2-комнатных квартир.
        apartments_3k: Количество 3-комнатных квартир.
        population: Расчётная численность населения.
        parking_spaces: Количество машиномест.
        green_area: Площадь озеленения в м².
        green_ratio: Доля озеленения.
    """

    site_area: float
    building_area: float
    total_gfa: float
    residential_area: float
    bcr: float
    far: float
    building_count: int
    avg_floors: float
    apartments_total: int
    apartments_1k: int
    apartments_2k: int
    apartments_3k: int
    population: float
    parking_spaces: int
    green_area: float
    green_ratio: float

    def to_dict(self) -> dict[str, Any]:
        """Преобразовать ТЭП в словарь.

        Returns:
            Словарь со всеми показателями.
        """
        return {
            "Площадь участка, м²": round(self.site_area, 1),
            "Площадь застройки, м²": round(self.building_area, 1),
            "Общая площадь (GFA), м²": round(self.total_gfa, 1),
            "Жилая площадь, м²": round(self.residential_area, 1),
            "Процент застройки (BCR)": round(self.bcr, 3),
            "Коэффициент плотности (FAR)": round(self.far, 3),
            "Количество зданий": self.building_count,
            "Средняя этажность": round(self.avg_floors, 1),
            "Квартиры всего": self.apartments_total,
            "1-комнатные": self.apartments_1k,
            "2-комнатные": self.apartments_2k,
            "3-комнатные": self.apartments_3k,
            "Население, чел.": round(self.population, 0),
            "Машиномест": self.parking_spaces,
            "Площадь озеленения, м²": round(self.green_area, 1),
            "Доля озеленения": round(self.green_ratio, 3),
        }

    def to_table_str(self) -> str:
        """Сформировать текстовую таблицу ТЭП на русском языке.

        Returns:
            Отформатированная строка с таблицей показателей.
        """
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  ТЕХНИКО-ЭКОНОМИЧЕСКИЕ ПОКАЗАТЕЛИ (ТЭП)")
        lines.append("=" * 60)

        rows: list[tuple[str, str]] = [
            ("Площадь участка", f"{self.site_area:,.1f} м²"),
            ("Площадь застройки", f"{self.building_area:,.1f} м²"),
            ("Общая площадь (GFA)", f"{self.total_gfa:,.1f} м²"),
            ("Жилая площадь", f"{self.residential_area:,.1f} м²"),
            ("", ""),
            ("Процент застройки (BCR)", f"{self.bcr:.1%}"),
            ("Коэфф. плотности (FAR)", f"{self.far:.2f}"),
            ("", ""),
            ("Количество зданий", f"{self.building_count}"),
            ("Средняя этажность", f"{self.avg_floors:.1f}"),
            ("", ""),
            ("Квартиры всего", f"{self.apartments_total}"),
            ("  — 1-комнатные", f"{self.apartments_1k}"),
            ("  — 2-комнатные", f"{self.apartments_2k}"),
            ("  — 3-комнатные", f"{self.apartments_3k}"),
            ("", ""),
            ("Население", f"{self.population:,.0f} чел."),
            ("Машиномест", f"{self.parking_spaces}"),
            ("", ""),
            ("Площадь озеленения", f"{self.green_area:,.1f} м²"),
            ("Доля озеленения", f"{self.green_ratio:.1%}"),
        ]

        for label, value in rows:
            if label == "" and value == "":
                lines.append("-" * 60)
            else:
                lines.append(f"  {label:<35} {value:>20}")

        lines.append("=" * 60)
        return "\n".join(lines)

    @classmethod
    def from_placement(
        cls,
        site: Site,
        buildings: list[Building],
        config: dict[str, Any],
    ) -> TEP:
        """Рассчитать ТЭП на основе размещения зданий.

        Args:
            site: Земельный участок.
            buildings: Список размещённых зданий.
            config: Словарь нормативных параметров (из defaults.yaml).

        Returns:
            Экземпляр TEP с рассчитанными показателями.
        """
        # Площадь участка
        site_area = site.area

        # Суммарная площадь застройки
        building_area = sum(b.total_building_area for b in buildings)

        # Общая площадь (GFA)
        total_gfa = sum(b.total_gfa for b in buildings)

        # Жилая площадь — сумма жилых площадей по секциям
        residential_area = 0.0
        for building in buildings:
            for section in building.sections:
                # Определяем количество жилых этажей
                res_floors = section.floors
                if section.section_type.has_commercial_ground:
                    res_floors = max(0, section.floors - 1)
                residential_area += (
                    section.section_type.residential_area_per_floor * res_floors
                )

        # Процент застройки и плотность
        bcr = building_area / site_area if site_area > 0 else 0.0
        far = total_gfa / site_area if site_area > 0 else 0.0

        # Количество зданий и средняя этажность
        building_count = len(buildings)
        avg_floors = (
            sum(b.floors for b in buildings) / building_count
            if building_count > 0
            else 0.0
        )

        # Квартиры — агрегация по всем зданиям
        total_apts: dict[str, int] = {}
        for building in buildings:
            for apt_type, count in building.total_apartments.items():
                total_apts[apt_type] = total_apts.get(apt_type, 0) + count

        apartments_1k = total_apts.get("1k", 0)
        apartments_2k = total_apts.get("2k", 0)
        apartments_3k = total_apts.get("3k", 0)
        apartments_total = apartments_1k + apartments_2k + apartments_3k

        # Население
        pop_per_1k = config.get("population_per_1k", 2.8)
        pop_per_2k = config.get("population_per_2k", 3.6)
        pop_per_3k = config.get("population_per_3k", 4.5)
        population = (
            apartments_1k * pop_per_1k
            + apartments_2k * pop_per_2k
            + apartments_3k * pop_per_3k
        )

        # Машиноместа
        parking_ratio = config.get("parking_ratio", 0.5)
        parking_spaces = math.ceil(apartments_total * parking_ratio)

        # Озеленение — оставшаяся площадь за вычетом застройки
        # (упрощённый расчёт: участок минус застройка)
        green_area = max(0.0, site_area - building_area)
        green_ratio = green_area / site_area if site_area > 0 else 0.0

        return cls(
            site_area=site_area,
            building_area=building_area,
            total_gfa=total_gfa,
            residential_area=residential_area,
            bcr=bcr,
            far=far,
            building_count=building_count,
            avg_floors=avg_floors,
            apartments_total=apartments_total,
            apartments_1k=apartments_1k,
            apartments_2k=apartments_2k,
            apartments_3k=apartments_3k,
            population=population,
            parking_spaces=parking_spaces,
            green_area=green_area,
            green_ratio=green_ratio,
        )

    def __repr__(self) -> str:
        """Строковое представление ТЭП."""
        return (
            f"TEP(площадь={self.site_area:.0f} м², "
            f"зданий={self.building_count}, "
            f"квартир={self.apartments_total}, "
            f"BCR={self.bcr:.1%}, FAR={self.far:.2f})"
        )
