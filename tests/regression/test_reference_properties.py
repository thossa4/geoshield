"""Regression tests: run the real, live pipeline against known reference
addresses and check results stay within expected bounds.

These tests make real network calls to FEMA, USGS, and the Census
geocoder (no mocking) — consistent with this project's rule of never
faking government data. That means they are slower (each address takes
roughly 10-15 seconds) and can fail if a source is briefly unavailable,
not just if the code regresses. A failure here means: check whether the
upstream API changed or was down before assuming the code broke.

Run with:
    python -m unittest tests.regression.test_reference_properties -v
(from the geoshield/ directory)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # for reference_properties package

from run_one_address import run_one_address  # noqa: E402
from reference_properties.properties import REFERENCE_PROPERTIES  # noqa: E402


def _in_range(value, bounds) -> bool:
    if value is None:
        return False
    low, high = bounds
    return low <= value <= high


class ReferencePropertyRegressionTests(unittest.TestCase):
    """One test method per reference property, generated dynamically so
    failures are reported per-address rather than as one giant test."""


def _make_test(prop: dict):
    def test(self):
        record = run_one_address(prop["address"])
        expected = prop["expected"]

        self.assertIsNotNone(record.get("longitude"), f"{prop['name']}: address failed to geocode")

        if "fema_zone" in expected:
            self.assertEqual(record.get("fema_zone"), expected["fema_zone"], f"{prop['name']}: fema_zone mismatch")
        if "special_flood_hazard_area" in expected:
            self.assertEqual(
                record.get("special_flood_hazard_area"), expected["special_flood_hazard_area"],
                f"{prop['name']}: special_flood_hazard_area mismatch",
            )
        if "floodway_flag" in expected:
            self.assertEqual(record.get("floodway_flag"), expected["floodway_flag"], f"{prop['name']}: floodway_flag mismatch")
        if "land_cover_class_code" in expected:
            self.assertEqual(
                record.get("land_cover_class_code"), expected["land_cover_class_code"],
                f"{prop['name']}: land_cover_class_code mismatch",
            )
        if "hurricane_risk_rating" in expected:
            self.assertEqual(
                record.get("hurricane_risk_rating"), expected["hurricane_risk_rating"],
                f"{prop['name']}: hurricane_risk_rating mismatch",
            )
        if "drainage_data_available" in expected:
            self.assertEqual(
                record.get("drainage_data_available"), expected["drainage_data_available"],
                f"{prop['name']}: drainage_data_available mismatch",
            )
        if "ebr_drainage_data_available" in expected:
            self.assertEqual(
                record.get("ebr_drainage_data_available"), expected["ebr_drainage_data_available"],
                f"{prop['name']}: ebr_drainage_data_available mismatch",
            )
        for concern_key in ("flood_context_concern_level", "wind_resilience_concern_level",
                            "heat_surface_concern_level", "drainage_context_concern_level"):
            if concern_key in expected:
                self.assertEqual(
                    record.get(concern_key), expected[concern_key],
                    f"{prop['name']}: {concern_key} mismatch",
                )
        if "parcel_data_available" in expected:
            self.assertEqual(
                record.get("parcel_data_available"), expected["parcel_data_available"],
                f"{prop['name']}: parcel_data_available mismatch",
            )
        if "parcel_match_quality" in expected:
            self.assertEqual(
                record.get("parcel_match_quality"), expected["parcel_match_quality"],
                f"{prop['name']}: parcel_match_quality mismatch",
            )

        for field_key, bounds_key in [
            ("ground_elevation_m", "ground_elevation_m_range"),
            ("elevation_percentile_rank", "elevation_percentile_rank_range"),
            ("impervious_pct_pixel", "impervious_pct_pixel_range"),
            ("impervious_pct_buffer_250m", "impervious_pct_buffer_250m_range"),
            ("nearest_stream_or_river_m", "nearest_stream_or_river_m_range"),
            ("nearest_canal_or_ditch_m", "nearest_canal_or_ditch_m_range"),
            ("nearest_waterbody_m", "nearest_waterbody_m_range"),
            ("nearest_levee_m", "nearest_levee_m_range"),
            ("nearest_stormwater_pipe_m", "nearest_stormwater_pipe_m_range"),
            ("nearest_stormwater_structure_m", "nearest_stormwater_structure_m_range"),
        ]:
            if bounds_key in expected:
                value = record.get(field_key)
                self.assertTrue(
                    _in_range(value, expected[bounds_key]),
                    f"{prop['name']}: {field_key}={value} not in expected range {expected[bounds_key]}",
                )

        recommendations = record.get("recommendations", [])
        rule_ids = {r["rule_id"] for r in recommendations}
        missing = prop.get("expected_rule_ids_present", set()) - rule_ids
        self.assertFalse(missing, f"{prop['name']}: expected rule(s) did not fire: {missing}")

        unexpected = prop.get("expected_rule_ids_absent", set()) & rule_ids
        self.assertFalse(unexpected, f"{prop['name']}: rule(s) fired that should not have: {unexpected}")

        rules_by_id = {r["rule_id"]: r for r in recommendations}
        for rule_id, expected_priority in prop.get("expected_rule_priorities", {}).items():
            self.assertIn(rule_id, rules_by_id, f"{prop['name']}: {rule_id} did not fire, cannot check its priority")
            self.assertEqual(
                rules_by_id[rule_id]["priority"], expected_priority,
                f"{prop['name']}: {rule_id} priority mismatch",
            )

    return test


for _prop in REFERENCE_PROPERTIES:
    setattr(ReferencePropertyRegressionTests, f"test_{_prop['name']}", _make_test(_prop))


if __name__ == "__main__":
    unittest.main()
