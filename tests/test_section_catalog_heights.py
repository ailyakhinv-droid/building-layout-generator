"""Тесты параметрического каталога секций, числовых ограничений высот и замка башни Б1."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.library.section_library import SectionLibrary
from src.library.excel_importer import import_sections_from_excel
from src.models.building import PlacedSection, Building
from dashboard_prototype.generator_service import (
    get_library_catalog,
    update_library_sections,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestSectionCatalogHeights(unittest.TestCase):
    """Проверка численных ограничений этажности и высот в каталоге секций."""

    def setUp(self) -> None:
        self.library = SectionLibrary(PROJECT_ROOT / "config" / "sections")
        update_library_sections({
            "sections": [
                {"id": "tower_b1", "min_floors": 12, "max_floors": 25},
                {"id": "mid_m8_9", "min_floors": 5, "max_floors": 9},
            ]
        })

    def tearDown(self) -> None:
        update_library_sections({
            "sections": [
                {"id": "tower_b1", "min_floors": 12, "max_floors": 25},
                {"id": "mid_m8_9", "min_floors": 5, "max_floors": 9},
            ]
        })

    def test_tower_b1_default_min_12_floors(self) -> None:
        """Секция Б1 по умолчанию имеет этажность от 12 этажей, если пользователь не задал иное."""
        tower_sec = self.library.get_by_id("tower_b1")
        self.assertIsNotNone(tower_sec)
        self.assertGreaterEqual(tower_sec.min_floors, 12)

        # Проверка создания PlacedSection: при создании с 0 или отрицательными этажами берется default_floors
        p_sec_def = PlacedSection(
            section_type=tower_sec,
            x=0.0,
            y=0.0,
            floors=0,
        )
        self.assertGreaterEqual(p_sec_def.floors, 12)
        self.assertGreaterEqual(p_sec_def.height, 38.0)

    def test_section_numerical_heights_properties(self) -> None:
        """Секции должны рассчитывать min_height_m и max_height_m по паспорту."""
        for sec in self.library.get_all():
            self.assertGreater(sec.min_height_m, 0.0)
            self.assertGreater(sec.max_height_m, sec.min_height_m)
            # Проверяем совпадение с формулой h1 + (N-1)*fh
            if sec.has_commercial_ground and sec.min_floors > 1:
                expected_min = round(sec.ground_floor_height + (sec.min_floors - 1) * sec.floor_height, 2)
            else:
                expected_min = round(sec.min_floors * sec.floor_height, 2)
            self.assertAlmostEqual(sec.min_height_m, expected_min, places=1)

    def test_catalog_endpoint_includes_numerical_heights(self) -> None:
        """Каталог секций для фронтенда должен содержать точные числовые высоты."""
        catalog = get_library_catalog()
        self.assertGreaterEqual(len(catalog), 9)
        b1 = next(item for item in catalog if item["id"] == "tower_b1")
        self.assertEqual(b1["min_floors"], 12)
        self.assertGreaterEqual(b1["min_height_m"], 38.0)
        self.assertGreaterEqual(b1["max_height_m"], 75.0)
        self.assertEqual(b1["floor_height"], 3.15)
        self.assertEqual(b1["ground_floor_height"], 4.20)

    def test_update_library_sections_allows_manual_input(self) -> None:
        """Пользователь может вручную задать любую этажность для секции через API."""
        res = update_library_sections({
            "sections": [
                {"id": "tower_b1", "min_floors": 8, "max_floors": 20},
                {"id": "mid_m8_9", "min_floors": 6, "max_floors": 9},
            ]
        })
        self.assertTrue(res["success"])
        b1_after = next(s for s in res["catalog"] if s["id"] == "tower_b1")
        self.assertEqual(b1_after["min_floors"], 8, "Пользовательское значение 8 должно быть сохранено")
        m8_after = next(s for s in res["catalog"] if s["id"] == "mid_m8_9")
        self.assertEqual(m8_after["min_floors"], 6)

        # Возвращаем секции к базовым параметрам
        update_library_sections({
            "sections": [
                {"id": "tower_b1", "min_floors": 12, "max_floors": 25},
                {"id": "mid_m8_9", "min_floors": 5, "max_floors": 9},
            ]
        })

    def test_excel_importer_parses_numerical_height_columns(self) -> None:
        """Импортер из sections.xlsx должен считывать числовые столбцы этажности и высот."""
        excel_file = PROJECT_ROOT / "data" / "sections.xlsx"
        if not excel_file.exists():
            self.skipTest("data/sections.xlsx не найден")

        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            imported = import_sections_from_excel(excel_file, tmp_dir)
            self.assertEqual(len(imported), 9)
            b1 = next(s for s in imported if s["section_code"] == "Б1")
            self.assertGreaterEqual(b1["min_floors"], 12)


if __name__ == "__main__":
    unittest.main()
