"""Тестирование модуля кадастровой привязки и OSM визуализации."""

import os
import sys
from pathlib import Path

# Кодировка UTF-8 для вывода в консоль Windows
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from src.core.cadastre import (
    PRESET_PARCELS,
    parse_cadastral_components,
    resolve_cadastral_location,
    get_cadastral_parcel,
    create_site_from_cadastre,
)
from src.core.buildable_area import compute_buildable_area
from src.core.placement import PlacementConfig, PlacementEngine
from src.core.tep_calculator import calculate_tep
from src.library.section_library import SectionLibrary
from src.visualization.map_view import generate_leaflet_map_html


def test_cadastre_and_osm():
    print("=" * 60)
    print("  ТЕСТИРОВАНИЕ КАДАСТРОВОЙ ПРИВЯЗКИ И OSM-ВИЗУАЛИЗАЦИИ")
    print("=" * 60)

    # 1. Проверка распознавания различных регионов и округов РФ
    cases = [
        ("77:17:0120316:1024", "г. Москва", 55.5724, 37.4718),
        ("50:27:0010101:500", "Московская область", 55.4312, 37.5458),  # Подольск
        ("50:04:0010101:300", "Московская область", 56.3442, 37.5208),  # Дмитров
        ("66:41:0101001:500", "Свердловская область", 56.8389, 60.6057),  # Екатеринбург
        ("16:50:010101:200", "Республика Татарстан", 55.7887, 49.1221),  # Казань
        ("42:24:010101:500", "Кемеровская область", 55.3547, 86.0874),  # Кемерово
        ("78:34:0004286:115", "г. Санкт-Петербург", 60.0210, 30.2450),
        ("23:43:0106012:450", "Краснодарский край", 45.0712, 38.9125),
    ]

    for cad, exp_reg, exp_lat, exp_lon in cases:
        r_name, d_name, norm, lat, lon = resolve_cadastral_location(cad)
        assert exp_reg in r_name, f"Ожидался регион {exp_reg}, получено {r_name}"
        assert abs(lat - exp_lat) < 0.1, f"Широта не совпадает: {lat} vs {exp_lat}"
        assert abs(lon - exp_lon) < 0.1, f"Долгота не совпадает: {lon} vs {exp_lon}"
        print(f"✓ {cad} -> {r_name} ({d_name}): [{lat:.4f}, {lon:.4f}]")

    print("\n✓ Все регионы и округа РФ геокодируются точно по своим городам.")

    # 2. Проверка отсутствия ложных красных линий
    podolsk_parcel = get_cadastral_parcel("50:27:0010101:500")
    assert len(podolsk_parcel.red_lines_metric) == 0, "Ложная красная линия присутствует!"
    site_podolsk = create_site_from_cadastre(podolsk_parcel)
    assert len(site_podolsk.red_lines) == 0
    print("✓ По умолчанию красные линии отсутствуют (чистый контур участка).")

    # 3. Полный пайплайн генерации на участке Подольска (МО)
    config_path = PROJECT_ROOT / "config" / "defaults.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    library = SectionLibrary(PROJECT_ROOT / "config" / "sections")
    compute_buildable_area(site_podolsk, config)
    print(f"\n✓ Зона застройки вычислена: {site_podolsk.buildable_area.area:,.0f} м² (отступ 6м)")

    engine = PlacementEngine(site_podolsk, library, config)
    cfg = PlacementConfig(target_floors=14, typology="AUTO")
    buildings = engine.generate(cfg)
    assert len(buildings) > 0, "Здания не были сгенерированы!"
    print(f"✓ Сгенерировано зданий: {len(buildings)} шт.")

    tep = calculate_tep(site_podolsk, buildings, config)
    print(f"✓ ТЭП: GFA = {tep.total_gfa:,.0f} м², Квартир = {tep.apartments_total}, FAR = {tep.far:.2f}")

    # 4. Проверка HTML Leaflet карты (без красных линий и с темно-синей границей)
    html = generate_leaflet_map_html(site_podolsk, buildings, tep, height=580)
    assert "https://tile.openstreetmap.org" in html
    assert "50:27:0010101:500" in html
    assert "Корпус 1" in html
    assert "#1B4F72" in html, "Цвет границы должен быть темно-синим!"
    # Убеждаемся что в слоях нет красных линий если они не заданы
    assert '"red_lines": []' in html or '"type": "red_line"' not in html
    print(f"✓ HTML Leaflet карты сформирован корректно ({len(html):,} символов).")

    # 5. Проверка включения красной линии по запросу
    parcel_with_rl = get_cadastral_parcel("50:27:0010101:500", add_red_line=True)
    assert len(parcel_with_rl.red_lines_metric) == 1
    print("✓ Красная линия успешно создается только при явном запросе add_red_line=True.")

    # 6. Проверка вращения участка вокруг центроида (состыковка с УДС)
    orig_centroid = (site_podolsk.boundary.centroid.x, site_podolsk.boundary.centroid.y)
    site_podolsk.rotate(35.0)
    new_centroid = (site_podolsk.boundary.centroid.x, site_podolsk.boundary.centroid.y)
    assert abs(orig_centroid[0] - new_centroid[0]) < 1e-4
    assert abs(orig_centroid[1] - new_centroid[1]) < 1e-4
    assert site_podolsk.rotation_deg == 35.0
    print("✓ Вращение участка поворачивает геометрию вокруг центра без смещения координат.")

    print("\n" + "=" * 60)
    print("  ВСЕ ТЕСТЫ КАДАСТРА И OSM ПОДЛОЖКИ ПРОЙДЕНЫ УСПЕШНО!")
    print("=" * 60)


if __name__ == "__main__":
    test_cadastre_and_osm()
