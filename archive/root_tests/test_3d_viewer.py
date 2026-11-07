"""Тест модуля интерактивной 3D-визуализации на MapLibre GL JS."""

import os
import sys
from pathlib import Path

# Кодировка UTF-8 для Windows консоли
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from shapely.geometry import Polygon, LineString

from src.models.site import Site
from src.library.section_library import SectionLibrary
from src.core.placement import PlacementConfig, PlacementEngine
from src.core.tep_calculator import calculate_tep
from src.core.buildable_area import compute_buildable_area
from src.visualization.viewer_3d import build_3d_geojson_data, generate_3d_viewer_html
from src.export.html_3d_export import export_3d_html


def test_3d_viewer():
    print("=" * 60)
    print("  ТЕСТИРОВАНИЕ 3D-ВИЗУАЛИЗАЦИИ НА MAPLIBRE GL JS")
    print("=" * 60)

    # 1. Создаем тестовый участок
    boundary = Polygon([(0, 0), (200, 0), (200, 150), (0, 150)])
    site = Site(
        boundary=boundary,
        setbacks={"default": 5.0},
        cadastral_number="47:07:1044001:555",
        address="Ленинградская обл., Всеволожский р-н",
        geo_center=(60.044377, 30.720331),
    )
    config = {"setbacks": {"default": 5.0}}
    site.buildable_area = compute_buildable_area(site, config)
    print(f"✓ Участок создан: {site.area} м², геоцентр: {site.geo_center}")

    # 2. Проверяем генерацию GeoJSON для предпросмотра (без зданий)
    preview_data = build_3d_geojson_data(site, buildings=None)
    assert "boundary" in preview_data
    assert "buildable" in preview_data
    assert len(preview_data["boundary"]["features"]) == 1
    assert len(preview_data["buildings"]["features"]) == 0
    print("✓ Предпросмотр GeoJSON структуры (без зданий) корректен")

    # 3. Расставляем здания с кастомной высотой этажа (3.3 м) и ограничением макс. высоты (30.0 м)
    import yaml
    with open("config/defaults.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    library = SectionLibrary(Path("config/sections"))
    engine = PlacementEngine(site, library, cfg)
    custom_floor_h = 3.3
    max_h_limit = 30.0
    placement_cfg = PlacementConfig(
        target_floors=14,  # запрашиваем 14 этажей (14 * 3.3 = 46.2 м > 30.0 м)
        floor_height=custom_floor_h,
        max_building_height_m=max_h_limit,
    )
    buildings = engine.generate(placement_cfg)
    tep = calculate_tep(site, buildings, cfg)
    print(f"✓ Размещено зданий: {len(buildings)}, суммарный GFA: {tep.total_gfa:,.1f} м²")

    # Проверяем, что ограничение максимальной высоты сработало (макс. 30м / 3.3м = 9 этажей)
    for b in buildings:
        assert b.height <= max_h_limit, f"Высота здания {b.height} превышает лимит {max_h_limit}"
        for s in b.sections:
            assert s.height <= max_h_limit
            assert s.effective_floor_height == custom_floor_h
    print(f"✓ Ограничение предельной высоты здания ({max_h_limit} м) и кастомная высота этажа ({custom_floor_h} м) соблюдены!")

    # 4. Проверяем генерацию GeoJSON с размещенными зданиями
    full_data = build_3d_geojson_data(site, buildings, tep)
    building_features = full_data["buildings"]["features"]
    assert len(building_features) > 0, "Должны быть сгенерированы секции зданий"

    first_feat = building_features[0]
    props = first_feat["properties"]
    print(f"✓ Сгенерировано 3D-секций: {len(building_features)}")
    print(f"  Пример секции: {props['full_name']}, {props['floors']} эт., высота {props['height']} м, GFA {props['gfa']} м²")

    assert props["floors"] > 0
    assert props["height"] > 0
    assert "building_name" in props
    assert "category_name" in props

    # 5. Генерация встроенного HTML
    embedded_html = generate_3d_viewer_html(
        site=site,
        buildings=buildings,
        tep=tep,
        title="Тестовый микрорайон 3D",
        height=600,
        default_basemap="light",
        standalone=False,
    )
    assert "<!doctype html>" in embedded_html
    assert "maplibregl" in embedded_html
    assert "fill-extrusion" in embedded_html
    assert "47:07:1044001:555" in embedded_html
    print("✓ Встроенный HTML сформирован (длина:", len(embedded_html), "символов)")

    # 6. Экспорт в автономный файл
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    export_file = output_dir / "test_site_3d.html"

    result_path = export_3d_html(
        site=site,
        buildings=buildings,
        tep=tep,
        filepath=export_file,
        title="3D-модель тестового участка",
        default_basemap="none",
    )
    assert result_path.exists()
    assert result_path.stat().st_size > 5000
    print(f"✓ Файл 3D-визуализации успешно экспортирован: {result_path} ({result_path.stat().st_size:,} байт)")

    print("=" * 60)
    print("  ВСЕ ТЕСТЫ 3D-ВИЗУАЛИЗАЦИИ УСПЕШНО ПРОЙДЕНЫ!")
    print("=" * 60)


if __name__ == "__main__":
    test_3d_viewer()
