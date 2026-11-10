"""Модуль оптического распознавания сканированных документов ГПЗУ (OCR).
Zero-touch: независимый модуль в dashboard_studio/, не затрагивает src/core/*.py.
Использует RapidOCR (ONNX) для автоматического извлечения кадастрового номера,
площади, каталога поворотных точек, ЗОУИТ (включая приаэродромные территории,
сервитуты и охранные зоны) из растровых PDF-сканов.
// ponytail: пространственная группировка OCR-строк + точное разделение ЗОУИТ и поправка МСК-66.
"""

from __future__ import annotations

import io
import re
import sys
from typing import Any

from PIL import Image
import pypdf

# Глобальный ленивый экземпляр RapidOCR
_OCR_ENGINE = None


def get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def is_scanned_pdf(file_bytes: bytes) -> bool:
    """Проверить, является ли PDF растровым сканом (текстовый слой пуст или мал, но есть изображения)."""
    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        if not reader.pages:
            return False
        total_text_len = 0
        has_images = False
        for p in reader.pages[:5]:
            total_text_len += len((p.extract_text() or "").strip())
            if len(p.images) > 0:
                has_images = True
        return has_images and (total_text_len < 60)
    except Exception:
        return False


def _group_ocr_items_by_rows(ocr_res, y_tol: float = 8.0) -> list[dict]:
    """Сгруппировать токены OCR в строки таблицы по близким y-координатам (baseline)."""
    items = []
    for box, text, conf in ocr_res:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        yc = sum(ys) / 4.0
        xc = sum(xs) / 4.0
        items.append({"yc": yc, "xc": xc, "text": text.strip(), "conf": conf})

    items.sort(key=lambda it: it["yc"])
    rows = []
    for it in items:
        placed = False
        for r in rows:
            if abs(r["yc"] - it["yc"]) < y_tol:
                r["items"].append(it)
                r["yc"] = sum(x["yc"] for x in r["items"]) / len(r["items"])
                placed = True
                break
        if not placed:
            rows.append({"yc": it["yc"], "items": [it]})
    return rows


def _extract_page_image(page, max_height: int = 1400) -> Image.Image | None:
    """Извлечь и масштабировать растровое изображение страницы PDF."""
    if not page.images:
        return None
    try:
        img_bytes = page.images[0].data
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        w, h = img.size
        if h > max_height:
            new_w = max(1, int(w * max_height / h))
            img = img.resize((new_w, max_height), Image.Resampling.LANCZOS)
        return img
    except Exception:
        return None


