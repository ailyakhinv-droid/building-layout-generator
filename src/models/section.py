"""Модель типовой секции жилого дома.

Содержит класс SectionType, описывающий геометрические
и планировочные параметры секции здания.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, box


@dataclass
class SectionType:
    """Тип секции жилого дома.

    Attributes:
        id: Уникальный идентификатор типа секции.
        name: Наименование секции на русском языке.
        category: Категория секции (MIDDLE, CORNER, END).
        width: Ширина секции в метрах (по фасаду).
        depth: Глубина секции в метрах (перпендикулярно фасаду).
        min_floors: Минимальное количество этажей.
        max_floors: Максимальное количество этажей.
        default_floors: Количество этажей по умолчанию.
        floor_area: Общая площадь этажа в м².
        apartments_per_floor: Количество квартир на этаже по типам.
        apt_areas: Площади квартир по типам в м².
        has_commercial_ground: Наличие коммерческого первого этажа.
        parking_per_apt: Количество машиномест на квартиру.
    """

    id: str
    name: str
    category: str
    width: float
    depth: float
    min_floors: int
    max_floors: int
    default_floors: int
    floor_area: float
    apartments_per_floor: dict[str, int] = field(default_factory=dict)
    apt_areas: dict[str, float] = field(default_factory=dict)
    has_commercial_ground: bool = False
    parking_per_apt: float = 0.5
    elevators: int = 1
    section_code: str = ""
    living_area_per_floor: float = 0.0
    commercial_area_ground: float = 0.0
    floor_height: float = 3.15
    ground_floor_height: float = 4.20

    @classmethod
    def from_json(cls, filepath: str | Path) -> SectionType:
        """Загрузить тип секции из JSON-файла."""
        path = Path(filepath)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Фильтруем только поля, присутствующие в dataclass
        import dataclasses
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)

    @property
    def residential_area_per_floor(self) -> float:
        """Жилая площадь на одном этаже в м².

        Вычисляется как сумма произведений площади квартиры
        на количество квартир данного типа на этаже.
        """
        total = 0.0
        for apt_type, count in self.apartments_per_floor.items():
            area = self.apt_areas.get(apt_type, 0.0)
            total += area * count
        return total

    @property
    def total_apts_per_floor(self) -> int:
        """Общее количество квартир на одном этаже."""
        return sum(self.apartments_per_floor.values())

    def create_footprint(self, x: float, y: float, angle: float = 0.0) -> Polygon:
        """Создать полигон пятна застройки секции.

        Создаёт прямоугольник с центром в точке (x, y),
        повёрнутый на заданный угол.

        Args:
            x: Координата X центра секции.
            y: Координата Y центра секции.
            angle: Угол поворота в градусах (против часовой стрелки).

        Returns:
            Полигон пятна застройки.
        """
        # Создаём прямоугольник с центром в начале координат
        half_w = self.width / 2.0
        half_d = self.depth / 2.0
        footprint = box(-half_w, -half_d, half_w, half_d)

        # Поворачиваем вокруг центра
        if angle != 0.0:
            footprint = rotate(footprint, angle, origin=(0, 0), use_radians=False)

        # Перемещаем в заданную позицию
        footprint = translate(footprint, xoff=x, yoff=y)

        return footprint

    def __repr__(self) -> str:
        """Строковое представление типа секции."""
        return (
            f"SectionType(id='{self.id}', name='{self.name}', "
            f"category='{self.category}', {self.width}×{self.depth} м, "
            f"{self.default_floors} эт.)"
        )
