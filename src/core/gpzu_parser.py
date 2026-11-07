"""Модуль парсинга градостроительных планов земельных участков (ГПЗУ) и выписок ЕГРН.

Поддерживает форматы:
- PDF (.pdf) — официальные градостроительные планы Минстроя РФ (Приказ № 741/пр / № 400/пр);
- Excel (.xlsx, .xls) — таблицы геодезических каталогов координат;
- Word (.docx) — текстовые градостроительные заключения и описания;
- Текстовые файлы (.txt, .csv) — экспорт каталогов поворотных точек.

Извлекает:
1. Кадастровый номер земельного участка;
2. Каталог координат характерных точек границ (X, Y в МСК или WGS-84);
3. Зоны с особыми условиями использования территорий (ЗОУИТ):
   - Охранные зоны инженерных сетей (водопровод, канализация, теплосети, ЛЭП, газопровод);
   - Санитарно-защитные зоны (СЗЗ);
   - Водоохранные зоны и прибрежные защитные полосы;
   - Зоны охраны объектов культурного наследия;
   - Приаэродромные территории;
4. Предельные параметры разрешенного строительства:
   - Минимальные отступы от границ участка (м);
   - Минимальные отступы от красных линий (м);
   - Предельная этажность и высота зданий (м);
   - Максимальный процент застройки (BCR).
"""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from src.core.cadastre import (
    create_site_from_coordinate_table,
    parse_coordinate_table,
    smart_resolve_location,
)
from src.geo.msk_converter import MSK_PRESETS, detect_msk_by_coordinates


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Извлечь весь текст из PDF документа ГПЗУ."""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages_text = []
        for idx, page in enumerate(reader.pages):
            txt = page.extract_text() or ""
            pages_text.append(txt)
        return "\n".join(pages_text)
    except Exception as e:
        return ""


def extract_text_from_docx(docx_bytes: bytes) -> str:
    """Извлечь текст из DOCX документа (без сторонних зависимостей через zipfile)."""
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
            xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            # Извлекаем все текстовые узлы <w:t>
            texts = [node.text for node in tree.iter() if node.tag.endswith("}t") and node.text]
            return " ".join(texts)
    except Exception:
        return ""


def extract_data_from_excel(
    excel_bytes: bytes,
) -> tuple[str, list[tuple[float, float]], list[dict[str, Any]]]:
    """Извлечь координаты и текст из Excel таблицы с группировкой по листам и секциям."""
    flat_coords: list[tuple[float, float]] = []
    lines: list[str] = []
    tables: list[dict[str, Any]] = []

    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
        for sheetname in wb.sheetnames:
            ws = wb[sheetname]
            curr_pts: list[tuple[float, float]] = []
            curr_title = sheetname
            prev_pt_idx: int | None = None

            for row in ws.iter_rows(values_only=True):
                if not row:
                    if len(curr_pts) >= 3:
                        tables.append({"title": curr_title, "points": list(curr_pts)})
                        curr_pts = []
                        prev_pt_idx = None
                    continue

                row_vals = [str(c).strip() for c in row if c is not None and str(c).strip() != ""]
                if not row_vals:
                    if len(curr_pts) >= 3:
                        tables.append({"title": curr_title, "points": list(curr_pts)})
                        curr_pts = []
                        prev_pt_idx = None
                    continue

                lines.append("\t".join(row_vals))

                # Проверяем, не заголовок ли это новой таблицы/зоны
                row_text = " ".join(row_vals)
                words = re.findall(r"[а-яА-ЯёЁa-zA-Z]{3,}", row_text)
                if len(words) >= 2 and not any(k in row_text.lower() for k in ("точка", "номер", "координат", "север", "восток", "геодезич")):
                    if len(curr_pts) >= 3:
                        tables.append({"title": curr_title, "points": list(curr_pts)})
                        curr_pts = []
                        prev_pt_idx = None
                    curr_title = f"{sheetname}: {row_text[:60]}"
                    continue

                # Поиск чисел и возможного номера точки
                nums: list[float] = []
                pt_id_num: int | None = None
                for idx_c, val in enumerate(row_vals):
                    val_clean = val.replace(",", ".").replace(" ", "").strip()
                    try:
                        v_flt = float(val_clean)
                        nums.append(v_flt)
                        if idx_c == 0 and v_flt.is_integer() and v_flt < 5000:
                            pt_id_num = int(v_flt)
                    except ValueError:
                        if idx_c == 0:
                            m_idx = re.search(r"\b(\d+)\b", val_clean)
                            if m_idx:
                                try:
                                    pt_id_num = int(m_idx.group(1))
                                except ValueError:
                                    pass

                if len(nums) >= 2:
                    # Детекция перезапуска нумерации характерных точек (новая зона)
                    if pt_id_num == 1 and prev_pt_idx is not None and prev_pt_idx > 1 and len(curr_pts) >= 3:
                        tables.append({"title": curr_title, "points": list(curr_pts)})
                        curr_pts = []
                        curr_title = f"{sheetname} (Контур {len(tables) + 1})"

                    if len(nums) >= 3 and nums[0].is_integer() and nums[0] < 5000:
                        pt = (nums[1], nums[2])
                    else:
                        pt = (nums[0], nums[1])

                    curr_pts.append(pt)
                    flat_coords.append(pt)
                    if pt_id_num is not None:
                        prev_pt_idx = pt_id_num

            if len(curr_pts) >= 3:
                tables.append({"title": curr_title, "points": list(curr_pts)})

    except Exception:
        pass

    return "\n".join(lines), flat_coords, tables


def is_plausible_coordinate_pair(c1: float, c2: float) -> bool:
    """Проверить, похожа ли пара чисел на реальные геодезические координаты (МСК или WGS-84)."""
    # 1. WGS-84 (градусы): 40..85 широта, 19..190 долгота
    if (40.0 <= c1 <= 85.0 and 19.0 <= c2 <= 190.0) or (40.0 <= c2 <= 85.0 and 19.0 <= c1 <= 190.0):
        # Исключаем малые целые числа (например проценты или отступы 50, 80)
        if c1.is_integer() and c2.is_integer() and c1 <= 100 and c2 <= 100:
            return False
        return True
    # 2. МСК / геодезические метры (>= 500 м)
    if abs(c1) >= 500.0 and abs(c2) >= 500.0:
        # Исключаем годы (1950..2050)
        if 1950 <= c1 <= 2050 and 1950 <= c2 <= 2050:
            return False
        return True
    # 3. Локальные метры для тестовых полигонов (исключая малые номера колонок 1..10)
    if c1.is_integer() and c2.is_integer() and 1 <= c1 <= 10 and 1 <= c2 <= 10:
        return False
    # Исключаем номера статей/пунктов законов (например 1.1, 57.3)
    if abs(c1) < 100.0 and abs(c2) < 100.0:
        return False
    return True


def classify_zone(
    title: str,
    points: list[tuple[float, float]],
    area: float = 0.0,
    is_largest: bool = False,
) -> tuple[str, str, str]:
    """Определить тип, роль и описание зоны по её названию и характеристикам.

    Returns:
        (zone_type, zone_role, description)
    """
    t_lower = title.lower()

    # 1. ЗОУИТ и охранные зоны (проверяем в первую очередь, чтобы исключить фразу "в границах охранных зон")
    zouit_keywords = (
        "охранн", "водопровод", "канализац", "лэп", "кабель", "газопровод",
        "теплотрасс", "теплосетей", "сзз", "санитарно", "водоохранн", "прибрежн",
        "затоплен", "подтоплен", "окн", "культурн", "приаэродромн", "полоса",
    )
    if any(k in t_lower for k in zouit_keywords):
        return (
            "zouit_exclusion",
            "zouit_exclusion",
            "Зона с особыми условиями использования (ЗОУИТ). По умолчанию вычитается из зоны застройки.",
        )

    # 2. Зона допустимого размещения зданий / пятно застройки
    if any(k in t_lower for k in ("допустим", "размещен", "пятно", "место строит", "пятн")):
        return (
            "buildable_envelope",
            "buildable_envelope",
            "Зона допустимого размещения зданий и сооружений (пятно застройки по разделу 1 ГПЗУ).",
        )

    # 3. Сервитуты и части ЗУ
    if any(k in t_lower for k in ("сервитут", "проезд", "проход", "чзу", "часть зу", "часть участка")):
        return (
            "easement",
            "easement",
            "Зона действия публичного сервитута / учетная часть ЗУ (ЧЗУ).",
        )

    # 4. Образуемый земельный участок (наивысший приоритет контура застройки)
    if any(k in t_lower for k in ("образуем", "образующ", ":зу", "зу1", "зу2", "зу3")):
        return (
            "boundary",
            "boundary",
            "Каталог характерных поворотных точек границ образуемого земельного участка.",
        )

    # 5. Граница ЗУ (внешний контур)
    boundary_keywords = (
        "описание границ", "границы земельного", "граница земельного",
        "граница участка", "границы участка", "контур зу", "контур 1", "контур участка",
        "границ", "земельн"
    )
    if any(k in t_lower for k in boundary_keywords):
        return (
            "boundary",
            "boundary",
            "Каталог характерных поворотных точек границ земельного участка (основной контур ЗУ).",
        )

    # Если явных ключевых слов нет:
    if is_largest:
        return (
            "boundary",
            "boundary",
            "Основной контур земельного участка (определен по наибольшей площади).",
        )

    return (
        "other",
        "other",
        "Дополнительный контур / зона из документа ГПЗУ.",
    )


def extract_all_coordinate_tables(
    text: str,
    excel_tables: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Найти все каталоги координат в тексте и сгруппировать их по зонам/контурам.

    Детектирует:
    - Разделы и заголовки зон (Границы ЗУ, Зона допустимого размещения, ЗОУИТ, Сервитуты);
    - Сброс нумерации характерных точек (1 после N) как границу контуров;
    - Вычисляет геометрию, замкнутость и площадь для каждой отдельной зоны.
    """
    raw_blocks: list[dict[str, Any]] = []

    if excel_tables:
        raw_blocks = list(excel_tables)
    else:
        lines = text.splitlines()
        curr_pts: list[tuple[float, float]] = []
        curr_labels: list[str] = []
        curr_title = "Каталог координат"
        prev_pt_idx: int | None = None

        header_keywords = (
            "каталог", "ведомост", "координат", "характерн", "описание границ",
            "раздел 1", "раздел 2", "чертеж", "допустим", "размещен", "пятно", "охранн",
            "сервитут", "зоуит", "чзу", "часть", "контур", "сзз", "водопровод", "лэп",
            "образуем", "образующ", "уточняем", "схема расположения", "межев", ":зу",
            "зу1", "зу2", "зу3", "земельн", "участк", "полоса", "водоохранн", "прибрежн",
            "санитарно-защитн",
        )

        table_header_noise = (
            "обозначение", "номер характерной точки", "характерной точки", "характерных точек",
            "перечень координат", "системе координат",
            "единого государственного реестра", "x y", "х у", "№ п/п", "№ точки", "1 2 3 4",
        )

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Пропускаем колонтитулы и маркеры страниц типа "Страница 1 из 17", "=== PAGE 1 ===", "1 из 17"
            if re.search(r"^(?:страница|\s*стр\.?|\s*=== page|\d+\s+из\s+\d+)", stripped, re.IGNORECASE):
                continue

            # Пропускаем строки с номерами законов, приказов и дат
            if re.search(r"(?:стать[яие|часть|п\.]\s*\d+|\b20\d\d\s*г|решение\s+городской\s+думы|приказ\s+минстроя)", stripped, re.IGNORECASE):
                continue

            # Пропускаем строки, оканчивающиеся на "- - -" (текстовые ЗОУИТ без координат)
            if re.search(r"-\s*-\s*-\s*$", stripped):
                continue

            words = re.findall(r"[а-яА-ЯёЁa-zA-Z]{2,}", stripped)

            # Если строка содержит 2 и более слов текста, это НЕ строка координат, а заголовок или описание
            if len(words) >= 2:
                low_line = stripped.lower()
                if any(k in low_line for k in header_keywords):
                    # Если это служебная шапка таблицы (X Y, Обозначение характерной точки) - НЕ меняем заголовок секции
                    if any(k in low_line for k in table_header_noise):
                        continue

                    # Настоящий заголовок новой секции/зоны
                    if len(curr_pts) >= 3:
                        raw_blocks.append({
                            "title": curr_title,
                            "points": list(curr_pts),
                            "labels": list(curr_labels),
                        })
                        curr_pts = []
                        curr_labels = []
                        prev_pt_idx = None
                    curr_title = stripped
                    continue
                else:
                    # Обычный текст (описание, примечание) между таблицами
                    if len(curr_pts) >= 3:
                        raw_blocks.append({
                            "title": curr_title,
                            "points": list(curr_pts),
                            "labels": list(curr_labels),
                        })
                        curr_pts = []
                        curr_labels = []
                        prev_pt_idx = None
                        curr_title = stripped
                    continue

            # Парсинг строки координат
            line_norm = re.sub(r"(\d+),(\d+)", r"\1.\2", stripped)
            parts = re.split(r"[,;\t|\s]+", line_norm)
            nums: list[float] = []
            pt_label_str: str | None = None
            pt_label_num: int | None = None

            for p in parts:
                p_clean = p.strip("(),[]{}:X=Y=x=y=Х=У=х=у=").strip()
                if not p_clean:
                    continue
                try:
                    val = float(p_clean)
                    nums.append(val)
                except ValueError:
                    # Распознавание меток точек: н1, Н1, n1, N1, н1(1), т.н1, т.1, 1'
                    m_pt = re.match(r"^(?:[тп]\.?)?([ннnNтtпp]?\s*(\d+)(?:\(\d+\))?['’]?)$", p_clean, re.IGNORECASE)
                    if m_pt:
                        pt_label_str = m_pt.group(1).replace(" ", "")
                        try:
                            pt_label_num = int(m_pt.group(2))
                        except ValueError:
                            pass

            if len(nums) >= 2:
                curr_pt_num: int | None = pt_label_num
                p_cand: tuple[float, float] | None = None

                # Поддержка 5 чисел (номер + X_сущ, Y_сущ, X_образ, Y_образ)
                if len(nums) >= 5 and nums[0].is_integer() and nums[0] < 5000:
                    p_cand = (nums[3], nums[4])
                    if pt_label_str is None:
                        pt_label_str = str(int(nums[0]))
                        curr_pt_num = int(nums[0])
                # Поддержка 4 чисел (X_сущ, Y_сущ, X_образ, Y_образ) -> берем образуемые!
                elif len(nums) == 4:
                    p_cand = (nums[2], nums[3])
                # Поддержка 3 чисел (номер + X, Y)
                elif len(nums) >= 3 and nums[0].is_integer() and nums[0] < 5000:
                    if curr_pt_num is None:
                        curr_pt_num = int(nums[0])
                    if pt_label_str is None:
                        pt_label_str = str(int(nums[0]))
                    p_cand = (nums[1], nums[2])
                else:
                    p_cand = (nums[0], nums[1])

                # ВАЛИДАЦИЯ КООРДИНАТ: отсеиваем номера страниц, годы и индексы колонок
                if not is_plausible_coordinate_pair(p_cand[0], p_cand[1]):
                    continue

                pt = p_cand

                if pt_label_str is None:
                    if "образуем" in curr_title.lower() or ":зу" in curr_title.lower():
                        pt_label_str = f"н{len(curr_pts) + 1}"
                    else:
                        pt_label_str = str(len(curr_pts) + 1)

                # Проверка перезапуска нумерации точек (1 после >1) — маркер нового контура
                if curr_pt_num == 1 and prev_pt_idx is not None and prev_pt_idx > 1 and len(curr_pts) >= 3:
                    raw_blocks.append({
                        "title": curr_title,
                        "points": list(curr_pts),
                        "labels": list(curr_labels),
                    })
                    curr_pts = []
                    curr_labels = []
                    curr_title = f"{curr_title} (Контур {len(raw_blocks) + 1})"
                elif (
                    curr_pt_num is not None
                    and prev_pt_idx is not None
                    and curr_pt_num < prev_pt_idx
                    and (prev_pt_idx - curr_pt_num) >= 2
                    and len(curr_pts) >= 3
                ):
                    raw_blocks.append({
                        "title": curr_title,
                        "points": list(curr_pts),
                        "labels": list(curr_labels),
                    })
                    curr_pts = []
                    curr_labels = []
                    curr_title = f"{curr_title} (Контур {len(raw_blocks) + 1})"

                curr_pts.append(pt)
                curr_labels.append(pt_label_str)
                if curr_pt_num is not None:
                    prev_pt_idx = curr_pt_num
            else:
                # Текстовое описание между таблицами
                if len(words) >= 3 and len(curr_pts) >= 3:
                    raw_blocks.append({
                        "title": curr_title,
                        "points": list(curr_pts),
                        "labels": list(curr_labels),
                    })
                    curr_pts = []
                    curr_labels = []
                    prev_pt_idx = None
                    curr_title = stripped

        if len(curr_pts) >= 3:
            raw_blocks.append({
                "title": curr_title,
                "points": list(curr_pts),
                "labels": list(curr_labels),
            })

    # Преобразование в структурированные зоны с расчетом площадей и Shapely
    from shapely.geometry import Polygon

    computed_blocks = []
    for b in raw_blocks:
        pts = b.get("points", [])
        raw_lbls = b.get("labels", [])
        # Дедупликация последовательных совпадающих точек с сохранением меток
        clean_pts: list[tuple[float, float]] = []
        clean_lbls: list[str] = []
        for idx_p, p in enumerate(pts):
            if not clean_pts or (abs(p[0] - clean_pts[-1][0]) > 1e-4 or abs(p[1] - clean_pts[-1][1]) > 1e-4):
                clean_pts.append(p)
                lbl = raw_lbls[idx_p] if idx_p < len(raw_lbls) else str(len(clean_pts))
                clean_lbls.append(lbl)

        if len(clean_pts) < 3:
            continue

        area_sqm = 0.0
        is_valid = False
        try:
            poly = Polygon(clean_pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly and not poly.is_empty:
                area_sqm = round(poly.area, 1)
                is_valid = True
        except Exception:
            pass

        computed_blocks.append({
            "title": b.get("title", "Каталог координат").strip(),
            "points": clean_pts,
            "labels": clean_lbls,
            "area_sqm": area_sqm,
            "is_valid": is_valid,
        })

    if not computed_blocks:
        return []

    # Находим блок с максимальной площадью (кандидат на основной контур ЗУ)
    max_area_idx = max(range(len(computed_blocks)), key=lambda i: computed_blocks[i]["area_sqm"])

    zones: list[dict[str, Any]] = []
    for idx, b in enumerate(computed_blocks):
        pts = b["points"]
        area_sqm = b["area_sqm"]
        is_largest = (idx == max_area_idx)

        z_type, z_role, z_desc = classify_zone(b["title"], pts, area_sqm, is_largest=is_largest)

        lbls = b.get("labels", [])
        formatted_coords = "\n".join(
            f"{lbls[i] if i < len(lbls) else (i + 1)}\t{x:.2f}\t{y:.2f}"
            for i, (x, y) in enumerate(pts)
        )

        zones.append({
            "id": f"zone_{idx + 1}",
            "name": b["title"],
            "type": z_type,
            "role": z_role,
            "points_count": len(pts),
            "coordinates": pts,
            "coordinates_text": formatted_coords,
            "area_sqm": area_sqm,
            "area_ha": round(area_sqm / 10000.0, 2),
            "is_valid": b["is_valid"],
            "default_apply": z_type in ("boundary", "buildable_envelope", "zouit_exclusion"),
            "description": z_desc,
        })

    return zones


def extract_zouit_restrictions(
    text: str,
    sub_tables: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Найти сведения о ЗОУИТ (зонах с особыми условиями использования территорий) в тексте ГПЗУ.

    Для каждой зоны определяет:
    - Наличие поворотных точек координат в документе (has_coordinates);
    - Построенные точки, площадь и статус;
    - Возможность ручного добавления/редактирования координат;
    - Является ли зона прямым запретом строительства (is_exclusion_zone).
    """
    zouit_list: list[dict[str, Any]] = []

    # Типовые шаблоны зон ограничений в российских градостроительных планах
    patterns = [
        (
            r"охранн\w+\s+зон\w+[^\.\n;]*(?:водопровод|водовод|канализац|сетей|водоснабжен)[^\.\n;]*",
            "Охранная зона водопровода/канализации",
            "Запрет капитального строительства в полосе сетей. Вычитается из зоны застройки.",
            True,
            ("водопровод", "водовод", "канализац", "водоснабжен"),
        ),
        (
            r"охранн\w+\s+зон\w+[^\.\n;]*(?:лэп|электросетев|электрическ|вл\s*\d+|кабельн)[^\.\n;]*",
            "Охранная зона электрических сетей (ЛЭП)",
            "Охранный коридор ЛЭП / кабельных линий. Строительство запрещено без выноса сетей.",
            True,
            ("лэп", "электросетев", "электрическ", "кабельн", "вл-"),
        ),
        (
            r"охранн\w+\s+зон\w+[^\.\n;]*(?:газопровод|газораспределит|газ)[^\.\n;]*",
            "Охранная зона газораспределительной сети",
            "Охранная зона газопровода высокого/среднего давления. Ограничение застройки.",
            True,
            ("газопровод", "газораспределит", "газ"),
        ),
        (
            r"охранн\w+\s+зон\w+[^\.\n;]*(?:теплотрасс|тепловы\w+\s+сет)[^\.\n;]*",
            "Охранная зона тепловых сетей",
            "Полоса отвода теплотрассы. Возведение капитальных зданий запрещено.",
            True,
            ("теплотрасс", "теплосет"),
        ),
        (
            r"(?:санитарно[\s\-]защитн\w+\s+зон\w+|сзз)[^\.\n;]*",
            "Санитарно-защитная зона (СЗЗ)",
            "Санитарно-защитная зона предприятий. Запрет размещения жилой застройки.",
            True,
            ("санитарно", "сзз"),
        ),
        (
            r"(?:водоохранн\w+\s+зон\w+|прибрежн\w+\s+защитн\w+\s+полос\w+)[^\.\n;]*",
            "Водоохранная зона / прибрежная полоса",
            "Специальный режим хозяйственной деятельности (ст. 65 Водного кодекса РФ).",
            False,
            ("водоохранн", "прибрежн", "полоса реки"),
        ),
        (
            r"(?:приаэродромн\w+\s+территори\w+|подзон\w+\s+приаэродромн\w+)[^\.\n;]*",
            "Приаэродромная территория",
            "Ограничение абсолютной высотной отметки (требуется согласование с Росавиацией).",
            False,
            ("приаэродромн", "аэродром"),
        ),
        (
            r"(?:культурн\w+\s+наследи\w+|памятник\w+\s+истории|окн|охран\w+\s+окн)[^\.\n;]*",
            "Зона охраны объекта культурного наследия",
            "Регламенты сохранения исторической среды и визуального восприятия ОКН.",
            False,
            ("окн", "культурн", "памятник"),
        ),
        (
            r"(?:зон\w+\s+затоплени\w+|подтоплени\w+)[^\.\n;]*",
            "Зона затопления / подтопления",
            "Требуется инженерная подготовка и защита территории до начала строительства.",
            False,
            ("затоплен", "подтоплен"),
        ),
    ]

    used_table_indices = set()
    seen_titles = set()
    zouit_counter = 0

    for regex, title, desc, is_excl, match_keywords in patterns:
        m = re.search(regex, text, re.IGNORECASE)
        if m and title not in seen_titles:
            seen_titles.add(title)
            zouit_counter += 1
            z_id = f"zouit_{zouit_counter}"
            snippet = m.group(0).strip()
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."

            # Поиск координатного каталога для данной ЗОУИТ
            matched_pts: list[tuple[float, float]] = []
            if sub_tables:
                # Ищем среди под-зон наиболее подходящий каталог по точным ключевым словам
                for t_idx, t_item in enumerate(sub_tables):
                    if t_idx in used_table_indices:
                        continue
                    t_title = (t_item.get("name") or t_item.get("title") or "").lower()
                    pts_candidate = t_item.get("coordinates") or t_item.get("points") or []
                    if not pts_candidate or len(pts_candidate) < 3:
                        continue

                    # Проверяем строгое совпадение доменных ключевых слов ЗОУИТ
                    if any(kw in t_title for kw in match_keywords):
                        matched_pts = pts_candidate
                        used_table_indices.add(t_idx)
                        break

            has_coords = len(matched_pts) >= 3
            coords_formatted = ""
            area_sqm = 0.0

            if has_coords:
                from shapely.geometry import Polygon
                try:
                    poly_z = Polygon(matched_pts)
                    area_sqm = round(poly_z.area, 1)
                except Exception:
                    area_sqm = 0.0
                coords_formatted = "\n".join(f"{i}\t{x:.2f}\t{y:.2f}" for i, (x, y) in enumerate(matched_pts, start=1))
                status_text = f"🟢 Найден каталог поворотных точек ({len(matched_pts)} точек, {round(area_sqm):,} м²)"
            else:
                status_text = "⚠️ Поворотные точки в документе отсутствуют (только текстовое описание)"

            zouit_list.append({
                "id": z_id,
                "type": "zouit",
                "name": title,
                "snippet": snippet,
                "description": desc,
                "is_exclusion_zone": is_excl,
                "has_coordinates": has_coords,
                "points_count": len(matched_pts),
                "coordinates": matched_pts,
                "coordinates_text": coords_formatted,
                "area_sqm": area_sqm,
                "status_text": status_text,
                "default_apply": is_excl and has_coords,
            })

    return zouit_list


def extract_gpzu_parameters(text: str) -> dict[str, Any]:
    """Извлечь нормативные параметры и отступы из текста ГПЗУ со сниппетами первоисточника."""
    params: dict[str, Any] = {}
    snippets: dict[str, str] = {}

    # 1. Минимальный отступ от границ земельного участка
    m_sb = re.search(
        r"(отступ\w*\s+от\s+границ\w*[^\d]*(\d+[\.,]?\d*)\s*м)",
        text,
        re.IGNORECASE,
    )
    if m_sb:
        params["boundary_setback"] = float(m_sb.group(2).replace(",", "."))
        snippets["boundary_setback"] = m_sb.group(1).strip()

    # 2. Минимальный отступ от красных линий
    m_rl = re.search(
        r"(отступ\w*\s+от\s+красн\w+\s+лини\w*[^\d]*(\d+[\.,]?\d*)\s*м)",
        text,
        re.IGNORECASE,
    )
    if m_rl:
        params["red_line_setback"] = float(m_rl.group(2).replace(",", "."))
        snippets["red_line_setback"] = m_rl.group(1).strip()

    # 3. Предельная высота зданий (в метрах)
    m_h = re.search(
        r"(предельн\w+\s+высот\w+[^\d]*(\d+[\.,]?\d*)\s*м)",
        text,
        re.IGNORECASE,
    )
    if m_h:
        params["max_building_height_m"] = float(m_h.group(2).replace(",", "."))
        snippets["max_building_height_m"] = m_h.group(1).strip()

    # 4. Предельная этажность
    m_fl = re.search(
        r"(предельн\w+\s+(?:этажност\w+|количеств\w+\s+этаж\w+)[^\d]*(\d+))",
        text,
        re.IGNORECASE,
    )
    if m_fl:
        params["max_floors"] = int(m_fl.group(2))
        snippets["max_floors"] = m_fl.group(1).strip()

    # 5. Максимальный процент застройки (BCR)
    m_bcr = re.search(
        r"((?:максимальн\w+\s+процент\s+застройк\w+|коэффициент\s+застройк\w+)[^\d]*(\d+[\.,]?\d*)\s*%)",
        text,
        re.IGNORECASE,
    )
    if m_bcr:
        bcr_val = float(m_bcr.group(2).replace(",", "."))
        if bcr_val > 1.0:
            bcr_val /= 100.0
        params["max_bcr"] = bcr_val
        snippets["max_bcr"] = m_bcr.group(1).strip()

    # 6. Коэффициент плотности застройки (FAR / Кпз)
    m_far = re.search(
        r"((?:коэффициент\s+плотност\w+\s+застройк\w+|плотност\w+\s+застройк\w+)[^\d]*(\d+[\.,]?\d*))",
        text,
        re.IGNORECASE,
    )
    if m_far:
        params["max_far"] = float(m_far.group(2).replace(",", "."))
        snippets["max_far"] = m_far.group(1).strip()

    # 7. Минимальное озеленение
    m_grn = re.search(
        r"((?:озеленен\w+|доля\s+озеленен\w+)[^\d]*не\s+менее[^\d]*(\d+[\.,]?\d*)\s*%)",
        text,
        re.IGNORECASE,
    )
    if m_grn:
        g_val = float(m_grn.group(2).replace(",", "."))
        if g_val > 1.0:
            g_val /= 100.0
        params["green_ratio_min"] = g_val
        snippets["green_ratio_min"] = m_grn.group(1).strip()

    params["snippets"] = snippets
    return params


def parse_gpzu_file(
    file_bytes: bytes,
    filename: str,
    msk_zone_override: str | None = None,
) -> dict[str, Any]:
    """Универсально разобрать файл ГПЗУ (PDF, Excel, Word или текст).

    Returns:
        Словарь с результатом парсинга:
        - success: bool
        - cadastral_number: str | None
        - points_count: int
        - coordinates_text: str (отформатированный каталог точек для вставки)
        - coordinate_system: str
        - area_sqm: float
        - area_ha: float
        - center: dict(lat, lon)
        - zouit: list[dict] (найденные ограничения и охранные зоны)
        - setbacks: dict (отступы и предельные параметры)
    """
    fn_lower = filename.lower()
    full_text = ""
    excel_pts: list[tuple[float, float]] = []
    excel_tables: list[dict[str, Any]] = []

    # 1. Извлечение текста и таблиц в зависимости от типа файла
    if fn_lower.endswith(".pdf"):
        full_text = extract_text_from_pdf(file_bytes)
    elif fn_lower.endswith((".xlsx", ".xls")):
        full_text, excel_pts, excel_tables = extract_data_from_excel(file_bytes)
    elif fn_lower.endswith(".docx"):
        full_text = extract_text_from_docx(file_bytes)
    else:
        # Текстовые файлы (.txt, .csv, .tsv)
        for enc in ("utf-8", "cp1251", "windows-1251", "latin1"):
            try:
                full_text = file_bytes.decode(enc)
                break
            except Exception:
                pass

    if not full_text and not excel_pts and not excel_tables:
        return {
            "success": False,
            "error": f"Не удалось прочитать содержимое файла '{filename}'. Убедитесь, что файл не поврежден и содержит текст или таблицу.",
        }

    # 2. Поиск кадастрового номера и площади ЗУ
    cad_match = re.search(r"\b(\d{2}:\d{1,2}:\d{6,7}:\d+)\b", full_text)
    detected_cad = cad_match.group(1) if cad_match else None

    stated_area = None
    m_area = re.search(r"площадь\s+земельного\s+участка[^\d]*(\d+[\s\d]*[\.,]?\d*)\s*(?:кв\.?\s*м|м²|га)", full_text, re.IGNORECASE)
    if m_area:
        try:
            val_str = m_area.group(1).replace(" ", "").replace(",", ".")
            stated_area = float(val_str)
            if "га" in m_area.group(0).lower():
                stated_area *= 10000.0
        except Exception:
            pass

    # 3. Извлечение каталогов координат с разделением по зонам
    zones = extract_all_coordinate_tables(full_text, excel_tables=excel_tables)

    primary_zone: dict[str, Any] | None = None
    if zones:
        # Приоритет 1: Зона образуемого земельного участка или границы ЗУ
        boundary_candidates = [
            z for z in zones if z["type"] == "boundary" or any(k in z["name"].lower() for k in ("образуем", "образующ", ":зу", "описание границ", "границы земельного"))
        ]
        if stated_area and boundary_candidates:
            # Ищем кандидата с максимально близкой площадью к указанной в документе
            primary_zone = min(boundary_candidates, key=lambda z: abs(z["area_sqm"] - stated_area))
        elif boundary_candidates:
            # Иначе берем кандидата с наибольшей площадью
            primary_zone = max(boundary_candidates, key=lambda z: z["area_sqm"])
        elif stated_area:
            primary_zone = min(zones, key=lambda z: abs(z["area_sqm"] - stated_area))
        else:
            primary_zone = max(zones, key=lambda z: z["area_sqm"])
        pts = primary_zone["coordinates"]
        formatted_coords_text = primary_zone["coordinates_text"]
    else:
        pts = excel_pts
        if not pts or len(pts) < 3:
            pts = parse_coordinate_table(full_text)
        if len(pts) >= 3:
            lines = [f"{idx}\t{p1:.2f}\t{p2:.2f}" for idx, (p1, p2) in enumerate(pts, start=1)]
            formatted_coords_text = "\n".join(lines)
            primary_zone = {
                "id": "zone_1",
                "name": "Основной контур земельного участка",
                "type": "boundary",
                "role": "boundary",
                "points_count": len(pts),
                "coordinates": pts,
                "coordinates_text": formatted_coords_text,
                "area_sqm": 0.0,
                "area_ha": 0.0,
                "is_valid": True,
                "default_apply": True,
                "description": "Контур участка из документа ГПЗУ.",
            }
            zones = [primary_zone]
        else:
            return {
                "success": False,
                "cadastral_number": detected_cad,
                "error": f"В файле '{filename}' не обнаружен каталог поворотных точек (требуется минимум 3 точки X, Y).",
            }

    # 4. Определение привязки и создание Site для основного контура
    reg_hint = None
    exp_center = None
    if detected_cad:
        _, _, _, c_lat, c_lon = smart_resolve_location(detected_cad)
        if c_lat != 0.0 and c_lon != 0.0:
            exp_center = (c_lat, c_lon)
            reg_hint = detected_cad.split(":")[0]

    try:
        site, meta = create_site_from_coordinate_table(
            formatted_coords_text,
            msk_zone=msk_zone_override,
            expected_center=exp_center,
            region_hint=reg_hint,
            cad_num=detected_cad,
        )
        if primary_zone:
            primary_zone["area_sqm"] = meta["area_sqm"]
            primary_zone["area_ha"] = meta["area_ha"]
    except Exception as e:
        return {
            "success": False,
            "cadastral_number": detected_cad,
            "error": f"Ошибка геометрического построения контура из ГПЗУ: {e}",
        }

    # 5. Поиск ЗОУИТ и параметров
    sub_tables = [z for z in zones if z["id"] != primary_zone["id"]]
    zouit_list = extract_zouit_restrictions(full_text, sub_tables=sub_tables)

    # Автоматически связываем под-зоны ZOUIT с каталогом ЗОУИТ
    existing_coords_sigs = {
        tuple(z.get("coordinates", [])[:3]) for z in zouit_list if z.get("coordinates")
    }
    for z in sub_tables:
        if z["type"] in ("zouit_exclusion", "easement"):
            sig = tuple(z["coordinates"][:3]) if len(z["coordinates"]) >= 3 else ()
            if sig and sig not in existing_coords_sigs:
                is_excl = (z["type"] == "zouit_exclusion")
                zouit_list.append({
                    "id": f"zouit_from_{z['id']}",
                    "type": "zouit",
                    "name": z["name"],
                    "snippet": f"Каталог координат ({z['points_count']} точек) из документа",
                    "description": z["description"],
                    "is_exclusion_zone": is_excl,
                    "has_coordinates": True,
                    "points_count": z["points_count"],
                    "coordinates": z["coordinates"],
                    "coordinates_text": z["coordinates_text"],
                    "area_sqm": z["area_sqm"],
                    "status_text": f"🟢 Каталог поворотных точек ({z['points_count']} точек, {round(z['area_sqm']):,} м²)",
                    "default_apply": is_excl,
                })

    setbacks = extract_gpzu_parameters(full_text)

    return {
        "success": True,
        "filename": filename,
        "cadastral_number": detected_cad or site.cadastral_number,
        "points_count": meta["points_count"],
        "coordinates_text": formatted_coords_text,
        "coordinate_system": meta["coordinate_system"],
        "area_sqm": meta["area_sqm"],
        "area_ha": meta["area_ha"],
        "center": {
            "lat": round(meta["center"][0], 6),
            "lon": round(meta["center"][1], 6),
        },
        "zones": zones,
        "zouit": zouit_list,
        "setbacks": setbacks,
        "snippets": setbacks.get("snippets", {}),
    }
