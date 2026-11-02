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


def extract_data_from_excel(excel_bytes: bytes) -> tuple[str, list[tuple[float, float]]]:
    """Извлечь координаты и текст из Excel таблицы."""
    coords: list[tuple[float, float]] = []
    lines: list[str] = []
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
        for sheetname in wb.sheetnames:
            ws = wb[sheetname]
            for row in ws.iter_rows(values_only=True):
                if not row:
                    continue
                row_vals = [str(c).strip() for c in row if c is not None and str(c).strip() != ""]
                if not row_vals:
                    continue
                lines.append("\t".join(row_vals))

                # Поиск колонок X, Y в строке
                nums: list[float] = []
                for val in row_vals:
                    val_clean = val.replace(",", ".").replace(" ", "").strip()
                    try:
                        v_flt = float(val_clean)
                        nums.append(v_flt)
                    except ValueError:
                        pass
                if len(nums) >= 2:
                    if len(nums) >= 3 and nums[0].is_integer() and nums[0] < 5000:
                        coords.append((nums[1], nums[2]))
                    else:
                        coords.append((nums[0], nums[1]))
    except Exception:
        pass
    return "\n".join(lines), coords


def extract_zouit_restrictions(text: str) -> list[dict[str, Any]]:
    """Найти сведения о ЗОУИТ (зонах с особыми условиями использования территорий) в тексте ГПЗУ."""
    zouit_list: list[dict[str, Any]] = []

    # Типовые шаблоны зон ограничений в российских градостроительных планах
    patterns = [
        (
            r"охранн\w+\s+зон\w+[^\.\n;]*(?:водопровод|водовод|канализац|сетей|водоснабжен)[^\.\n;]*",
            "Охранная зона водопровода/канализации",
            "Запрет капитального строительства в полосе прохождения сетей. Требуется согласование с ресурсоснабжающей организацией.",
        ),
        (
            r"охранн\w+\s+зон\w+[^\.\n;]*(?:лэп|электросетев|электрическ|вл\s*\d+|кабельн)[^\.\n;]*",
            "Охранная зона электрических сетей (ЛЭП)",
            "Ограничение высоты кранов и зданий в охранной зоне воздушных/кабельных линий электропередачи.",
        ),
        (
            r"охранн\w+\s+зон\w+[^\.\n;]*(?:газопровод|газораспределит|газ)[^\.\n;]*",
            "Охранная зона газораспределительной сети",
            "Охранная зона газопровода высокого/среднего/низкого давления. Ограничение земляных и строительных работ.",
        ),
        (
            r"охранн\w+\s+зон\w+[^\.\n;]*(?:теплотрасс|тепловы\w+\s+сет)[^\.\n;]*",
            "Охранная зона тепловых сетей",
            "Запрет возведения зданий над полосой теплотрассы.",
        ),
        (
            r"(?:санитарно[\s\-]защитн\w+\s+зон\w+|сзз)[^\.\n;]*",
            "Санитарно-защитная зона (СЗЗ)",
            "Ограничение размещения жилой застройки и детских площадок до границы расчетной/установленной СЗЗ.",
        ),
        (
            r"(?:водоохранн\w+\s+зон\w+|прибрежн\w+\s+защитн\w+\s+полос\w+)[^\.\n;]*",
            "Водоохранная зона / прибрежная полоса",
            "Специальный режим хозяйственной деятельности по Водному кодексу РФ (от 50 до 200 м от береговой линии).",
        ),
        (
            r"(?:приаэродромн\w+\s+территори\w+|подзон\w+\s+приаэродромн\w+)[^\.\n;]*",
            "Приаэродромная территория",
            "Ограничение предельной абсолютной высоты застройки и согласование с Росавиацией.",
        ),
        (
            r"(?:культурн\w+\s+наследи\w+|памятник\w+\s+истории|окн|охран\w+\s+окн)[^\.\n;]*",
            "Зона охраны объекта культурного наследия",
            "Ограничение высотности, визуального восприятия и соблюдение регламентов сохранения исторической среды.",
        ),
        (
            r"(?:зон\w+\s+затоплени\w+|подтоплени\w+)[^\.\n;]*",
            "Зона затопления / подтопления",
            "Требуется инженерная защита территории (дамбы, подсыпка грунта) до начала строительства.",
        ),
    ]

    seen_titles = set()
    for regex, title, desc in patterns:
        m = re.search(regex, text, re.IGNORECASE)
        if m and title not in seen_titles:
            seen_titles.add(title)
            snippet = m.group(0).strip()
            # Ограничиваем длину сниппета для аккуратного отображения
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."
            zouit_list.append({
                "type": "zouit",
                "name": title,
                "snippet": snippet,
                "description": desc,
            })

    return zouit_list


