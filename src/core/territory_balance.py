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
    underground_levels: int = 1 # Расчетное число подземных этажей паркинга
    guest_ground_placed: int = 0 # Фактически размещено гостевых мест открыто
    resident_ground_placed: int = 0 # Фактически размещено постоянных мест открыто


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
    stylobate_area: float = 0.0
    green_roof_area: float = 0.0
    effective_green_area: float = 0.0
    effective_green_ratio: float = 0.0
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
        data = {
            "Площадь участка, м²": round(self.site_area, 1),
            "Пятно застройки, м²": round(self.building_footprint, 1),
            "Процент застройки (BCR)": f"{self.bcr:.1%}",
            "Проезды и пожарные полосы, м²": round(self.driveways_area, 1),
            "Дворовые площадки всего, м²": round(self.playgrounds.total, 1),
            "  - Детские игровые, м²": round(self.playgrounds.children, 1),
            "  - Спортивные, м²": round(self.playgrounds.sport, 1),
            "  - Отдых взрослых, м²": round(self.playgrounds.relax, 1),
            "  - Хозплощадки и ТКО, м²": round(self.playgrounds.utility + self.playgrounds.waste, 1),
            "Озеленение на грунте, м²": round(self.green_area, 1),
            "Доля озеленения на грунте": f"{self.green_ratio:.1%}",
            "Озеленение в норме": "Да" if self.green_norm_met else "Нет",
            "Парковки требуется всего, м/м": self.parking.required_total,
            "  - Гостевых, м/м": self.parking.required_guest,
            "  - Постоянных (для жителей), м/м": self.parking.required_resident,
            "Наземная парковка на участке, м/м": self.parking.ground_capacity,
            "  - В т.ч. открытых гостевых, м/м": self.parking.guest_ground_placed,
            "  - В т.ч. открытых для жителей, м/м": self.parking.resident_ground_placed,
            "Площадь открытых парковок, м²": round(self.parking.ground_area, 1),
            "Дефицит в подземный паркинг, м/м": self.parking.underground_deficit,
            "Оценка площади подземного паркинга, м²": round(self.parking.underground_area_est, 1),
            "Расчетная этажность подземного паркинга": f"{self.parking.underground_levels} ур." if self.parking.underground_deficit > 0 else "0 ур.",
            "Региональный норматив": self.regional_norm_name,
        }
        if self.green_roof_area > 0:
            data["Кровля стилобата с озеленением (СП 42 п. 9.13), м²"] = round(self.green_roof_area, 1)
            data["Эффективное озеленение (грунт + стилобат)"] = f"{self.effective_green_ratio:.1%}"
        return data

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
    buildings: list[Any] | None = None,
) -> TerritoryBalanceResult:
    """Рассчитать полный градостроительный баланс территории земельного участка.

    Включает:
    - Расчет пожарных проездов по СП 4.13130 (по периметру и этажности);
    - Приоритет открытого размещения гостевых автостоянок (СП 42.13330 п. 11.5);
    - Вынос постоянных мест жителей в подземный паркинг с расчетом этажности стилобата;
    - Эксплуатируемую кровлю стилобата с зачетом в озеленение (СП 42.13330 п. 9.13).

    Args:
        site_area: Общая площадь участка, м².
        building_footprint_area: Площадь пятна застройки зданий, м².
        population: Расчетное количество жителей, чел.
        residential_area: Общая жилая площадь квартир, м².
        apartments_total: Общее количество квартир.
        regional_norm: Выбранный региональный норматив (РНГП/МНГП).
        driveways_factor: Резервный коэффициент доли свободной площади под проезды.
        underground_area_per_car: Нормативная площадь подземного паркинга на 1 м/м с рампами (~35 м²).
        buildings: Список размещенных зданий для точного геометрического расчета проездов СП 4.13130.

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

    # 4. Проезды, пожарные полосы и тротуары вокруг домов (СП 4.13130)
    if buildings and len(buildings) > 0 and free_land > 0:
        total_driveway_area = 0.0
        for b in buildings:
            fp = getattr(b, "footprint", None)
            perim = float(fp.exterior.length) if fp and hasattr(fp, "exterior") and fp.exterior else 120.0
            h = getattr(b, "height", 27.0)
            if h > 28.0:
                # СП 4.13130 п. 8.1: здания выше 28 м требуют проезд с 2-х сторон или по периметру (ширина 6.0 м)
                lane_len = perim * 0.55
                b_drive = lane_len * 6.0
            else:
                # Здания до 28 м: проезд с 1 стороны (ширина 4.2 м)
                lane_len = perim * 0.35
                b_drive = lane_len * 4.2
            # Разворотная площадка для пожарной техники 15х15м (225 м²) + входные тротуары
            b_drive += 225.0 + (perim * 0.20 * 1.8)
            total_driveway_area += b_drive

        # Ограничиваем физическими пределами от свободной земли участка
        min_drv = free_land * 0.12
        max_drv = free_land * 0.35
        driveways_area = round(max(min_drv, min(total_driveway_area, max_drv)), 1)
    else:
        driveways_area = round(free_land * driveways_factor, 1)

    # 5. Обязательное минимальное озеленение (по нормативу, обычно 25% от площади участка)
    min_green_ratio = regional_norm.density.green_ratio_min
    min_green_required = round(site_area * min_green_ratio, 1)

    # 6. Доступный резерв земли для открытых наземных автостоянок:
    land_for_parking = free_land - driveways_area - playgrounds.total - min_green_required
    area_per_car = max(15.0, regional_norm.parking.area_per_car)

    # Приоритет распределения машиномест по СП 42.13330 (п. 11.5):
    # - Гостевые машиноместа (req_guest) первоочередно размещаются открыто на участке;
    # - Места жителей (req_resident) размещаются на открытой земле по остаточному принципу,
    #   а при дефиците земли направляются в подземный/стилобатный паркинг.
    if land_for_parking > 0:
        max_possible_ground = int(land_for_parking / area_per_car)
        # 1. Сначала гостевые
        actual_guest_ground = min(req_guest, max_possible_ground)
        rem_ground = max_possible_ground - actual_guest_ground
        # 2. Затем постоянные жители
        actual_resident_ground = min(req_resident, rem_ground)
        actual_ground_spaces = actual_guest_ground + actual_resident_ground
        actual_ground_area = round(actual_ground_spaces * area_per_car, 1)

        actual_green_area = round(
            free_land - driveways_area - playgrounds.total - actual_ground_area, 1
        )
    else:
        actual_guest_ground = 0
        actual_resident_ground = 0
        actual_ground_spaces = 0
        actual_ground_area = 0.0
        actual_green_area = max(0.0, free_land - driveways_area - playgrounds.total)
        warnings.append(
            "Дефицит территории участка: для обеспечения нормативных площадок "
            "наземные парковки не помещаются, машиноместа перенесены в подземный паркинг."
        )

    # 7. Дефицит машиномест (в подземный паркинг)
    underground_deficit = max(0, req_total - actual_ground_spaces)
    underground_area_est = round(underground_deficit * underground_area_per_car, 1)

    # 8. Расчет стилобата и уровней подземного паркинга
    stylobate_footprint = building_footprint_area * 1.35 if building_footprint_area > 0 else max(500.0, site_area * 0.25)
    underground_levels = math.ceil(underground_area_est / max(400.0, stylobate_footprint)) if underground_deficit > 0 else 0

    # 9. Озелененная кровля стилобата (СП 42.13330 п. 9.13)
    green_roof_area = max(0.0, round(stylobate_footprint - building_footprint_area, 1)) if underground_deficit > 0 else 0.0
    effective_green_area = round(actual_green_area + green_roof_area, 1)
    effective_green_ratio = effective_green_area / site_area if site_area > 0 else 0.0

    actual_green_ratio = actual_green_area / site_area if site_area > 0 else 0.0
    green_norm_met = (actual_green_ratio >= min_green_ratio) or (effective_green_ratio >= min_green_ratio)

    if not (actual_green_ratio >= min_green_ratio):
        if effective_green_ratio >= min_green_ratio:
            warnings.append(
                f"Наземное озеленение ({actual_green_ratio:.1%}) компенсируется "
                f"эксплуатируемой кровлей стилобата ({green_roof_area:,.0f} м²). Суммарно: {effective_green_ratio:.1%} (норма {min_green_ratio:.0%})."
            )
        else:
            warnings.append(
                f"Доля озеленения ({actual_green_ratio:.1%}) ниже норматива ({min_green_ratio:.0%}). "
                f"Рекомендуется сократить пятно застройки или использовать эксплуатируемую кровлю."
            )

    if underground_deficit > 0:
        lvl_str = f" ({underground_levels} подземн. ур.)" if underground_levels > 0 else ""
        warnings.append(
            f"Требуется подземный/стилобатный паркинг на {underground_deficit} м/м "
            f"(ориентировочно {underground_area_est:,.0f} м²{lvl_str})."
        )
        if underground_levels > 2:
            warnings.append(
                f"Внимание: расчетная этажность подземного паркинга ({underground_levels} ур.) "
                f"приведет к существенному удорожанию. Рекомендуется вынос части мест в отдельный паркинг."
            )

    parking_balance = ParkingBalance(
        required_total=req_total,
        required_guest=req_guest,
        required_resident=req_resident,
        ground_capacity=actual_ground_spaces,
        ground_area=actual_ground_area,
        underground_deficit=underground_deficit,
        underground_area_est=underground_area_est,
        underground_levels=underground_levels,
        guest_ground_placed=actual_guest_ground,
        resident_ground_placed=actual_resident_ground,
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
        stylobate_area=round(stylobate_footprint, 1),
        green_roof_area=green_roof_area,
        effective_green_area=effective_green_area,
        effective_green_ratio=effective_green_ratio,
        warnings=warnings,
    )
