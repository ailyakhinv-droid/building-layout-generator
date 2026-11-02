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
    run_pipeline,
)


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


if __name__ == "__main__":
    unittest.main()
