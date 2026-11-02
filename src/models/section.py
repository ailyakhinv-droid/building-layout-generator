"""Модель типовой секции жилого дома.

Содержит класс SectionType, описывающий геометрические
и планировочные параметры секции здания.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from shapely.affinity import rotate, scale, translate
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
        width_small: Малая ширина секции в метрах (для Г-образных угловых секций).
        depth_small: Малая глубина секции в метрах (для Г-образных угловых секций).
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
    width_small: float | None = None
    depth_small: float | None = None
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
    def is_meridian(self) -> bool:
        """Является ли секция меридиональной.

        Меридиональные секции имеют двухстороннюю ориентацию квартир (восток-запад)
        и по нормам инсоляции (СанПиН 1.2.3685-21, СП 42.13330) не могут размещаться
        строго горизонтально (восток-запад). Угол их продольной оси к горизонтали
        должен составлять не менее 25-30°, чтобы обеспечить инсоляцию северного фасада
        не менее 1.5-2 ч.
        """
        name_l = (self.name or "").lower()
        code_l = (self.section_code or "").lower()
        id_l = (self.id or "").lower()
        return "меридиан" in name_l or "meridian" in name_l or code_l.startswith("м") or id_l.startswith("mid_m")

    @property
    def is_latitudinal(self) -> bool:
        """Является ли секция широтной (ориентация восток-запад допустима)."""
        name_l = (self.name or "").lower()
        code_l = (self.section_code or "").lower()
        id_l = (self.id or "").lower()
        return "широтн" in name_l or "latitud" in name_l or code_l.startswith("ш") or id_l.startswith("end_sh")

    @property
    def total_apts_per_floor(self) -> int:
        """Общее количество квартир на одном этаже."""
        return sum(self.apartments_per_floor.values())

    def create_footprint(
        self,
        x: float,
        y: float,
        angle: float = 0.0,
        is_flipped: bool = False,
    ) -> Polygon:
        """Создать полигон пятна застройки секции.

        Для угловых секций (CORNER) с заданными малыми габаритами создаёт
        Г-образный контур с вырезом со стороны внутреннего двора.
        Для остальных секций создаёт прямоугольник.

        Args:
            x: Координата X центра секции.
            y: Координата Y центра секции.
            angle: Угол поворота в градусах (против часовой стрелки).
            is_flipped: Отразить ли секцию зеркально по горизонтали (для правого угла скобы).

        Returns:
            Полигон пятна застройки.
        """
        hw = self.width / 2.0
        hd = self.depth / 2.0

        if self.category == "CORNER" and self.width_small and self.depth_small:
            ws = self.width_small
            ds = self.depth_small
            footprint = Polygon([
                (-hw, hd),
                (hw, hd),
                (hw, hd - ds),
                (-hw + ws, hd - ds),
                (-hw + ws, -hd),
                (-hw, -hd),
                (-hw, hd),
            ])
            if is_flipped:
                footprint = scale(footprint, xfact=-1.0, yfact=1.0, origin=(0, 0))
        else:
            footprint = box(-hw, -hd, hw, hd)

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
