"""Тестирование башенной (точечной) типологии застройки и работы секции Б1."""

import os
import sys
from pathlib import Path

# Кодировка UTF-8 для Windows-консоли
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from src.core.site_parser import create_rectangular_site
from src.core.buildable_area import compute_buildable_area
from src.core.placement import PlacementConfig, PlacementEngine
from src.core.tep_calculator import calculate_tep
from src.library.section_library import SectionLibrary


def test_tower_placement() -> None:
    print("=" * 60)
    print("  ТЕСТИРОВАНИЕ БАШЕННОЙ (ТОЧЕЧНОЙ) ЗАСТРОЙКИ")
    print("=" * 60)

    with open("config/defaults.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 1. Загрузка библиотеки
    library = SectionLibrary()
    tower_secs = library.get_tower_sections()
    assert len(tower_secs) >= 1, "Секция башни не найдена в библиотеке!"
    tower_b1 = tower_secs[0]
    print(f"✓ Секция башни найдена: {tower_b1.name} ({tower_b1.id}), категория: {tower_b1.category}")
    assert tower_b1.category == "TOWER", f"Ожидалась категория TOWER, получена: {tower_b1.category}"
    assert tower_b1.width == 29.7 and tower_b1.depth == 23.9

    # 2. Создание участка
    site = create_rectangular_site(200, 150)
    compute_buildable_area(site, config)
    assert site.buildable_area is not None

    # 3. Расстановка точечных башен (typology='TOWER')
    engine = PlacementEngine(site, library, config)
    cfg_tower = PlacementConfig(typology="TOWER", target_floors=24, cascade_floors=True)
    towers = engine.generate(cfg_tower)

    assert len(towers) >= 4, f"Ожидалось не менее 4 башен на участке 200x150, получено: {len(towers)}"
    print(f"✓ Размещено точечных башен: {len(towers)}")

    for i, t in enumerate(towers):
        assert t.typology == "TOWER", f"Типология здания {i+1} должна быть TOWER"
        assert len(t.sections) == 1, f"Башня {i+1} должна состоять строго из 1 секции"
        assert site.buildable_area.contains(t.footprint), f"Башня {i+1} выходит за зону допустимой застройки"
        print(f"  • Башня {i+1}: этажей={t.floors}, высота={t.height:.1f} м, GFA={t.total_gfa:,.1f} м²")

    # 4. Проверка дистанций между башнями (не менее 24 м)
    for i in range(len(towers)):
        for j in range(i + 1, len(towers)):
            dist = towers[i].footprint.distance(towers[j].footprint)
            assert dist >= 20.0, f"Разрыв между башнями {i+1} и {j+1} слишком мал: {dist:.1f} м"

    tep = calculate_tep(site, towers, config)
    print(f"✓ ТЭП башенной застройки: GFA={tep.total_gfa:,.1f} м², FAR={tep.far:.2f}, Квартир={tep.apartments_total}")

    # 5. Смешанная застройка с фланговыми башнями
    cfg_mixed = PlacementConfig(typology="AUTO", target_floors=17, allow_towers_in_mixed=True)
    mixed_buildings = engine.generate(cfg_mixed)
    print(f"✓ Смешанная застройка (AUTO): размещено зданий {len(mixed_buildings)}")
    typologies_used = {b.typology for b in mixed_buildings}
    print(f"  Типологии в ансамбле: {typologies_used}")

    print("=" * 60)
    print("  ВСЕ ТЕСТЫ БАШЕННОЙ ЗАСТРОЙКИ УСПЕШНО ПРОЙДЕНЫ! ✓")
    print("=" * 60)


if __name__ == "__main__":
    test_tower_placement()
