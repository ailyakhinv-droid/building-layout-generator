"""Unit tests for CAD parser (DXF/DWG) and site placement."""

import unittest
from pathlib import Path

import ezdxf
import yaml

from src.core.cad_parser import (
    inspect_cad_layers,
    parse_cad_site,
    DWGConversionError,
)
from src.core.buildable_area import compute_buildable_area
from src.core.placement import PlacementConfig, PlacementEngine
from src.core.tep_calculator import calculate_tep
from src.library.section_library import SectionLibrary

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestCADParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output_dir = PROJECT_ROOT / "output"
        cls.output_dir.mkdir(exist_ok=True)
        cls.config_path = PROJECT_ROOT / "config" / "defaults.yaml"
        with cls.config_path.open("r", encoding="utf-8") as f:
            cls.config = yaml.safe_load(f)
        cls.lib = SectionLibrary(PROJECT_ROOT / "config" / "sections")

    def test_cad_dxf_parsing_and_placement(self):
        test_dxf = self.output_dir / "test_boundary_msk.dxf"
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        doc.layers.add("ГРАНИЦА_УЧАСТКА", color=1)
        doc.layers.add("КРАСНЫЕ_ЛИНИИ", color=3)
        doc.layers.add("ТОПОСЪЕМКА_ТЕКСТ", color=7)

        base_x, base_y = 502300.0, 2198000.0
        pts = [
            (base_x + 0.0, base_y + 0.0),
            (base_x + 240.0, base_y + 0.0),
            (base_x + 240.0, base_y + 160.0),
            (base_x + 100.0, base_y + 160.0),
            (base_x + 0.0, base_y + 80.0),
        ]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "ГРАНИЦА_УЧАСТКА"})
        msp.add_line(
            (base_x + 0.0, base_y + 8.0),
            (base_x + 240.0, base_y + 8.0),
            dxfattribs={"layer": "КРАСНЫЕ_ЛИНИИ"},
        )
        doc.saveas(test_dxf)

        layers = inspect_cad_layers(test_dxf)
        self.assertTrue(any(l.is_candidate for l in layers))
        self.assertTrue(any(l.is_red_line_candidate for l in layers))

        site, meta = parse_cad_site(test_dxf, normalize_origin=True)
        self.assertGreater(site.area, 20000)
        self.assertEqual(site.base_offset, (base_x, base_y))
        self.assertEqual(len(site.red_lines), 1)

        buildable = compute_buildable_area(site, self.config)
        self.assertGreater(buildable.area, 0)

        engine = PlacementEngine(site, self.lib, self.config)
        bldgs = engine.generate(PlacementConfig(target_floors=17, typology="AUTO"))
        self.assertGreater(len(bldgs), 0)

        tep = calculate_tep(site, bldgs, self.config)
        self.assertGreater(tep.total_gfa, 0)
        self.assertGreater(tep.apartments_total, 0)

    def test_cad_line_polygonization(self):
        test_lines_dxf = self.output_dir / "test_lines_boundary.dxf"
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        doc.layers.add("МЕЖА_УЧАСТКА", color=2)

        segments = [
            ((0, 0), (200, 0)),
            ((200, 0), (200, 150)),
            ((200, 150), (0, 150)),
            ((0, 150), (0, 0)),
        ]
        for p1, p2 in segments:
            msp.add_line(p1, p2, dxfattribs={"layer": "МЕЖА_УЧАСТКА"})
        doc.saveas(test_lines_dxf)

        site_lines, meta = parse_cad_site(test_lines_dxf, boundary_layer="МЕЖА_УЧАСТКА")
        self.assertAlmostEqual(site_lines.area, 30000.0, delta=1.0)

    def test_dwg_without_oda_raises_error(self):
        mock_dwg = self.output_dir / "mock_sample.dwg"
        with open(mock_dwg, "wb") as f:
            f.write(b"AC1027_AUTOCAD_MOCK_DWG_CONTENT")

        with self.assertRaises(DWGConversionError):
            parse_cad_site(mock_dwg)


if __name__ == "__main__":
    unittest.main()
