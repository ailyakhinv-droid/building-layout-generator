"""Тестирование CAD-парсера (DXF / DWG) и интеграции с генератором застройки.

Проверяет:
1. Создание тестового чертежа DXF с замкнутой границей и красными линиями в МСК координатах.
2. Парсинг слоёв и сущностей.
3. Автоматическое определение слоя границы и слоя красных линий.
4. Нормализацию МСК-координат (с сохранением точки привязки).
5. Сборку границы из разрозненных отрезков LINE через polygonize.
6. Полный цикл расстановки зданий на CAD-участке и расчет ТЭП.
7. Корректный перехват DWGConversionError.
"""

import os
import sys
from pathlib import Path

# Кодировка UTF-8 для консоли Windows
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import ezdxf
import yaml
from shapely.geometry import Polygon

from src.core.cad_parser import (
    inspect_cad_layers,
    parse_cad_site,
    DWGConversionError,
)
from src.core.buildable_area import compute_buildable_area
from src.core.placement import PlacementConfig, PlacementEngine
from src.core.tep_calculator import calculate_tep
from src.library.section_library import SectionLibrary


def test_cad_pipeline():
    print("=" * 60)
    print("  ТЕСТИРОВАНИЕ CAD-ПАРСЕРА (DXF / DWG)")
    print("=" * 60)

    output_dir = PROJECT_ROOT / "output"
    output_dir.mkdir(exist_ok=True)
    test_dxf = output_dir / "test_boundary_msk.dxf"

    # 1. Создаем тестовый чертеж DXF с реальными координатами МСК-50
    # X ~ 502,300 м, Y ~ 2,198,000 м
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.add("ГРАНИЦА_УЧАСТКА", color=1)
    doc.layers.add("КРАСНЫЕ_ЛИНИИ", color=3)
    doc.layers.add("ТОПОСЪЕМКА_ТЕКСТ", color=7)

    base_x, base_y = 502300.0, 2198000.0
    pts = [
        (base_x + 0.0, base_y + 0.0),
        (base_x + 240.0, base_y + 0.0),
        (base_x + 240.0, base_y + 160.0),
        (base_x + 100.0, base_y + 160.0),
        (base_x + 0.0, base_y + 80.0),
    ]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "ГРАНИЦА_УЧАСТКА"})

    # Красная линия вдоль южной границы со сдвигом 8 м
    msp.add_line(
        (base_x + 0.0, base_y + 8.0),
        (base_x + 240.0, base_y + 8.0),
        dxfattribs={"layer": "КРАСНЫЕ_ЛИНИИ"},
    )
    doc.saveas(test_dxf)
    print(f"✓ Тестовый DXF создан: {test_dxf.name}")

    # 2. Инспекция слоев
    layers = inspect_cad_layers(test_dxf)
    print(f"✓ Найдено слоев с геометрией: {len(layers)}")
    for l in layers:
        print(f"  • Слой «{l.name}»: полилиний={l.polylines_count}, отрезков={l.lines_count}, "
              f"кандидат границы={l.is_candidate}, красные линии={l.is_red_line_candidate}")

    assert any(l.is_candidate for l in layers), "Слой границы не распознан как кандидат!"
    assert any(l.is_red_line_candidate for l in layers), "Слой красных линий не распознан!"

    # 3. Парсинг участка с автоопределением
    site, meta = parse_cad_site(test_dxf, normalize_origin=True)
    print(f"\n✓ Участок успешно импортирован:")
    print(f"  • Площадь: {site.area:,.1f} м²")
    print(f"  • Вершин контура: {meta['vertices_count']}")
    print(f"  • Слой границы: {meta['boundary_layer']}")
    print(f"  • Слой красных линий: {meta['red_lines_layer']} ({meta['red_lines_count']} шт.)")
    print(f"  • Сдвиг МСК привязки: ({site.base_offset[0]:,.1f}, {site.base_offset[1]:,.1f})")
    print(f"  • Локальные границы: {site.boundary.bounds}")

    assert site.area > 20000, "Некорректная площадь участка!"
    assert site.base_offset == (base_x, base_y), "Неверная точка привязки МСК!"
    assert len(site.red_lines) == 1, "Красная линия не извлечена!"

    # 4. Проверка генерации застройки на импортированном участке
    config_path = PROJECT_ROOT / "config" / "defaults.yaml"
    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    lib = SectionLibrary(PROJECT_ROOT / "config" / "sections")

    buildable = compute_buildable_area(site, config)
    print(f"\n✓ Зона застройки с учетом красных линий и отступов: {buildable.area:,.1f} м²")

    engine = PlacementEngine(site, lib, config)
    bldgs = engine.generate(PlacementConfig(target_floors=17, typology="AUTO"))
    print(f"✓ Размещено зданий: {len(bldgs)}")

    tep = calculate_tep(site, bldgs, config)
    print(f"✓ ТЭП: GFA={tep.total_gfa:,.0f} м², FAR={tep.far:.2f}, BCR={tep.bcr:.1%}, Квартир={tep.apartments_total}")

    assert len(bldgs) > 0, "Не удалось разместить здания на CAD-участке!"

    # 5. Тестирование сшивки разрозненных отрезков LINE в контур (polygonization)
    test_lines_dxf = output_dir / "test_lines_boundary.dxf"
    doc2 = ezdxf.new("R2010")
    msp2 = doc2.modelspace()
    doc2.layers.add("МЕЖА_УЧАСТКА", color=2)

    segments = [
        ((0, 0), (200, 0)),
        ((200, 0), (200, 150)),
        ((200, 150), (0, 150)),
        ((0, 150), (0, 0)),
    ]
    for p1, p2 in segments:
        msp2.add_line(p1, p2, dxfattribs={"layer": "МЕЖА_УЧАСТКА"})
    doc2.saveas(test_lines_dxf)

    site_lines, meta2 = parse_cad_site(test_lines_dxf, boundary_layer="МЕЖА_УЧАСТКА")
    print(f"\n✓ Сшивка отрезков LINE в контур:")
    print(f"  • Собрана замкнутая площадь: {site_lines.area:,.0f} м² (ожидалось 30,000 м²)")
    assert abs(site_lines.area - 30000.0) < 1.0, "Ошибка сшивки отрезков LINE!"

    # 6. Проверка обработки DWG без ODA
    mock_dwg = output_dir / "mock_sample.dwg"
    with open(mock_dwg, "wb") as f:
        f.write(b"AC1027_AUTOCAD_MOCK_DWG_CONTENT")

    dwg_caught = False
    try:
        parse_cad_site(mock_dwg)
    except DWGConversionError:
        dwg_caught = True

    assert dwg_caught, "DWGConversionError не был вызван для DWG файла!"
    print(f"✓ Проверка DWG без ODA: корректно вызвано понятное исключение DWGConversionError")

    print("\n" + "=" * 60)
    print("  ВСЕ ТЕСТЫ CAD-ПАРСЕРА ПРОЙДЕНЫ УСПЕШНО! ✓")
    print("=" * 60)


if __name__ == "__main__":
    test_cad_pipeline()
