"""Модели размещённой секции и здания.

Содержит классы PlacedSection и Building, описывающие
конкретное размещение секций на участке и агрегированные
параметры здания.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import Polygon
from shapely.ops import unary_union

from src.models.section import SectionType

# Высота типового этажа по умолчанию (метры)
_DEFAULT_FLOOR_HEIGHT: float = 3.0


@dataclass
class PlacedSection:
    """Секция, размещённая на участке.

    Attributes:
        section_type: Тип секции из библиотеки.
        x: Координата X центра секции.
        y: Координата Y центра секции.
        angle: Угол поворота секции в градусах.
        floors: Количество этажей секции.
        is_flipped: Зеркальное отражение по горизонтали (для правого угла скобы).
    """

    section_type: SectionType
    x: float
    y: float
    angle: float = 0.0
    floors: int = 0
    is_flipped: bool = False
    floor_height: float | None = None
    ground_floor_height: float | None = None

    def __post_init__(self) -> None:
        """Установить этажность по умолчанию, если не задана, и ограничить максимумом секции."""
        if self.floors <= 0:
            self.floors = self.section_type.default_floors
        else:
            self.floors = max(1, min(self.floors, self.section_type.max_floors))

    @property
    def footprint(self) -> Polygon:
        """Полигон пятна застройки секции."""
        return self.section_type.create_footprint(
            self.x, self.y, self.angle, is_flipped=self.is_flipped
        )

    @property
    def gfa(self) -> float:
        """Общая площадь секции (площадь этажа × количество этажей) в м²."""
        return self.section_type.floor_area * self.floors

    @property
    def effective_floor_height(self) -> float:
        """Эффективная высота типового этажа."""
        if self.floor_height is not None and self.floor_height > 0:
            return self.floor_height
        return getattr(self.section_type, "floor_height", _DEFAULT_FLOOR_HEIGHT)

    @property
    def effective_ground_floor_height(self) -> float:
        """Эффективная высота первого этажа (коммерческого при наличии)."""
        if self.ground_floor_height is not None and self.ground_floor_height > 0:
            return self.ground_floor_height
        return getattr(self.section_type, "ground_floor_height", self.effective_floor_height)

    @property
    def height(self) -> float:
        """Высота секции в метрах с учетом этажности и высоты этажа."""
        if self.section_type.has_commercial_ground and self.floors > 1:
            return round(
                self.effective_ground_floor_height + (self.floors - 1) * self.effective_floor_height,
                2,
            )
        return round(self.floors * self.effective_floor_height, 2)

    def get_apartments(self) -> dict[str, int]:
        """Получить количество квартир по типам для данной секции.

        Количество квартир на этаже умножается на количество жилых этажей.
        Если первый этаж коммерческий, жилых этажей на 1 меньше.

        Returns:
            Словарь {тип_квартиры: количество}.
        """
        # Определяем количество жилых этажей
        residential_floors = self.floors
        if self.section_type.has_commercial_ground:
            residential_floors = max(0, self.floors - 1)

        result: dict[str, int] = {}
        for apt_type, count_per_floor in self.section_type.apartments_per_floor.items():
            result[apt_type] = count_per_floor * residential_floors
        return result

    def __repr__(self) -> str:
        """Строковое представление размещённой секции."""
        flip_str = ", flipped" if self.is_flipped else ""
        return (
            f"PlacedSection('{self.section_type.id}', "
            f"pos=({self.x:.1f}, {self.y:.1f}), "
            f"angle={self.angle:.0f}°, floors={self.floors}{flip_str})"
        )


@dataclass
class Building:
    """Здание, состоящее из одной или нескольких секций.

    Attributes:
        sections: Список размещённых секций, составляющих здание.
        typology: Типология здания (LINEAR, L_SHAPE, U_SHAPE, COURTYARD).
    """

    sections: list[PlacedSection] = field(default_factory=list)
    typology: str = "LINEAR"

    @property
    def footprint(self) -> Polygon:
        """Объединённое пятно застройки здания (union всех секций).

        Returns:
            Полигон объединённого пятна застройки.

        Raises:
            ValueError: Если здание не содержит секций.
        """
        if not self.sections:
            raise ValueError("Здание не содержит секций.")

        footprints = [section.footprint for section in self.sections]
        union = unary_union(footprints)

        # Если из-за микропогрешностей стыковки вернулся MultiPolygon,
        # объединяем микрозазоры с помощью буфера без потери формы двора
        if union.geom_type == "MultiPolygon":
            merged = union.buffer(0.05).buffer(-0.05)
            if merged.geom_type == "Polygon":
                return merged

        return union

    @property
    def floors(self) -> int:
        """Максимальное количество этажей среди секций здания."""
        if not self.sections:
            return 0
        return max(section.floors for section in self.sections)

    @property
    def max_floors(self) -> int:
        """Максимальное количество этажей среди секций здания."""
        return self.floors

    @property
    def min_floors(self) -> int:
        """Минимальное количество этажей среди секций здания."""
        if not self.sections:
            return 0
        return min(section.floors for section in self.sections)

    @property
    def avg_floors(self) -> float:
        """Средняя этажность секций здания."""
        if not self.sections:
            return 0.0
        return sum(section.floors for section in self.sections) / len(self.sections)

    @property
    def total_gfa(self) -> float:
        """Общая площадь здания (сумма GFA всех секций) в м²."""
        return sum(section.gfa for section in self.sections)

    @property
    def total_building_area(self) -> float:
        """Площадь пятна застройки здания в м²."""
        return self.footprint.area

    @property
    def total_apartments(self) -> dict[str, int]:
        """Агрегированное количество квартир по типам.

        Returns:
            Словарь {тип_квартиры: суммарное_количество}.
        """
        totals: dict[str, int] = {}
        for section in self.sections:
            for apt_type, count in section.get_apartments().items():
                totals[apt_type] = totals.get(apt_type, 0) + count
        return totals

    @property
    def height(self) -> float:
        """Высота здания в метрах (максимальная высота среди размещенных секций)."""
        if not self.sections:
            return 0.0
        return max((section.height for section in self.sections), default=0.0)

    def get_apartment_count(self) -> dict[str, dict[str, int]]:
        """Получить детальную раскладку квартир по секциям.

        Returns:
            Словарь {id_секции: {тип_квартиры: количество}}.
        """
        breakdown: dict[str, dict[str, int]] = {}
        for section in self.sections:
            key = f"{section.section_type.id}_({section.x:.0f},{section.y:.0f})"
            breakdown[key] = section.get_apartments()
        return breakdown

    def add_section(self, section: PlacedSection) -> None:
        """Добавить секцию в здание.

        Args:
            section: Размещённая секция для добавления.
        """
        self.sections.append(section)

    def __repr__(self) -> str:
        """Строковое представление здания."""
        fl_str = f"{self.floors}" if self.min_floors == self.max_floors else f"{self.min_floors}-{self.max_floors}"
        return (
            f"Building(sections={len(self.sections)}, "
            f"floors={fl_str}, "
            f"gfa={self.total_gfa:.0f} м²)"
        )
