"""Комплексный аудит и тест всех параметров, ползунков и ограничений Шага 3."""

import unittest
from pathlib import Path
from dashboard_prototype.generator_service import run_pipeline

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_base_payload():
    return {
        "site_mode": "cadastre",
        "custom_area": 35000,
        "boundary_setback": 6.0,
        "red_line_setback": 5.0,
        "target_floors": 14,
        "max_building_height_m": 50.0,
        "floor_height": 3.0,
        "cascade_floors": True,
        "asymmetric_wings": True,
        "car_free_courtyard": True,
        "only_ground_parking": False,
        "typology": "AUTO",
        "courtyard_orientation": "SOUTH",
        "max_far": 2.5,
        "max_bcr": 0.4,
        "road_preset": "none",
        "max_sections": 8,
        "stage": 2,
        "site_locked": True,
        "allow_parking_in_zouit": False,
        "allow_towers_in_mixed": True,
        "regional_norm_id": "russia_sp42",
        "insolation": {
            "enabled": False,  # Отключаем для ускорения тестов аудита
            "norm_hours": 2.0,
            "include_surroundings": False,
            "default_surrounding_height": 15.0,
            "grid_step_m": 3.0,
            "auto_cascade_reduction": True,
        },
        "respect_norms": True,
        "gen_mode": "fixed",
    }


class TestStep3ControlsAudit(unittest.TestCase):
    """Аудит параметров Шага 3."""

    def test_height_limit_strict_enforcement(self):
        """Проверка: Здания НЕ должны превышать max_building_height_m (50 м) даже для Башни Б1."""
        payload = get_base_payload()
        payload["typology"] = "TOWER"
        payload["max_building_height_m"] = 50.0
        payload["target_floors"] = 16

        res = run_pipeline(payload)
        self.assertNotIn("error", res, f"Pipeline returned error: {res.get('error')}")
        buildings = res.get("buildings", [])
        self.assertGreater(len(buildings), 0, "No buildings placed")

        max_h = max(b.get("height", 0) for b in buildings)
        print(f"\n[TEST HEIGHT] Typology=TOWER, target=16 fl, limit=50.0m -> max building height is {max_h}m")
        # Проверяем, превышает ли 50.0 м
        self.assertLessEqual(max_h, 50.0, f"VIOLATION: building height {max_h}m exceeds limit 50.0m!")

    def test_slider_floors_controls_actual_floors(self):
        """Проверка: Ползунок целевой этажности (target_floors) меняет этажность корпусов."""
        payload_8 = get_base_payload()
        payload_8["target_floors"] = 8
        payload_8["typology"] = "AUTO"
        res_8 = run_pipeline(payload_8)
        b_8 = res_8.get("buildings", [])
        max_f_8 = max(b.get("floors", 0) for b in b_8)

        payload_14 = get_base_payload()
        payload_14["target_floors"] = 14
        payload_14["typology"] = "AUTO"
        res_14 = run_pipeline(payload_14)
        b_14 = res_14.get("buildings", [])
        max_f_14 = max(b.get("floors", 0) for b in b_14)

        print(f"\n[TEST FLOORS] target=8 -> max floors: {max_f_8}, target=14 -> max floors: {max_f_14}")
        self.assertLessEqual(max_f_8, 9, "Target floors 8 produced excessively tall building")
        self.assertGreater(max_f_14, max_f_8, "Slider floors has no effect on building heights!")

    def test_slider_setback_controls_buildable_area(self):
        """Проверка: Ползунок отступа от границ ЗУ (boundary_setback) сужает зону застройки."""
        payload_close = get_base_payload()
        payload_close["boundary_setback"] = 3.0
        res_close = run_pipeline(payload_close)
        b_area_close = res_close.get("buildable_area_sqm", 0)

        payload_far = get_base_payload()
        payload_far["boundary_setback"] = 12.0
        res_far = run_pipeline(payload_far)
        b_area_far = res_far.get("buildable_area_sqm", 0)

        print(f"\n[TEST SETBACK] setback=3m -> area={b_area_close} m2, setback=12m -> area={b_area_far} m2")
        self.assertGreater(b_area_close, b_area_far, "Setback slider has no effect on buildable area!")

    def test_slider_max_sections_controls_building_length(self):
        """Проверка: Ползунок макс. секций в корпусе (max_sections) ограничивает длину."""
        payload_short = get_base_payload()
        payload_short["max_sections"] = 3
        payload_short["typology"] = "SECTIONAL"
        res_short = run_pipeline(payload_short)
        b_short = res_short.get("buildings", [])
        max_sec_short = max(len(b.get("sections", [])) for b in b_short) if b_short else 0

        payload_long = get_base_payload()
        payload_long["max_sections"] = 8
        payload_long["typology"] = "SECTIONAL"
        res_long = run_pipeline(payload_long)
        b_long = res_long.get("buildings", [])
        max_sec_long = max(len(b.get("sections", [])) for b in b_long) if b_long else 0

        print(f"\n[TEST MAX SECTIONS] max_sec=3 -> actual {max_sec_short}, max_sec=8 -> actual {max_sec_long}")
        self.assertLessEqual(max_sec_short, 3, f"Building exceeded max_sections=3 limit: {max_sec_short}")

    def test_typologies_generate_correct_archetypes(self):
        """Проверка: Кнопки типологий генерируют соответствующие типы зданий."""
        for typ in ("AUTO", "U_SHAPE", "TOWER", "SECTIONAL"):
            payload = get_base_payload()
            payload["typology"] = typ
            res = run_pipeline(payload)
            self.assertNotIn("error", res, f"Failed for typology {typ}: {res.get('error')}")
            b_list = res.get("buildings", [])
            self.assertGreater(len(b_list), 0, f"No buildings for typology {typ}")
            types_present = set(b.get("typology") for b in b_list)
            print(f"[TEST TYPOLOGY] {typ} produced building typologies: {types_present}")
            if typ == "TOWER":
                self.assertIn("TOWER", types_present)

    def test_only_ground_parking_flag(self):
        """Проверка: Флаг 'Все парковки на участке' обнуляет подземный паркинг."""
        payload = get_base_payload()
        payload["only_ground_parking"] = True
        res = run_pipeline(payload)
        tep = res.get("tep", {})
        parking = tep.get("parking", {})
        underground = parking.get("underground_spaces", 0)
        print(f"\n[TEST ONLY GROUND PARKING] underground_spaces = {underground}")
        self.assertEqual(underground, 0, "Underground spaces should be 0 when only_ground_parking=True")

    def test_section_catalog_overrides(self):
        """Проверка: Переопределения этажности секций через модалку (section_overrides)."""
        payload = get_base_payload()
        payload["typology"] = "TOWER"
        payload["section_overrides"] = {
            "tower_b1": {"min_floors": 10, "max_floors": 12}
        }
        res = run_pipeline(payload)
        buildings = res.get("buildings", [])
        b1_floors = [b.get("floors") for b in buildings if "tower" in b.get("typology", "").lower() or b.get("typology") == "TOWER"]
        print(f"\n[TEST SECTION OVERRIDES] tower_b1 clamped to 10..12 -> placed floors: {b1_floors}")
        for fl in b1_floors:
            self.assertLessEqual(fl, 12, f"Override max_floors=12 violated: {fl}")


if __name__ == "__main__":
    unittest.main()
