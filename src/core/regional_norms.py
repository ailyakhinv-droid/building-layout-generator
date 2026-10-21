"""Региональные нормативы градостроительного проектирования (РНГП / МНГП).

Модуль для загрузки региональных параметров и расчета нормативной потребности
в машиноместах, детских и спортивных площадках, площадках отдыха и ТКО
согласно СП 42.13330, МНГП г. Москвы, РНГП МО и РНГП Санкт-Петербурга.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class ParkingCalculationMethod(str, Enum):
    """Методика расчета нормативного количества машиномест."""

    PER_1000_PEOPLE = "per_1000_people"  # СП 42.13330 (по уровню автомобилизации)
    PER_LIVING_AREA = "per_living_area"  # 1 м/м на X м² жилой площади (МО, СПб, Москва)
    PER_APARTMENT = "per_apartment"      # Доля машиномест на 1 квартиру


@dataclass
class DensityNormConfig:
    """Нормативы плотности и использования территории."""

    max_far: float = 2.5
    max_bcr: float = 0.40
    green_ratio_min: float = 0.25


@dataclass
class ParkingNormConfig:
    """Нормативы обеспечения автостоянками."""

    method: ParkingCalculationMethod = ParkingCalculationMethod.PER_1000_PEOPLE
    ratio: float = 350.0       # Значение в зависимости от метода (350 на 1000 чел, 80 м² на 1 м/м и т.д.)
    guest_share: float = 0.20  # Доля открытых гостевых стоянок
    area_per_car: float = 25.0 # Средняя площадь на 1 открытое машиноместо с проездом (м²)


@dataclass
class PlaygroundNormConfig:
    """Нормативы площадок дворового благоустройства (м² на 1 жителя)."""

    children: float = 0.7  # Детские игровые площадки
    sport: float = 0.5     # Спортивные площадки
    relax: float = 0.1     # Площадки для отдыха взрослых
    utility: float = 0.1   # Хозяйственные площадки
    waste: float = 0.05    # Площадки ТКО

    @property
    def total_per_person(self) -> float:
        """Суммарная нормативная площадь площадок на 1 жителя."""
        return self.children + self.sport + self.relax + self.utility + self.waste


@dataclass
class RegionalNorm:
    """Региональный норматив градостроительного проектирования."""

    id: str
    name: str
    description: str
    density: DensityNormConfig
    parking: ParkingNormConfig
    playgrounds: PlaygroundNormConfig

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegionalNorm:
        """Создать объект норматива из словаря конфигурации."""
        density_data = data.get("density", {})
        parking_data = data.get("parking", {})
        playgrounds_data = data.get("playgrounds", {})

        p_method_str = parking_data.get("method", "per_1000_people")
        try:
            p_method = ParkingCalculationMethod(p_method_str)
        except ValueError:
            p_method = ParkingCalculationMethod.PER_1000_PEOPLE

        return cls(
            id=data.get("id", "custom"),
            name=data.get("name", "Пользовательский норматив"),
            description=data.get("description", ""),
            density=DensityNormConfig(
                max_far=float(density_data.get("max_far", 2.5)),
                max_bcr=float(density_data.get("max_bcr", 0.40)),
                green_ratio_min=float(density_data.get("green_ratio_min", 0.25)),
            ),
            parking=ParkingNormConfig(
                method=p_method,
                ratio=float(parking_data.get("ratio", 350.0)),
                guest_share=float(parking_data.get("guest_share", 0.20)),
                area_per_car=float(parking_data.get("area_per_car", 25.0)),
            ),
            playgrounds=PlaygroundNormConfig(
                children=float(playgrounds_data.get("children", 0.7)),
                sport=float(playgrounds_data.get("sport", 0.5)),
                relax=float(playgrounds_data.get("relax", 0.1)),
                utility=float(playgrounds_data.get("utility", 0.1)),
                waste=float(playgrounds_data.get("waste", 0.05)),
            ),
        )

    def calculate_parking_demand(
        self,
        residential_area: float,
        apartments_total: int,
        population: float,
    ) -> dict[str, int]:
        """Рассчитать нормативную потребность в машиноместах.

        Returns:
            Словарь с общим числом м/м, гостевыми и постоянными м/м.
        """
        if self.parking.method == ParkingCalculationMethod.PER_LIVING_AREA:
            # 1 м/м на ratio м² жилой площади
            ratio = max(1.0, self.parking.ratio)
            total_spaces = math.ceil(residential_area / ratio)
        elif self.parking.method == ParkingCalculationMethod.PER_APARTMENT:
            # ratio м/м на 1 квартиру
            total_spaces = math.ceil(apartments_total * self.parking.ratio)
        else:
            # per_1000_people: ratio машиномест на 1000 жителей
            total_spaces = math.ceil((population / 1000.0) * self.parking.ratio)

        guest_spaces = math.ceil(total_spaces * self.parking.guest_share)
        resident_spaces = max(0, total_spaces - guest_spaces)

        return {
            "total": total_spaces,
            "guest": guest_spaces,
            "resident": resident_spaces,
        }

    def calculate_playgrounds_demand(self, population: float) -> dict[str, float]:
        """Рассчитать требуемые площади дворовых площадок в м².

        Returns:
            Словарь с площадями по каждому виду площадок и суммой.
        """
        children = round(population * self.playgrounds.children, 1)
        sport = round(population * self.playgrounds.sport, 1)
        relax = round(population * self.playgrounds.relax, 1)
        utility = round(population * self.playgrounds.utility, 1)
        waste = round(population * self.playgrounds.waste, 1)
        total = round(children + sport + relax + utility + waste, 1)

        return {
            "children": children,
            "sport": sport,
            "relax": relax,
            "utility": utility,
            "waste": waste,
            "total": total,
        }


def get_default_config_path() -> Path:
    """Получить путь к файлу региональных нормативов."""
    project_root = Path(__file__).resolve().parent.parent.parent
    return project_root / "config" / "regional_norms.yaml"


def load_regional_norms(path: Path | None = None) -> dict[str, RegionalNorm]:
    """Загрузить все доступные региональные нормативы из YAML."""
    norm_path = path or get_default_config_path()
    if not norm_path.exists():
        # Fallback к базовому СП 42, если файл еще не создан
        fallback = RegionalNorm(
            id="russia_sp42",
            name="РФ (СП 42.13330.2016)",
            description="Базовые федеральные нормативы",
            density=DensityNormConfig(),
            parking=ParkingNormConfig(),
            playgrounds=PlaygroundNormConfig(),
        )
        return {fallback.id: fallback}

    with norm_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    regions_data = data.get("regions", {})
    result: dict[str, RegionalNorm] = {}
    for region_id, reg_dict in regions_data.items():
        reg_dict["id"] = region_id
        result[region_id] = RegionalNorm.from_dict(reg_dict)

    return result


def get_regional_norm(region_id: str, path: Path | None = None) -> RegionalNorm:
    """Получить норматив по идентификатору региона."""
    norms = load_regional_norms(path)
    if region_id in norms:
        return norms[region_id]
    # Возвращаем первый попавшийся или дефолтный
    return next(iter(norms.values()))
