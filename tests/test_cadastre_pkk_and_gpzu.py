import unittest
from shapely.geometry import Polygon

from src.core.cadastre import (
    fetch_pkk_parcel_data,
    parse_coordinate_table,
    create_site_from_coordinate_table,
    get_cadastral_parcel,
)
from dashboard_prototype.generator_service import (
    lookup_pkk_parcel,
    parse_gpzu_table,
    preview_site,
    process_gpzu_upload,
    run_pipeline,
)
from src.core.gpzu_parser import parse_gpzu_file


class TestCadastrePKKAndGPZU(unittest.TestCase):
    """Тестирование загрузки границ с ПКК Росреестра и парсинга каталога координат ГПЗУ."""

    def test_parse_coordinate_table_formats(self):
        # Формат с номерами точек и разделителями пробелами
        text1 = """
        1  337979.12  1475315.11
        2  338015.68  1475301.40
        3  337968.30  1475176.38
        """
        pts1 = parse_coordinate_table(text1)
        self.assertEqual(len(pts1), 3)
        self.assertAlmostEqual(pts1[0][0], 337979.12)
        self.assertAlmostEqual(pts1[0][1], 1475315.11)

        # Формат с запятыми в качестве десятичных знаков и табуляцией
        text2 = """
        1\t337979,12\t1475315,11
        2\t338015,68\t1475301,40
        3\t337968,30\t1475176,38
        """
        pts2 = parse_coordinate_table(text2)
        self.assertEqual(len(pts2), 3)
        self.assertAlmostEqual(pts2[0][0], 337979.12)

        # Формат без нумерации точек (только X, Y)
        text3 = """
        57.161069, 65.674079
        57.162000, 65.675000
        57.161500, 65.676000
        """
        pts3 = parse_coordinate_table(text3)
        self.assertEqual(len(pts3), 3)
        self.assertAlmostEqual(pts3[0][0], 57.161069)
        self.assertAlmostEqual(pts3[0][1], 65.674079)

    def test_create_site_from_gpzu_msk(self):
        # Каталог координат ЖК Акватория (Тюмень, МСК-72)
        sample_gpzu = """
        1  337979.12  1475315.11
        2  338015.68  1475301.40
        3  337968.30  1475176.38
        4  337938.10  1475096.70
        5  337944.09  1475094.52
        6  337935.04  1475069.68
        7  337760.60  1475134.20
        8  337798.15  1475235.11
        9  337846.77  1475364.75
        1  337979.12  1475315.11
        """
        site, meta = create_site_from_coordinate_table(
            sample_gpzu,
            msk_zone="МСК-72 Зона 1 (Тюмень)",
            cad_num="72:23:0222001:16187",
        )
        self.assertEqual(meta["points_count"], 9)
        self.assertAlmostEqual(meta["area_sqm"], 44381.1, places=0)
        self.assertAlmostEqual(site.geo_center[0], 57.1602, places=2)
        self.assertAlmostEqual(site.geo_center[1], 65.6725, places=2)
        self.assertTrue(site.boundary.is_valid)

    def test_create_site_from_wgs84(self):
        sample_wgs = """
        57.161069 65.674079
        57.162000 65.674079
        57.162000 65.676000
        57.161069 65.676000
        """
        site, meta = create_site_from_coordinate_table(sample_wgs)
        self.assertEqual(meta["coordinate_system"], "WGS-84")
        self.assertEqual(meta["points_count"], 4)
        self.assertGreater(site.area, 5000)

    def test_pkk_fetch_or_cache(self):
        # Проверяем кадастровый номер из базы Росреестра
        data = lookup_pkk_parcel("16:50:010101:1")
        if data.get("success"):
            self.assertEqual(data["cadastral_number"], "16:50:010101:1")
            self.assertGreater(data["points_count"], 10)
            self.assertGreater(data["area_sqm"], 50000)

    def test_preview_and_pipeline_with_gpzu(self):
        sample_gpzu = """
        1  337979.12  1475315.11
        2  338015.68  1475301.40
        3  337968.30  1475176.38
        4  337938.10  1475096.70
        5  337944.09  1475094.52
        6  337935.04  1475069.68
        7  337760.60  1475134.20
        8  337798.15  1475235.11
        9  337846.77  1475364.75
        """
        # Этап 1: Предпросмотр участка
        preview_res = preview_site({
            "site_mode": "cadastre",
            "cad_query": "72:23:0222001:16187",
            "gpzu_coordinates": sample_gpzu,
            "msk_zone": "МСК-72 Зона 1 (Тюмень)",
        })
        self.assertEqual(preview_res["stage"], 1)
        self.assertAlmostEqual(preview_res["site_area_sqm"], 44381.1, places=0)
        self.assertIn("cad_info", preview_res)
        self.assertTrue(preview_res["cad_info"]["is_gpzu"])

        # Этап 2: Полная генерация застройки
        gen_res = run_pipeline({
            "site_mode": "cadastre",
            "cad_query": "72:23:0222001:16187",
            "gpzu_coordinates": sample_gpzu,
            "msk_zone": "МСК-72 Зона 1 (Тюмень)",
            "layout_type": "QUARTER",
            "target_floors": 9,
        })
        self.assertIn("tep", gen_res)
        self.assertGreater(len(gen_res["buildings"]), 0)
        self.assertGreater(gen_res["tep"]["gfa"], 10000)

    def test_gpzu_file_parser_text_and_zouit(self):
        sample_doc = """
        ГРАДОСТРОИТЕЛЬНЫЙ ПЛАН ЗЕМЕЛЬНОГО УЧАСТКА
        № РФ-72-2-00-0-00-2023-016187
        Кадастровый номер: 72:23:0222001:16187
        Адрес: Тюменская область, г. Тюмень

        1.1. Каталог координат характерных точек границ:
        1  337979.12  1475315.11
        2  338015.68  1475301.40
        3  337968.30  1475176.38
        4  337938.10  1475096.70
        5  337944.09  1475094.52
        6  337935.04  1475069.68
        7  337760.60  1475134.20
        8  337798.15  1475235.11
        9  337846.77  1475364.75

        1.3. Сведения о зонах с особыми условиями использования (ЗОУИТ):
        - Охранная зона водопровода и сетей водоснабжения Ду 500.
        - Водоохранная зона реки Тура.

        Раздел 2. Предельные параметры разрешенного строительства
        Минимальный отступ от границ земельного участка: 3.0 м
        Минимальный отступ от красных линий: 5.0 м
        Предельная высота: 75.0 м
        Предельная этажность: 25
        Максимальный процент застройки: 40%
        """
        res = parse_gpzu_file(sample_doc.encode("utf-8"), "gpzu_sample.txt")
        self.assertTrue(res["success"])
        self.assertEqual(res["cadastral_number"], "72:23:0222001:16187")
        self.assertEqual(res["points_count"], 9)
        self.assertAlmostEqual(res["area_sqm"], 44381.1, places=0)
        self.assertGreaterEqual(len(res["zouit"]), 2)
        self.assertEqual(res["setbacks"]["boundary_setback"], 3.0)
        self.assertEqual(res["setbacks"]["red_line_setback"], 5.0)

    def test_gpzu_excel_parser(self):
        import openpyxl
        import io
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Координаты"
        ws.append(["№", "X", "Y"])
        coords = [
            (1, 337979.12, 1475315.11),
            (2, 338015.68, 1475301.40),
            (3, 337968.30, 1475176.38),
            (4, 337938.10, 1475096.70),
            (5, 337944.09, 1475094.52),
            (6, 337935.04, 1475069.68),
            (7, 337760.60, 1475134.20),
            (8, 337798.15, 1475235.11),
            (9, 337846.77, 1475364.75),
        ]
        for row in coords:
            ws.append(list(row))
        buf = io.BytesIO()
        wb.save(buf)
        excel_bytes = buf.getvalue()

        res = process_gpzu_upload(excel_bytes, "site_coords.xlsx", msk_zone="МСК-72 Зона 1 (Тюмень)")
        self.assertTrue(res["success"])
        self.assertEqual(res["points_count"], 9)
        self.assertAlmostEqual(res["area_sqm"], 44381.1, places=0)
        self.assertIn("МСК-72", res["coordinate_system"])

    def test_digitized_contour_flow(self):
        # Имитация работы пользователя (Вариант 1): клики по карте в WGS-84
        digitized_clicks = [
            (57.160000, 65.670000),
            (57.162000, 65.670000),
            (57.162000, 65.673000),
            (57.160000, 65.673000),
        ]
        coords_str = "\n".join(f"{idx+1}\t{pt[0]}\t{pt[1]}" for idx, pt in enumerate(digitized_clicks))

        preview_res = preview_site({
            "site_mode": "cadastre",
            "cad_query": "72:23:0222001:16187",
            "gpzu_coordinates": coords_str,
        })
        self.assertEqual(preview_res["stage"], 1)
        self.assertGreater(preview_res["site_area_sqm"], 20000)
        self.assertEqual(preview_res["vertices_count"], 4)
        self.assertAlmostEqual(preview_res["geo_center"]["lat"], 57.1610, places=2)
        self.assertAlmostEqual(preview_res["geo_center"]["lon"], 65.6715, places=2)


    def test_gpzu_multi_zone_grouping(self):
        # ГПЗУ с 3 отдельными таблицами: Граница ЗУ, Пятно допустимого размещения, Охранная зона водопровода
        multi_zone_doc = """
        ГРАДОСТРОИТЕЛЬНЫЙ ПЛАН ЗЕМЕЛЬНОГО УЧАСТКА
        Кадастровый номер: 72:23:0222001:16187

        Раздел 1.1. Каталог координат характерных точек границ земельного участка:
        1  337979.12  1475315.11
        2  338015.68  1475301.40
        3  337968.30  1475176.38
        4  337938.10  1475096.70
        5  337760.60  1475134.20
        6  337798.15  1475235.11
        7  337846.77  1475364.75

        Раздел 1.2. Чертеж. Зона допустимого размещения зданий, строений, сооружений:
        1  337960.00  1475300.00
        2  337950.00  1475200.00
        3  337800.00  1475180.00
        4  337820.00  1475280.00

        Раздел 1.3. Охранная зона водопровода Ду 500:
        1  337900.00  1475250.00
        2  337910.00  1475260.00
        3  337905.00  1475270.00
        4  337895.00  1475260.00
        """
        res = parse_gpzu_file(multi_zone_doc.encode("utf-8"), "gpzu_multi_zones.txt")
        self.assertTrue(res["success"])
        # Проверяем, что координаты НЕ свалились в кучу (7 + 4 + 4 != 15)
        # Основной контур ЗУ должен содержать ровно 7 точек!
        self.assertEqual(res["points_count"], 7)
        self.assertIn("zones", res)
        self.assertEqual(len(res["zones"]), 3)

        # Зона 1: Границы ЗУ
        z1 = res["zones"][0]
        self.assertEqual(z1["type"], "boundary")
        self.assertEqual(z1["points_count"], 7)
        self.assertGreater(z1["area_sqm"], 30000)

        # Зона 2: Пятно застройки
        z2 = res["zones"][1]
        self.assertEqual(z2["type"], "buildable_envelope")
        self.assertEqual(z2["points_count"], 4)

        # Зона 3: Охранная зона водопровода
        z3 = res["zones"][2]
        self.assertEqual(z3["type"], "zouit_exclusion")
        self.assertEqual(z3["points_count"], 4)

        # Проверяем, что ЗОУИТ автоматически связался с координатами
        self.assertGreaterEqual(len(res["zouit"]), 1)
        z_water = next((z for z in res["zouit"] if "водопровод" in z["name"].lower()), None)
        self.assertIsNotNone(z_water)
        self.assertTrue(z_water["has_coordinates"])
        self.assertEqual(len(z_water["coordinates"]), 4)

    def test_gpzu_excel_multi_sheet_zones(self):
        import openpyxl
        import io
        wb = openpyxl.Workbook()

        # Лист 1: Граница ЗУ
        ws1 = wb.active
        ws1.title = "Граница ЗУ"
        ws1.append(["№", "X", "Y"])
        for p in [
            (1, 337979.12, 1475315.11),
            (2, 338015.68, 1475301.40),
            (3, 337968.30, 1475176.38),
            (4, 337846.77, 1475364.75),
        ]:
            ws1.append(list(p))

        # Лист 2: Охранная зона ЛЭП
        ws2 = wb.create_sheet(title="Охранная зона ЛЭП")
        ws2.append(["№", "X", "Y"])
        for p in [
            (1, 337900.00, 1475250.00),
            (2, 337910.00, 1475260.00),
            (3, 337905.00, 1475270.00),
            (4, 337895.00, 1475260.00),
        ]:
            ws2.append(list(p))

        buf = io.BytesIO()
        wb.save(buf)

        res = parse_gpzu_file(buf.getvalue(), "zones.xlsx")
        self.assertTrue(res["success"])
        self.assertEqual(len(res["zones"]), 2)
        self.assertEqual(res["zones"][0]["type"], "boundary")
        self.assertEqual(res["zones"][0]["points_count"], 4)
        self.assertEqual(res["zones"][1]["type"], "zouit_exclusion")
        self.assertEqual(res["zones"][1]["points_count"], 4)

    def test_forming_parcel_parsing_with_new_points(self):
        doc = """
        СХЕМА РАСПОЛОЖЕНИЯ ЗЕМЕЛЬНОГО УЧАСТКА НА КАДАСТРОВОМ ПЛАНЕ ТЕРРИТОРИИ
        Каталог координат характерных точек границ образуемого земельного участка :ЗУ1:
        н1  -  -  337979.12  1475315.11
        н2  337950.00  1475300.00  338015.68  1475301.40
        н3  -  -  337968.30  1475176.38
        н4  -  -  337846.77  1475364.75
        """
        res = parse_gpzu_file(doc.encode("utf-8"), "shema_cpt_zu1.txt")
        self.assertTrue(res["success"])
        self.assertEqual(res["points_count"], 4)
        self.assertIn("н1", res["coordinates_text"])
        self.assertIn("н2", res["coordinates_text"])
        # Проверяем, что взяты именно образуемые координаты (338015.68), а не старые (337950.00)
        self.assertAlmostEqual(res["zones"][0]["coordinates"][1][0], 338015.68)
        self.assertAlmostEqual(res["zones"][0]["coordinates"][1][1], 1475301.40)

    def test_gpzu_multipage_pdf_and_noise_filtering(self):
        """Проверка парсинга многостраничного ГПЗУ с разрывом таблицы страниц и отсевом текстового шума."""
        # Имитируем реальную структуру Минстроевского ГПЗУ со сквозной нумерацией через разрыв страниц
        doc_text = """
        Градостроительный план земельного участка № РФ-18-3-26-0-00-2026-1243-0
        18:26:041136:753
        Площадь земельного участка 41111 м²

        Описание границ земельного участка (образуемого земельного участка):
        Обозначение (номер) характерной точки
        Перечень координат характерных точек в системе координат
        X Y
        1 386213.46 2226426.33
        2 386253.41 2226490.62
        3 386256.58 2226495.72
        4 386234.88 2226509.66
        5 386257.69 2226548.48
        6 386247.86 2226553.64

        Страница 1 из 17
        === PAGE 2 ===
        Страница 2 из 17

        7 386204.41 2226580.25
        8 386175.42 2226596.05
        9 386025.37 2226687.87
        10 386199.90 2226432.48

        2. Информация о градостроительном регламенте
        Решение Городской думы от 27 ноября 2007 года №344
        Предельная этажность: 10 эт.
        Предельная высота: 35 м

        6. Информация о границах зон с особыми условиями использования территорий:
        1 2 3 4
        Охранная зона водопровода и канализации - - -
        Охранная зона газопровода - - -
        Санитарно-защитная зона цеха:
        1 385937.09 2226858.70
        2 385929.24 2226876.96
        3 385926.40 2226892.04
        4 385920.98 2226888.89
        """
        res = parse_gpzu_file(doc_text.encode("utf-8"), "test_gpzu_doc.txt")
        self.assertTrue(res["success"])
        self.assertEqual(res["cadastral_number"], "18:26:041136:753")
        self.assertIn("МСК-18", res["coordinate_system"])
        # Контур участка должен содержать 10 точек, бесшовно соединенных через разрыв страниц
        self.assertEqual(res["points_count"], 10)
        # Проверяем, что числовые строки дат ("27 ноября 2007 года") и номеров колонок ("1 2 3 4") не создали ложных зон
        self.assertEqual(len(res["zones"]), 2)
        self.assertEqual(res["zones"][0]["type"], "boundary")
        self.assertEqual(res["zones"][1]["type"], "zouit_exclusion")
        self.assertEqual(res["zones"][1]["points_count"], 4)


if __name__ == "__main__":
    unittest.main()
