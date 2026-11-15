"""Тесты независимой настройки толщины въездов УДС (4-лучевой перекресток),
математической привязки подложек ArcGIS на 2D CAD чертеже
и расчетной сетки тайлов OpenStreetMap.
"""

from __future__ import annotations

import math
import unittest
from shapely.geometry import Polygon
from src.core.road_slicer import RoadSlicer
from src.models.site import Site


def local_meters_to_wgs84(x: float, y: float, center_lat: float, center_lon: float) -> tuple[float, float]:
    """Аналог JS функции localMetersToWgs84 для верификации."""
    a = 6378137.0
    e2 = 0.00669437999014
    lat_rad = math.radians(center_lat)
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    den = 1.0 - e2 * sin_lat * sin_lat
    sqrt_den = math.sqrt(den)
    N = a / sqrt_den
    M = (a * (1.0 - e2)) / (den * sqrt_den)

    dlat = (y / M) * (180.0 / math.pi)
    dlon = (x / (N * cos_lat)) * (180.0 / math.pi)

    return (center_lon + dlon, center_lat + dlat)


def wgs84_to_local_meters(lon: float, lat: float, center_lat: float, center_lon: float) -> tuple[float, float]:
    """Аналог JS функции wgs84ToLocalMeters для обратного пересчета."""
    a = 6378137.0
    e2 = 0.00669437999014
    lat_rad = math.radians(center_lat)
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    den = 1.0 - e2 * sin_lat * sin_lat
    sqrt_den = math.sqrt(den)
    N = a / sqrt_den
    M = (a * (1.0 - e2)) / (den * sqrt_den)

    dlat_rad = math.radians(lat - center_lat)
    dlon_rad = math.radians(lon - center_lon)

    return (dlon_rad * N * cos_lat, dlat_rad * M)


def lon2tile(lon: float, zoom: int) -> int:
    return math.floor((lon + 180.0) / 360.0 * (2 ** zoom))


def lat2tile(lat: float, zoom: int) -> int:
    return math.floor(
        (1.0 - math.log(math.tan(math.radians(lat)) + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * (2 ** zoom)
    )


class TestUdsRaysAndBasemap(unittest.TestCase):
    def test_4ray_individual_widths_influence(self):
        """Проверка: изменение ширины любого из въездов (1, 2, 3 или 4) меняет геометрию УДС."""
        site_poly = Polygon([(0, 0), (200, 0), (200, 200), (0, 200)])
        buildable = site_poly.buffer(-6.0)
        hub = [100.0, 100.0]

        # Базовая конфигурация: все 4 въезда по 15м
        roads_base = [
            {'name': 'Ray 1', 'points': [[0, 100], hub], 'width': 15.0, 'setback': 4.0},
            {'name': 'Ray 2', 'points': [[200, 100], hub], 'width': 15.0, 'setback': 4.0},
            {'name': 'Ray 3', 'points': [[100, 0], hub], 'width': 15.0, 'setback': 4.0},
            {'name': 'Ray 4', 'points': [[100, 200], hub], 'width': 15.0, 'setback': 4.0},
        ]
        res_base = RoadSlicer.slice_buildable_area(buildable, site_poly, road_lines=roads_base, preset='custom')
        self.assertEqual(len(res_base.sub_blocks), 4)

        # Модификация Въезда 2: увеличиваем ширину с 15м до 25м
        roads_mod_2 = [
            {'name': 'Ray 1', 'points': [[0, 100], hub], 'width': 15.0, 'setback': 4.0},
            {'name': 'Ray 2', 'points': [[200, 100], hub], 'width': 25.0, 'setback': 4.0},
            {'name': 'Ray 3', 'points': [[100, 0], hub], 'width': 15.0, 'setback': 4.0},
            {'name': 'Ray 4', 'points': [[100, 200], hub], 'width': 15.0, 'setback': 4.0},
        ]
        res_mod_2 = RoadSlicer.slice_buildable_area(buildable, site_poly, road_lines=roads_mod_2, preset='custom')
        self.assertEqual(len(res_mod_2.sub_blocks), 4)
        self.assertGreater(res_mod_2.roads_area_sqm, res_base.roads_area_sqm)

        # Модификация Въезда 4: уменьшаем ширину с 15м до 8м
        roads_mod_4 = [
            {'name': 'Ray 1', 'points': [[0, 100], hub], 'width': 15.0, 'setback': 4.0},
            {'name': 'Ray 2', 'points': [[200, 100], hub], 'width': 15.0, 'setback': 4.0},
            {'name': 'Ray 3', 'points': [[100, 0], hub], 'width': 15.0, 'setback': 4.0},
            {'name': 'Ray 4', 'points': [[100, 200], hub], 'width': 8.0, 'setback': 4.0},
        ]
        res_mod_4 = RoadSlicer.slice_buildable_area(buildable, site_poly, road_lines=roads_mod_4, preset='custom')
        self.assertEqual(len(res_mod_4.sub_blocks), 4)
        self.assertLess(res_mod_4.roads_area_sqm, res_base.roads_area_sqm)

    def test_local_meters_to_wgs84_exact_match(self):
        """Проверка: математический алгоритм привязки подложки строго совпадает с WGS-84 полигоном."""
        center_lat, center_lon = 57.161069, 65.674079
        site = Site(boundary=Polygon([(0, 0), (220, 0), (220, 160), (0, 160)]), geo_center=(center_lat, center_lon))
        wgs_poly = site.to_wgs84_boundary()

        # Центр (0,0)
        p0 = local_meters_to_wgs84(0, 0, center_lat, center_lon)
        self.assertAlmostEqual(p0[0], center_lon, places=6)
        self.assertAlmostEqual(p0[1], center_lat, places=6)

        # Угол (220, 160)
        p_corner = local_meters_to_wgs84(220, 160, center_lat, center_lon)
        wgs_bounds = wgs_poly.bounds  # (minx, miny, maxx, maxy) -> (min_lon, min_lat, max_lon, max_lat)
        self.assertAlmostEqual(p_corner[0], wgs_bounds[2], places=6)
        self.assertAlmostEqual(p_corner[1], wgs_bounds[3], places=6)

        # Обратный пересчет (round-trip)
        p_rev = wgs84_to_local_meters(p_corner[0], p_corner[1], center_lat, center_lon)
        self.assertAlmostEqual(p_rev[0], 220.0, places=4)
        self.assertAlmostEqual(p_rev[1], 160.0, places=4)

    def test_osm_tile_grid_calculations(self):
        """Проверка: расчет тайловой сетки Slippy Map OpenStreetMap на зуме 17."""
        center_lat, center_lon = 57.161069, 65.674079
        tx = lon2tile(center_lon, 17)
        ty = lat2tile(center_lat, 17)
        self.assertEqual(tx, 89447)
        self.assertEqual(ty, 40047)


if __name__ == '__main__':
    unittest.main()
