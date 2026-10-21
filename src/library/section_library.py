"""Библиотека типовых секций.

Загружает и хранит каталог типовых секций из JSON-файлов,
предоставляя удобный доступ по категории и идентификатору.
"""

from __future__ import annotations

from pathlib import Path

from src.models.section import SectionType


class SectionLibrary:
    """Библиотека типовых секций жилых домов.

    Загружает все JSON-файлы секций из указанной директории
    и предоставляет методы поиска и фильтрации.
    """

    def __init__(self, sections_dir: str | Path | None = None) -> None:
        """Инициализировать библиотеку секций.

        Args:
            sections_dir: Путь к директории с JSON-файлами секций.
                         Если None, используется путь по умолчанию.
        """
        self._sections: dict[str, SectionType] = {}

        if sections_dir is None:
            # Путь по умолчанию: config/sections/ относительно корня проекта
            sections_dir = Path(__file__).resolve().parent.parent.parent / "config" / "sections"

        self._dir = Path(sections_dir)
        self._load_all()

    def _load_all(self) -> None:
        """Загрузить все секции из директории."""
        if not self._dir.exists():
            raise FileNotFoundError(
                f"Директория секций не найдена: {self._dir}"
            )

        for json_file in sorted(self._dir.glob("*.json")):
            try:
                section = SectionType.from_json(json_file)
                self._sections[section.id] = section
            except Exception as e:
                print(f"Ошибка загрузки секции {json_file.name}: {e}")

        if not self._sections:
            print(f"Предупреждение: в {self._dir} не найдено ни одной секции.")

    def get_all(self) -> list[SectionType]:
        """Получить все секции из библиотеки.

        Returns:
            Список всех типов секций.
        """
        return list(self._sections.values())

    def get_by_id(self, section_id: str) -> SectionType | None:
        """Получить секцию по идентификатору.

        Args:
            section_id: Идентификатор секции.

        Returns:
            Тип секции или None, если не найдена.
        """
        return self._sections.get(section_id)

    def get_by_category(self, category: str) -> list[SectionType]:
        """Получить все секции указанной категории.

        Args:
            category: Категория секции (MIDDLE, CORNER, END).

        Returns:
            Список секций данной категории.
        """
        return [
            s for s in self._sections.values()
            if s.category.upper() == category.upper()
        ]

    def get_middle_sections(self) -> list[SectionType]:
        """Получить все рядовые секции."""
        return self.get_by_category("MIDDLE")

    def get_corner_sections(self) -> list[SectionType]:
        """Получить все угловые секции."""
        return self.get_by_category("CORNER")

    def get_end_sections(self) -> list[SectionType]:
        """Получить все торцевые секции."""
        return self.get_by_category("END")

    def get_tower_sections(self) -> list[SectionType]:
        """Получить все точечные (башенные) секции."""
        return [
            s for s in self._sections.values()
            if s.category.upper() == "TOWER"
            or s.id.lower().startswith("tower")
            or "точечн" in s.name.lower()
            or "башн" in s.name.lower()
        ]

    def get_sections_for_floors(self, floors: int) -> list[SectionType]:
        """Получить секции, поддерживающие заданную этажность (с учетом лифтовых ограничений)."""
        return [
            s for s in self._sections.values()
            if s.min_floors <= floors <= s.max_floors
        ]

    def get_by_elevators(self, elevators: int) -> list[SectionType]:
        """Получить секции с заданным количеством лифтов."""
        return [
            s for s in self._sections.values()
            if s.elevators == elevators
        ]

    @property
    def count(self) -> int:
        """Количество секций в библиотеке."""
        return len(self._sections)

    def __repr__(self) -> str:
        """Строковое представление библиотеки."""
        categories = {}
        for s in self._sections.values():
            cat = s.category
            categories[cat] = categories.get(cat, 0) + 1
        cat_str = ", ".join(f"{k}: {v}" for k, v in sorted(categories.items()))
        return f"SectionLibrary({self.count} секций: {cat_str})"