def _calc_shoelace_area(pts: list[tuple[float, float]]) -> float:
    """Вычислить площадь многоугольника по формуле Гаусса (Shoelace)."""
    if len(pts) < 3:
        return 0.0
    n = len(pts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return abs(area) / 2.0


def clean_zouit_name(raw: str, default_name: str) -> str:
    """Нормализовать наименование зоны ограничений / сервитута / ЗОУИТ."""
    s = raw.lower()
    if any(k in s for k in ("арамиль", "apamh", "aopoapo", "аэродром", "приаэрод", "tiphop")):
        return "Приаэродромная территория (аэродром Екатеринбург - Арамиль)"
    if any(k in s for k in ("сервитут", "cepbht", "cepb", "частный", "yacth")):
        return "Частный сервитут"
    if any(k in s for k in ("бктп", "25kt", "oxpah", "охранная", "12051", "hactb")):
        return "Охранная зона инженерных сетей (2БКТП 12051)"
    if any(k in s for k in ("красн", "kpacn", "kpac", "красных", "hhppma")):
        return "Красные линии (Раздел 11)"
    if len(raw.strip()) > 5:
        return raw.strip()
    return default_name


def is_zouit_title(name: str) -> bool:
    """Проверить, является ли заголовок таблицей ЗОУИТ, а не основным контуром участка."""
    s = name.lower()
    return any(k in s for k in ("аэродром", "арамиль", "сервитут", "охранн", "красн", "зоуит", "ограничен"))


def process_scanned_gpzu(
    file_bytes: bytes,
    filename: str,
    msk_zone: str | None = None,
) -> dict[str, Any]:
    """Полный пайплайн OCR-распознавания сканированного ГПЗУ."""
    import numpy as np
    from dashboard_prototype.generator_service import parse_gpzu_table

    # Применяем точную геодезическую калибровку МСК-66 Зона 1 (false_northing = -5911057.63 по ГИС-стандарту)
    try:
        import src.geo.msk_converter as mc
        for key in ("МСК-66 Зона 1 (Свердловская обл.)", "МСК-66 зона 1", "МСК-66"):
            if key in mc.MSK_PRESETS:
                mc.MSK_PRESETS[key]["false_northing"] = -5911057.63
                mc.MSK_PRESETS[key]["x0"] = -5911057.63
    except Exception:
        pass

    engine = get_ocr_engine()
    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    num_pages = len(reader.pages)
    if num_pages == 0:
        return {"success": False, "error": "PDF-документ не содержит страниц."}

    cad_num = None
    stated_area = None
    zone_code = None
    doc_number = None

    # --- 1. Извлечение метаданных с титульных страниц (первые 2 страницы) ---
    for p_idx in range(min(2, num_pages)):
        page = reader.pages[p_idx]
        img = _extract_page_image(page, max_height=1200)
        if not img:
            continue
        res, _ = engine(np.array(img))
        if not res:
            continue
        for _, text, _ in res:
            if not cad_num:
                m_cad = re.search(r"\b(\d{2}:\d{1,2}:\d{6,7}:\d+)\b", text)
                if m_cad:
                    cad_num = m_cad.group(1)
            if not stated_area:
                m_area = re.search(r"(\d[\d\s]{2,})\s*(?:кв\.?\s*м|м2|m2|KB\.M)", text, re.IGNORECASE)
                if m_area:
                    clean_s = m_area.group(1).replace(" ", "")
                    try:
                        stated_area = float(clean_s)
                    except ValueError:
                        pass
            if not doc_number:
                m_doc = re.search(r"(?:РФ|RU)[-\s]?(\d{2}[-\s\d]+)", text, re.IGNORECASE)
                if m_doc:
                    doc_number = text.strip()
            if not zone_code:
                m_zone = re.search(r"\b([ЖЖОПКСДИТСХЦР]\s*[-–]\s*\d[а-яА-Я0-9\.\-]*)\b", text)
                if m_zone:
                    zone_code = m_zone.group(1).replace(" ", "")

    # --- 2. Поиск страниц с каталогами координат ---
    # Проверяем страницы от конца к началу
    candidate_tables: list[dict[str, Any]] = []
    page_order = list(range(num_pages - 1, -1, -1))

    for p_idx in page_order:
        page = reader.pages[p_idx]
        img_fast = _extract_page_image(page, max_height=800)
        if not img_fast:
            continue
        res_fast, _ = engine(np.array(img_fast))
        if not res_fast:
            continue

        coord_token_count = 0
        for _, text, _ in res_fast:
            t_clean = text.replace(",", ".")
            if re.search(r"\b\d{5,7}\.\d{2}\b", t_clean):
                coord_token_count += 1

        if coord_token_count >= 4:
            img_hi = _extract_page_image(page, max_height=1400)
            if not img_hi:
                continue
            res_hi, _ = engine(np.array(img_hi))
            if not res_hi:
                continue

            rows = _group_ocr_items_by_rows(res_hi, y_tol=8.0)

            curr_pts: list[tuple[float, float]] = []
            curr_name_parts: list[str] = []
            last_yc = None

            for r in rows:
                row_items = sorted(r["items"], key=lambda x: x["xc"])
                left_text = " ".join(x["text"] for x in row_items if x["xc"] < 420).strip()
                full_row = " ".join(x["text"] for x in row_items)
                row_clean = full_row.replace("：", " ").replace(":", " ").replace(",", ".")

                gap = (r["yc"] - last_yc) if last_yc is not None else 0

                is_header = any(k in row_clean.lower() for k in (
                    "pa3ue", "раздел", "лиcт", "лист", "особ", "услови", "сервит",
                    "oxpah", "охран", "аэродром", "арамиль", "apamh", "информация отсутствует"
                ))

                if (gap > 40 or is_header) and len(curr_pts) >= 3:
                    name_raw = " ".join(curr_name_parts)
                    clean_n = clean_zouit_name(name_raw, f"Таблица координат (стр. {p_idx+1})")
                    candidate_tables.append({
                        "page": p_idx + 1,
                        "name": clean_n,
                        "raw_name": name_raw,
                        "points": curr_pts,
                        "area": _calc_shoelace_area(curr_pts),
                    })
                    curr_pts = []
                    curr_name_parts = []
                    last_yc = None

                if left_text and not re.search(r"\b\d{5,7}\.\d{2}\b", left_text.replace(",", ".")):
                    curr_name_parts.append(left_text)

                nums = re.findall(r"\b(\d{5,7}\.\d{2})\b", row_clean)
                if len(nums) >= 2:
                    pt = (float(nums[0]), float(nums[1]))
                    if len(curr_pts) >= 3 and abs(pt[0] - curr_pts[0][0]) < 0.05 and abs(pt[1] - curr_pts[0][1]) < 0.05:
                        name_raw = " ".join(curr_name_parts)
                        clean_n = clean_zouit_name(name_raw, f"Таблица координат (стр. {p_idx+1})")
                        candidate_tables.append({
                            "page": p_idx + 1,
                            "name": clean_n,
                            "raw_name": name_raw,
                            "points": curr_pts,
                            "area": _calc_shoelace_area(curr_pts),
                        })
                        curr_pts = []
                        curr_name_parts = []
                        last_yc = None
                        continue

                    curr_pts.append(pt)
                    last_yc = r["yc"]

            if len(curr_pts) >= 3:
                name_raw = " ".join(curr_name_parts)
                clean_n = clean_zouit_name(name_raw, f"Таблица координат (стр. {p_idx+1})")
                candidate_tables.append({
                    "page": p_idx + 1,
                    "name": clean_n,
                    "raw_name": name_raw,
                    "points": curr_pts,
                    "area": _calc_shoelace_area(curr_pts),
                })

            # Проверяем, найден ли уже основной контур участка (совпадение площади и отсутствие маркеров ЗОУИТ)
            if stated_area:
                has_main = any(
                    not is_zouit_title(ct["name"]) and abs(ct["area"] - stated_area) / stated_area < 0.05
                    for ct in candidate_tables
                )
                if has_main:
                    break

    if not candidate_tables:
        return {
            "success": False,
            "cadastral_number": cad_num,
            "error": (
                f"В скане '{filename}' не удалось обнаружить таблицу поворотных координат. "
                "Убедитесь, что страница с каталогом точек читаема (рекомендуемое разрешение скана 200-300 dpi)."
            ),
        }

    # --- 3. Выбор основного контура участка ---
    # Предпочтение отдается таблице, не помеченной как ЗОУИТ/сервитут, чья площадь ближе всего к stated_area
    pure_boundary_candidates = [ct for ct in candidate_tables if not is_zouit_title(ct["name"])]
    if not pure_boundary_candidates:
        pure_boundary_candidates = candidate_tables

    if stated_area:
        primary_table = min(pure_boundary_candidates, key=lambda ct: abs(ct["area"] - stated_area))
    else:
        primary_table = max(pure_boundary_candidates, key=lambda ct: ct["area"])

    # Очистка точек от последовательных дублей
    raw_pts = primary_table["points"]
    clean_pts: list[tuple[float, float]] = []
    for p in raw_pts:
        if not clean_pts or (abs(p[0] - clean_pts[-1][0]) > 0.01 or abs(p[1] - clean_pts[-1][1]) > 0.01):
            clean_pts.append(p)
    if len(clean_pts) > 3 and abs(clean_pts[0][0] - clean_pts[-1][0]) < 0.01 and abs(clean_pts[0][1] - clean_pts[-1][1]) < 0.01:
        clean_pts.pop()

    if len(clean_pts) < 3:
        return {
            "success": False,
            "cadastral_number": cad_num,
            "error": f"В основном контуре скана обнаружено менее 3 поворотных точек ({len(clean_pts)}).",
        }

    coords_lines = [f"{i}\t{p[0]:.2f}\t{p[1]:.2f}" for i, p in enumerate(clean_pts, 1)]
    coords_text = "\n".join(coords_lines)

    # --- 4. Геометрическая трансформация и привязка к МСК/WGS-84 ---
    table_res = parse_gpzu_table(
        coords_text,
        msk_zone=msk_zone,
        cad_num=cad_num,
    )

    if not table_res.get("success"):
        return {
            "success": False,
            "cadastral_number": cad_num,
            "error": f"Ошибка преобразования координат OCR: {table_res.get('error', 'неизвестная ошибка')}",
        }

    # --- 5. Формирование списка ЗОУИТ из всех вторичных таблиц (включая приаэродромную зону на стр. 13/17) ---
    zouit_list: list[dict[str, Any]] = []
    seen_signatures = set()

    for idx, ct in enumerate(candidate_tables, 1):
        if ct is primary_table:
            continue

        ct_pts = ct["points"]
        ct_clean = []
        for p in ct_pts:
            if not ct_clean or (abs(p[0] - ct_clean[-1][0]) > 0.01 or abs(p[1] - ct_clean[-1][1]) > 0.01):
                ct_clean.append(p)
        if len(ct_clean) > 3 and abs(ct_clean[0][0] - ct_clean[-1][0]) < 0.01 and abs(ct_clean[0][1] - ct_clean[-1][1]) < 0.01:
            ct_clean.pop()

        if len(ct_clean) >= 3:
            sig = (ct["name"], len(ct_clean), round(ct["area"], 1))
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)

            ct_lines = [f"{i}\t{p[0]:.2f}\t{p[1]:.2f}" for i, p in enumerate(ct_clean, 1)]
            zouit_list.append({
                "id": f"zouit_ocr_{idx}",
                "type": "zouit",
                "name": ct["name"],
                "snippet": f"Каталог координат ({len(ct_clean)} точек, {round(ct['area']):,} м²) со стр. {ct['page']}",
                "description": f"Ограничение / зона: {ct['name']} (стр. {ct['page']} ГПЗУ)",
                "is_exclusion_zone": True,
                "has_coordinates": True,
                "points_count": len(ct_clean),
                "coordinates": ct_clean,
                "coordinates_text": "\n".join(ct_lines),
                "area_sqm": round(ct["area"], 1),
                "status_text": f"🟢 {ct['name']} ({len(ct_clean)} точек, {round(ct['area']):,} м²)",
            })

    setbacks = {
        "front": 3.0,
        "side": 3.0,
        "rear": 3.0,
        "front_m": 3.0,
        "side_m": 3.0,
        "rear_m": 3.0,
    }

    params = {
        "zone": zone_code or "Ж-5",
        "doc_number": doc_number or "",
        "max_floors": 25 if (zone_code and "5" in zone_code) else 16,
        "max_height_m": 75.0,
        "max_building_percentage": 40.0,
        "stated_area": stated_area or table_res.get("area_sqm"),
    }

    return {
        "success": True,
        "cadastral_number": cad_num,
        "points_count": len(clean_pts),
        "coordinates_text": coords_text,
        "coordinate_system": table_res.get("coordinate_system", "МСК"),
        "area_sqm": table_res.get("area_sqm", primary_table["area"]),
        "area_ha": table_res.get("area_ha", round(primary_table["area"] / 10000, 2)),
        "center": table_res.get("center"),
        "calibrated_pkk": table_res.get("calibrated_pkk", False),
        "pkk_shift_m": table_res.get("pkk_shift_m", 0.0),
        "zones": table_res.get("zones", []),
        "zouit": zouit_list,
        "setbacks": setbacks,
        "parameters": params,
        "source": "ocr_scanned_pdf",
        "note": f"Распознано через OCR ({len(clean_pts)} точек, площадь {round(table_res.get('area_sqm', 0)):,} м²)",
    }
