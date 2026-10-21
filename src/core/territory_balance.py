"""Калькулятор баланса территории и нормативного обеспечения.

Модуль рассчитывает детальный баланс площадей земельного участка:
- Пятно застройки (BCR)
- Внутриквартальные проезды, пожарные полосы и тротуары
- Обязательные дворовые площадки (игры детей, спорт, отдых, хозцели, ТКО)
- Нормативное озеленение (не менее 25%)
- Наземная вместимость машиномест и дефицит в подземный/многоуровневый паркинг
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from src.core.regional_norms import RegionalNorm


@dataclass
class PlaygroundBreakdown:
    """Детализация площадей дворовых площадок."""

    children: float  # Игры детей, м²
    sport: float     # Занятия физкультурой, м²
    relax: float     # Отдых взрослых, м²
    utility: float   # Хозяйственные цели, м²
    waste: float     # Контейнеры ТКО, м²
    total: float     # Всего площадок, м²


@dataclass
class ParkingBalance:
    """Баланс обеспечения автостоянками."""

    required_total: int     # Требуется всего по РНГП/МНГП, м/м
    required_guest: int     # В том числе гостевых, м/м
    required_resident: int  # В том числе для жителей, м/м
    ground_capacity: int    # Размещено открыто на участке, м/м
    ground_area: float      # Площадь под наземными парковками, м²
    underground_deficit: int # Дефицит машиномест (в подземный/стилобатный паркинг), м/м
    underground_area_est: float # Оценочная площадь подземного паркинга, м²


@dataclass
class TerritoryBalanceResult:
    """Итоговый баланс использования земельного участка."""

    site_area: float
    building_footprint: float
    driveways_area: float
    playgrounds: PlaygroundBreakdown
    green_area: float
    green_ratio: float
    green_norm_met: bool
    parking: ParkingBalance
    regional_norm_name: str
    warnings: list[str] = field(default_factory=list)

    @property
    def bcr(self) -> float:
        """Процент застройки."""
        return self.building_footprint / self.site_area if self.site_area > 0 else 0.0

    @property
    def free_area(self) -> float:
        """Свободная от зданий территория участка."""
        return max(0.0, self.site_area - self.building_footprint)

    def to_dict(self) -> dict[str, Any]:
        """Преобразовать баланс в словарь показателей."""
        return {
            "Площадь участка, м²": round(self.site_area, 1),
            "Пятно застройки, м²": round(self.building_footprint, 1),
            "Процент застройки (BCR)": f"{self.bcr:.1%}",
            "Проезды и пожарные полосы, м²": round(self.driveways_area, 1),
            "Дворовые площадки всего, м²": round(self.playgrounds.total, 1),
            "  - Детские игровые, м²": round(self.playgrounds.children, 1),
            "  - Спортивные, м²": round(self.playgrounds.sport, 1),
            "  - Отдых взрослых, м²": round(self.playgrounds.relax, 1),
            "  - Хозплощадки и ТКО, м²": round(self.playgrounds.utility + self.playgrounds.waste, 1),
            "Озеленение, м²": round(self.green_area, 1),
            "Доля озеленения": f"{self.green_ratio:.1%}",
            "Озеленение в норме": "Да" if self.green_norm_met else "Нет",
            "Парковки требуется всего, м/м": self.parking.required_total,
            "  - Гостевых, м/м": self.parking.required_guest,
            "  - Постоянных (для жителей), м/м": self.parking.required_resident,
            "Наземная парковка на участке, м/м": self.parking.ground_capacity,
            "Площадь открытых парковок, м²": round(self.parking.ground_area, 1),
            "Дефицит в подземный паркинг, м/м": self.parking.underground_deficit,
            "Оценка площади подземного паркинга, м²": round(self.parking.underground_area_est, 1),
            "Региональный норматив": self.regional_norm_name,
        }

    def get_structure_shares(self) -> dict[str, float]:
        """Получить процентные доли элементов баланса участка (для диаграммы)."""
        if self.site_area <= 0:
            return {}

        return {
            "Застройка (дома)": round(self.building_footprint / self.site_area * 100, 1),
            "Проезды и тротуары": round(self.driveways_area / self.site_area * 100, 1),
            "Дворовые площадки": round(self.playgrounds.total / self.site_area * 100, 1),
            "Озеленение": round(self.green_area / self.site_area * 100, 1),
            "Наземные парковки": round(self.parking.ground_area / self.site_area * 100, 1),
        }


def calculate_territory_balance(
    site_area: float,
    building_footprint_area: float,
    population: float,
    residential_area: float,
    apartments_total: int,
    regional_norm: RegionalNorm,
    driveways_factor: float = 0.18,
    underground_area_per_car: float = 35.0,
) -> TerritoryBalanceResult:
    """Рассчитать полный градостроительный баланс территории земельного участка.

    Args:
        site_area: Общая площадь участка, м².
        building_footprint_area: Площадь пятна застройки зданий, м².
        population: Расчетное количество жителей, чел.
        residential_area: Общая жилая площадь квартир, м².
        apartments_total: Общее количество квартир.
        regional_norm: Выбранный региональный норматив (РНГП/МНГП).
        driveways_factor: Доля свободной площади под пожарные проезды, разъезды и тротуары (~18%).
        underground_area_per_car: Нормативная площадь подземного паркинга на 1 м/м с рампами (~35 м²).

    Returns:
        Объект TerritoryBalanceResult с полной детализацией и проверками.
    """
    warnings: list[str] = []

    # 1. Потребность в парковках по региональному нормативу
    parking_demand = regional_norm.calculate_parking_demand(
        residential_area=residential_area,
        apartments_total=apartments_total,
        population=population,
    )
    req_total = parking_demand["total"]
    req_guest = parking_demand["guest"]
    req_resident = parking_demand["resident"]

    # 2. Потребность в площадках дворового благоустройства
    play_dict = regional_norm.calculate_playgrounds_demand(population)
    playgrounds = PlaygroundBreakdown(
        children=play_dict["children"],
        sport=play_dict["sport"],
        relax=play_dict["relax"],
        utility=play_dict["utility"],
        waste=play_dict["waste"],
        total=play_dict["total"],
    )

    # 3. Свободная от зданий территория
    free_land = max(0.0, site_area - building_footprint_area)

    # 4. Проезды, пожарные пути и тротуары вокруг домов
    # В среднем занимают от 15% до 22% свободной территории
    driveways_area = round(free_land * driveways_factor, 1)

    # 5. Обязательное минимальное озеленение (по нормативу, обычно 25% от площади участка)
    min_green_ratio = regional_norm.density.green_ratio_min
    min_green_required = round(site_area * min_green_ratio, 1)

    # 6. Доступный резерв земли для открытых наземных автостоянок:
    # Земля под парковки = Свободная земля - Проезды - Площадки - Минимальное озеленение
    land_for_parking = free_land - driveways_area - playgrounds.total - min_green_required

    area_per_car = max(15.0, regional_norm.parking.area_per_car)

    if land_for_parking > 0:
        # Сколько максимум наземных м/м физически помещается
        max_possible_ground = int(land_for_parking / area_per_car)
        # Наземно размещаем не больше, чем требуется всего
        actual_ground_spaces = min(req_total, max_possible_ground)
        actual_ground_area = round(actual_ground_spaces * area_per_car, 1)

        # Фактическое озеленение (всё, что осталось свободным сверх минимального)
        actual_green_area = round(
            free_land - driveways_area - playgrounds.total - actual_ground_area, 1
        )
    else:
        # Земли не хватает даже на минимальное озеленение и площадки
        actual_ground_spaces = 0
        actual_ground_area = 0.0
        # Зеленая площадь ужимается
        actual_green_area = max(0.0, free_land - driveways_area - playgrounds.total)
        warnings.append(
            "Дефицит территории участка: для обеспечения нормативных площадок "
            "наземные парковки не помещаются, все машиноместа перенесены в подземный паркинг."
        )

    # 7. Дефицит машиномест (требует подземного или стилобатного паркинга)
    underground_deficit = max(0, req_total - actual_ground_spaces)
    underground_area_est = round(underground_deficit * underground_area_per_car, 1)

    # 8. Проверка нормативного озеленения
    actual_green_ratio = actual_green_area / site_area if site_area > 0 else 0.0
    green_norm_met = actual_green_ratio >= min_green_ratio

    if not green_norm_met:
        warnings.append(
            f"Доля озеленения ({actual_green_ratio:.1%}) ниже норматива ({min_green_ratio:.0%}). "
            f"Рекомендуется сократить пятно застройки или использовать эксплуатируемую кровлю."
        )

    if underground_deficit > 0:
        warnings.append(
            f"Требуется подземный/стилобатный паркинг на {underground_deficit} м/м "
            f"(ориентировочно {underground_area_est:,.0f} м²)."
        )

    parking_balance = ParkingBalance(
        required_total=req_total,
        required_guest=req_guest,
        required_resident=req_resident,
        ground_capacity=actual_ground_spaces,
        ground_area=actual_ground_area,
        underground_deficit=underground_deficit,
        underground_area_est=underground_area_est,
    )

    return TerritoryBalanceResult(
        site_area=site_area,
        building_footprint=building_footprint_area,
        driveways_area=driveways_area,
        playgrounds=playgrounds,
        green_area=actual_green_area,
        green_ratio=actual_green_ratio,
        green_norm_met=green_norm_met,
        parking=parking_balance,
        regional_norm_name=regional_norm.name,
        warnings=warnings,
    )