def extract_gpzu_parameters(text: str) -> dict[str, Any]:
    """Извлечь нормативные параметры и отступы из текста ГПЗУ."""
    params: dict[str, Any] = {}

    # 1. Минимальный отступ от границ земельного участка
    m_sb = re.search(
        r"отступ\w*\s+от\s+границ\w*[^\d]*(\d+[\.,]?\d*)\s*м",
        text,
        re.IGNORECASE,
    )
    if m_sb:
        params["boundary_setback"] = float(m_sb.group(1).replace(",", "."))

    # 2. Минимальный отступ от красных линий
    m_rl = re.search(
        r"отступ\w*\s+от\s+красн\w+\s+лини\w*[^\d]*(\d+[\.,]?\d*)\s*м",
        text,
        re.IGNORECASE,
    )
    if m_rl:
        params["red_line_setback"] = float(m_rl.group(1).replace(",", "."))

    # 3. Предельная высота зданий (в метрах)
    m_h = re.search(
        r"предельн\w+\s+высот\w+[^\d]*(\d+[\.,]?\d*)\s*м",
        text,
        re.IGNORECASE,
    )
    if m_h:
        params["max_building_height_m"] = float(m_h.group(1).replace(",", "."))

    # 4. Предельная этажность
    m_fl = re.search(
        r"предельн\w+\s+(?:этажност\w+|количеств\w+\s+этаж\w+)[^\d]*(\d+)",
        text,
        re.IGNORECASE,
    )
    if m_fl:
        params["max_floors"] = int(m_fl.group(1))

    # 5. Максимальный процент застройки (BCR)
    m_bcr = re.search(
        r"(?:максимальн\w+\s+процент\s+застройк\w+|коэффициент\s+застройк\w+)[^\d]*(\d+[\.,]?\d*)\s*%",
        text,
        re.IGNORECASE,
    )
    if m_bcr:
        bcr_val = float(m_bcr.group(1).replace(",", "."))
        if bcr_val > 1.0:
            bcr_val /= 100.0
        params["max_bcr"] = bcr_val

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

    # 1. Извлечение текста в зависимости от типа файла
    if fn_lower.endswith(".pdf"):
        full_text = extract_text_from_pdf(file_bytes)
    elif fn_lower.endswith((".xlsx", ".xls")):
        full_text, excel_pts = extract_data_from_excel(file_bytes)
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

    if not full_text and not excel_pts:
        return {
            "success": False,
            "error": f"Не удалось прочитать содержимое файла '{filename}'. Убедитесь, что файл не поврежден и содержит текст или таблицу.",
        }

    # 2. Поиск кадастрового номера
    cad_match = re.search(r"\b(\d{2}:\d{1,2}:\d{6,7}:\d+)\b", full_text)
    detected_cad = cad_match.group(1) if cad_match else None

    # 3. Извлечение каталога координат
    pts = excel_pts
    if not pts or len(pts) < 3:
        # Поиск таблицы координат в тексте
        pts = parse_coordinate_table(full_text)

    if len(pts) < 3:
        return {
            "success": False,
            "cadastral_number": detected_cad,
            "error": f"В файле '{filename}' не обнаружен каталог поворотных точек (требуется минимум 3 точки X, Y).",
        }

    # 4. Формирование чистого текста каталога координат
    lines = []
    for idx, (p1, p2) in enumerate(pts, start=1):
        lines.append(f"{idx}\t{p1:.2f}\t{p2:.2f}")
    formatted_coords_text = "\n".join(lines)

    # 5. Определение привязки и создание Site
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
    except Exception as e:
        return {
            "success": False,
            "cadastral_number": detected_cad,
            "error": f"Ошибка геометрического построения контура из ГПЗУ: {e}",
        }

    # 6. Поиск ЗОУИТ и параметров
    zouit_list = extract_zouit_restrictions(full_text)
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
        "zouit": zouit_list,
        "setbacks": setbacks,
    }
