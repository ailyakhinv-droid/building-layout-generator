import unittest
import numpy as np
from shapely.geometry import Polygon

from src.models.site import Site
from src.library.section_library import SectionLibrary
from src.core.placement import (
    PlacementEngine,
    PlacementConfig,
    MIN_MERIDIAN_INSOLATION_ANGLE_DEG
)
from src.core.insolation import (
    InsolationCalculator,
    InsolationReport,
    FacadeFacet
)
from dashboard_prototype.generator_service import get_config


class TestMeridianAndSurroundingsHeatmap(unittest.TestCase):
    def setUp(self):
        # 160x100m rectangle parcel
        self.boundary = Polygon([(0, 0), (160, 0), (160, 100), (0, 100)])
        self.site = Site(boundary=self.boundary)
        self.site.buildable_area = self.boundary.buffer(-6.0)
        self.library = SectionLibrary()
        self.config = get_config()

    def test_no_meridian_sections_on_horizontal_orientation(self):
        """Verify that M-sections are never placed horizontally (facing North-South)."""
        engine = PlacementEngine(self.site, self.library, self.config)
        all_sec_ids = [s.id for s in self.library.get_all()]
        
        # Test standard placement typologies: U_SHAPE, PERIMETER, LINEAR, AUTO
        for typ in ["U_SHAPE", "PERIMETER", "LINEAR", "AUTO"]:
            p_cfg = PlacementConfig(
                target_floors=9,
                typology=typ,
                preferred_section_ids=all_sec_ids
            )
            buildings = engine.generate(p_cfg)
            self.assertTrue(len(buildings) > 0, f"Expected buildings generated for typology {typ}")
            
            for b_idx, b in enumerate(buildings):
                for s_idx, s in enumerate(b.sections):
                    angle_deg = abs(s.angle) % 180.0
                    ang_to_horiz = min(angle_deg, 180.0 - angle_deg)
                    if ang_to_horiz < MIN_MERIDIAN_INSOLATION_ANGLE_DEG:
                        is_meridian = getattr(s.section_type, 'is_meridian', False) or s.section_type.id.startswith('mid_m') or s.section_type.id.startswith('M') or s.section_type.id.startswith('М')
                        self.assertFalse(
                            is_meridian,
                            f"Typology {typ}, Bldg {b_idx}, Sec {s_idx} ({s.section_type.id}): Meridian section placed at angle {s.angle:.1f}° "
                            f"(ang_to_horiz={ang_to_horiz:.1f}° < {MIN_MERIDIAN_INSOLATION_ANGLE_DEG}°), which faces North-South!"
                        )

    def test_surroundings_facets_generation_and_export(self):
        """Verify surrounding buildings get 3D facade facets with insolation data."""
        from src.models.building import Building, PlacedSection
        from src.models.section import SectionType

        mock_section = SectionType(
            id="Ш1",
            name="Широтная",
            category="MIDDLE",
            width=28.0,
            depth=14.0,
            default_floors=9,
            min_floors=4,
            max_floors=16,
            floor_area=392.0,
        )
        
        # Surrounding building 15m away to the north
        surr_poly = Polygon([(30, 60), (70, 60), (70, 80), (30, 80)])
        surr_feat = {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [list(surr_poly.exterior.coords)]},
            "properties": {
                "id": "osm_test_surr_1",
                "name": "Соседний дом 1",
                "building_type": "apartments",
                "levels": 5,
                "height": 15.0,
            }
        }
        
        calc = InsolationCalculator(
            site_lat=56.85,
            site_lon=53.20,
            required_hours=2.0,
            surrounding_buildings=[surr_feat],
        )
        
        # New building directly south of surrounding building
        sec = PlacedSection(mock_section, x=50.0, y=40.0, angle=0.0, floors=12)
        b = Building(sections=[sec], typology="LINEAR")
        
        report = calc.calculate_masterplan_insolation([b], include_surroundings=True)
        self.assertIsNotNone(report.surrounding_impact)
        impact = report.surrounding_impact
        self.assertIn("buildings", impact)
        self.assertEqual(len(impact["buildings"]), 1)
        self.assertIn("delta_hours", impact["buildings"][0])
        self.assertIn("sanpin_status", impact["buildings"][0])
        
        # Check surrounding facets list
        surr_facets = report.surrounding_facets
        self.assertTrue(len(surr_facets) > 0, "Expected facade facets generated for surrounding buildings")
        
        f0 = surr_facets[0]
        self.assertTrue(f0.is_surrounding)
        self.assertEqual(f0.surrounding_id, "osm_test_surr_1")
        self.assertIsNotNone(f0.baseline_hours)
        self.assertIsNotNone(f0.color_hex)
        
        # Test serialization into GeoJSON
        geojson = report.to_geojson_facets(center_lat=56.85, center_lon=53.20, include_surroundings=True)
        self.assertEqual(geojson["type"], "FeatureCollection")
        self.assertTrue(len(geojson["features"]) > 0)
        
        # Find feature with is_surrounding = True
        surr_features = [f for f in geojson["features"] if f["properties"].get("is_surrounding")]
        self.assertTrue(len(surr_features) > 0)
        self.assertEqual(surr_features[0]["properties"]["surrounding_id"], "osm_test_surr_1")
        self.assertIn("delta_hours", surr_features[0]["properties"])
        self.assertIn("baseline_hours", surr_features[0]["properties"])


if __name__ == '__main__':
    unittest.main()
