"""Импортер типовых секций из файла Excel (Revit ADSK).

Читает спецификацию обобщенной модели жилых секций из Excel
и формирует набор валидированных JSON-файлов для библиотеки секций.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import openpyxl


def parse_num(val: Any) -> float:
    """Безопасное преобразование значения в число с плавающей точкой."""
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def import_sections_from_excel(
    excel_path: str | Path,
    output_dir: str | Path,
) -> list[dict[str, Any]]:
    """Импортировать секции из Excel-файла в каталог JSON-файлов.

    Args:
        excel_path: Путь к файлу sections.xlsx.
        output_dir: Директория для сохранения JSON файлов.

    Returns:
        Список созданных конфигураций секций.
    """
    excel_path = Path(excel_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.load_workbook(excel_path, data_only=True)
    sheet = wb.active

    # Извлечение заголовков (строка 2)
    headers = [sheet.cell(2, c).value for c in range(1, sheet.max_column + 1)]

    # Сопоставление категорий и диапазонов этажности по типам секций
    # Учитывает лифтовые узлы: <= 9 эт. (1 лифт), >= 10 эт. (2 лифта)
    meta_mapping = {
        "Б1": {
            "id": "tower_b1",
            "category": "MIDDLE",  # Точечная башня
            "min_floors": 12,
            "max_floors": 25,
            "elevators": 2,
        },
        "М2": {
            "id": "mid_m2_24",
            "category": "MIDDLE",
            "min_floors": 10,
            "max_floors": 25,
            "elevators": 2,
        },
        "М5": {
            "id": "mid_m5_15",
            "category": "MIDDLE",
            "min_floors": 10,
            "max_floors": 18,
            "elevators": 2,
        },
        "М8": {
            "id": "mid_m8_9",
            "category": "MIDDLE",
            "min_floors": 5,
            "max_floors": 9,
            "elevators": 1,
        },
        "М9": {
            "id": "mid_m9_7",
            "category": "MIDDLE",
            "min_floors": 5,
            "max_floors": 8,
            "elevators": 1,
        },
        "С": {
            "id": "corner_c",
            "category": "CORNER",
            "min_floors": 3,
            "max_floors": 9,
            "elevators": 1,
        },
        "Ш1": {
            "id": "end_sh1_9",
            "category": "END",
            "min_floors": 5,
            "max_floors": 9,
            "elevators": 1,
        },
        "Ш2": {
            "id": "end_sh2_8",
            "category": "END",
            "min_floors": 5,
            "max_floors": 9,
            "elevators": 1,
        },
        "Ю1": {
            "id": "corner_yu1",
            "category": "CORNER",
            "min_floors": 3,
            "max_floors": 9,
            "elevators": 1,
        },
    }

    # Примерные средние площади по типам квартир для распределения
    base_apt_areas = {
        "studio": 26.5,
        "1k": 38.0,
        "2k": 56.5,
        "3k": 76.0,
        "4k": 95.0,
    }

    imported_sections: list[dict[str, Any]] = []

    for row_idx in range(4, sheet.max_row + 1):
        row_vals = [sheet.cell(row_idx, c).value for c in range(1, sheet.max_column + 1)]
        if not any(v is not None for v in row_vals):
            continue

        row_dict = {headers[i]: row_vals[i] for i in range(len(headers)) if i < len(row_vals)}

        stype = str(row_dict.get("ТИП СЕКЦИИ", "")).strip()
        if not stype:
            continue

        meta = meta_mapping.get(
            stype,
            {
                "id": f"sec_{stype.lower()}",
                "category": "MIDDLE",
                "min_floors": 5,
                "max_floors": 17,
                "elevators": 1,
            },
        )

        name = str(row_dict.get("НАИМЕНОВАНИЕ СЕКЦИИ", f"Секция {stype}"))
        full_name = f"{name} ({stype})"

        # Геометрические размеры в метрах
        length_m = round(parse_num(row_dict.get("Секция_Длина")) / 1000.0, 2)
        width_m = round(parse_num(row_dict.get("Секция_Ширина")) / 1000.0, 2)

        # Малые габариты для угловых секций (L-shape)
        len_small_raw = row_dict.get("Секция_Длина малая")
        width_small_raw = row_dict.get("Секция_Ширина малая")
        len_small_m = round(parse_num(len_small_raw) / 1000.0, 2) if len_small_raw else None
        width_small_m = round(parse_num(width_small_raw) / 1000.0, 2) if width_small_raw else None

        # Для угловых Г-образных секций:
        # width_small = толщина бокового крыла (~13.2-13.6м)
        # depth_small = толщина верхнего крыла (~16.9-17.0м, стык со стандартными 17м корпусами)
        width_small = None
        depth_small = None
        if len_small_m and width_small_m:
            if abs(len_small_m - 17.0) < abs(width_small_m - 17.0):
                depth_small = len_small_m
                width_small = width_small_m
            else:
                depth_small = width_small_m
                width_small = len_small_m

        # В градостроительной модели: width = фасадный шаг, depth = глубина корпуса
        facade_width = length_m
        building_depth = width_m

        # Площади
        floor_area = round(parse_num(row_dict.get("Общая площадь типового этажа")), 2)
        living_area_typ = round(parse_num(row_dict.get("Площадь квартир на типовом этаже_С коэф")), 2)
        comm_area_ground = round(parse_num(row_dict.get("Общая площадь коммерческих помещений на первом этаже")), 2)

        # Высоты
        floor_height = round(parse_num(row_dict.get("Типовой этаж_Высота", 3150)) / 1000.0, 2)
        ground_floor_height = round(parse_num(row_dict.get("Первый этаж_Высота", 4200)) / 1000.0, 2)

        # Этажность по проекту
        default_floors = int(parse_num(row_dict.get("_Этажность", meta["default_floors"] if "default_floors" in meta else 9)))

        # Квартирография типового этажа
        st_count = int(parse_num(row_dict.get("Количество студий на типовом этаже")))
        k1_count = int(parse_num(row_dict.get("Количество 1К на типовом этаже")))
        k2_count = int(parse_num(row_dict.get("Количество 2К на типовом этаже")))
        k3_count = int(parse_num(row_dict.get("Количество 3К на типовом этаже")))
        k4_count = int(parse_num(row_dict.get("Количество 4К на типовом этаже")))

        apts_per_floor = {
            "studio": st_count,
            "1k": k1_count,
            "2k": k2_count,
            "3k": k3_count,
            "4k": k4_count,
        }

        # Вычисляем масштабированные площади квартир, чтобы сумма точно равнялась living_area_typ
        weighted_sum = sum(base_apt_areas[t] * count for t, count in apts_per_floor.items())
        ratio = (living_area_typ / weighted_sum) if weighted_sum > 0 else 1.0

        apt_areas = {
            t: round(base_apt_areas[t] * ratio, 1) if count > 0 else 0.0
            for t, count in apts_per_floor.items()
        }

        section_data = {
            "id": meta["id"],
            "name": full_name,
            "section_code": stype,
            "category": meta["category"],
            "width": facade_width,
            "depth": building_depth,
            "width_small": width_small,
            "depth_small": depth_small,
            "min_floors": meta["min_floors"],
            "max_floors": meta["max_floors"],
            "default_floors": default_floors,
            "elevators": meta["elevators"],
            "floor_area": floor_area,
            "living_area_per_floor": living_area_typ,
            "apartments_per_floor": apts_per_floor,
            "apt_areas": apt_areas,
            "has_commercial_ground": comm_area_ground > 0,
            "commercial_area_ground": comm_area_ground,
            "floor_height": floor_height,
            "ground_floor_height": ground_floor_height,
            "parking_per_apt": 0.5,
        }

        # Сохранение в JSON
        json_filename = f"{meta['id']}.json"
        json_path = output_dir / json_filename
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(section_data, f, ensure_ascii=False, indent=2)

        imported_sections.append(section_data)

    return imported_sections
