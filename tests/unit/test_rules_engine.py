"""Fast, deterministic unit tests for src/recommendations/rules_engine.py.

No network calls — generate_recommendations() is a pure function of an
indicators dict and optional building_attributes dict. Complements the
live regression suite (which proves the 3 reference addresses produce
the right rules) by directly exercising rule conditions a handful of
real addresses won't happen to combine — e.g. FLOOD_FLOODWAY specifically
(none of the 3 reference addresses are in a mapped floodway), or the
"no data" branches for every module at once.

Run with:
    python -m unittest tests.unit.test_rules_engine -v
(from the geoshield/ directory)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from recommendations.rules_engine import RULESET_VERSION, generate_recommendations  # noqa: E402


def _rule_ids(recs):
    return {r["rule_id"] for r in recs}


class FloodRuleTests(unittest.TestCase):
    def test_no_data_triggers_flood_no_data_only(self):
        recs = generate_recommendations({"flood_data_available": False})
        self.assertIn("FLOOD_NO_DATA", _rule_ids(recs))
        self.assertNotIn("FLOOD_ZONE_X_CONTEXT", _rule_ids(recs))

    def test_floodway_takes_priority_over_sfha(self):
        recs = generate_recommendations({
            "flood_data_available": True, "floodway_flag": True,
            "special_flood_hazard_area": True, "fema_zone": "AE",
        })
        ids = _rule_ids(recs)
        self.assertIn("FLOOD_FLOODWAY", ids)
        self.assertNotIn("FLOOD_SFHA", ids)

    def test_sfha_without_floodway(self):
        recs = generate_recommendations({
            "flood_data_available": True, "floodway_flag": False,
            "special_flood_hazard_area": True, "fema_zone": "AE",
        })
        self.assertIn("FLOOD_SFHA", _rule_ids(recs))

    def test_zone_x_context_when_no_sfha(self):
        recs = generate_recommendations({
            "flood_data_available": True, "floodway_flag": False,
            "special_flood_hazard_area": False, "fema_zone": "X",
        })
        self.assertIn("FLOOD_ZONE_X_CONTEXT", _rule_ids(recs))


class TerrainRuleTests(unittest.TestCase):
    def test_no_terrain_data_triggers_terrain_no_data(self):
        recs = generate_recommendations({"terrain_data_available": False})
        self.assertIn("TERRAIN_NO_DATA", _rule_ids(recs))

    def test_percentile_alone_gives_neighborhood_context_only(self):
        recs = generate_recommendations({
            "terrain_data_available": True, "elevation_percentile_rank": 60,
            "elevation_relative_position": "about average", "ground_elevation_m": 10,
        })
        ids = _rule_ids(recs)
        self.assertIn("TERRAIN_NEIGHBORHOOD_CONTEXT", ids)
        self.assertNotIn("TERRAIN_LOW_RELATIVE_ELEVATION_IN_SFHA", ids)

    def test_low_percentile_in_sfha_escalates(self):
        recs = generate_recommendations({
            "terrain_data_available": True, "elevation_percentile_rank": 10,
            "elevation_relative_position": "notably lower", "ground_elevation_m": -2,
            "special_flood_hazard_area": True,
        })
        self.assertIn("TERRAIN_LOW_RELATIVE_ELEVATION_IN_SFHA", _rule_ids(recs))

    def test_low_percentile_without_sfha_does_not_escalate(self):
        recs = generate_recommendations({
            "terrain_data_available": True, "elevation_percentile_rank": 10,
            "elevation_relative_position": "notably lower", "ground_elevation_m": 10,
            "special_flood_hazard_area": False,
        })
        self.assertNotIn("TERRAIN_LOW_RELATIVE_ELEVATION_IN_SFHA", _rule_ids(recs))


class LandcoverClimateRuleTests(unittest.TestCase):
    def test_high_impervious_alone(self):
        recs = generate_recommendations({"impervious_pct_buffer_250m": 85})
        self.assertIn("LANDCOVER_HIGH_IMPERVIOUS", _rule_ids(recs))

    def test_low_canopy_high_impervious_pair(self):
        recs = generate_recommendations({"impervious_pct_buffer_250m": 60, "tree_canopy_pct_buffer_250m": 5})
        self.assertIn("LANDCOVER_LOW_CANOPY_HEAT", _rule_ids(recs))

    def test_high_heat_triggers_climate_rule(self):
        recs = generate_recommendations({"hottest_month_max_temp_f": 95, "hottest_month": "August"})
        self.assertIn("CLIMATE_HIGH_HEAT_EXPOSURE", _rule_ids(recs))


class WindRuleTests(unittest.TestCase):
    def test_regional_context_fires_when_ratings_present(self):
        recs = generate_recommendations({"hurricane_risk_rating": "Relatively Low", "strong_wind_risk_rating": "Relatively Low"})
        self.assertIn("WIND_REGIONAL_HAZARD_CONTEXT", _rule_ids(recs))

    def test_roof_age_unknown_when_not_supplied(self):
        recs = generate_recommendations({}, building_attributes={})
        self.assertIn("WIND_ROOF_AGE_UNKNOWN", _rule_ids(recs))

    def test_roof_age_known_suppresses_that_rule(self):
        recs = generate_recommendations({}, building_attributes={"roof_age": 5})
        self.assertNotIn("WIND_ROOF_AGE_UNKNOWN", _rule_ids(recs))

    def test_fortified_yes_suppresses_no_fortified_doc_rule(self):
        recs = generate_recommendations({}, building_attributes={"fortified_status": "yes"})
        self.assertNotIn("WIND_NO_FORTIFIED_DOC", _rule_ids(recs))
        self.assertNotIn("WIND_LA_PROGRAM_CHECK", _rule_ids(recs))

    def test_no_fortified_doc_priority_escalates_with_elevated_regional_risk(self):
        recs = generate_recommendations(
            {"hurricane_risk_rating": "Very High"}, building_attributes={"fortified_status": "unknown"},
        )
        rule = next(r for r in recs if r["rule_id"] == "WIND_NO_FORTIFIED_DOC")
        self.assertEqual(rule["priority"], "Now")

    def test_no_fortified_doc_priority_lower_without_elevated_regional_risk(self):
        recs = generate_recommendations(
            {"hurricane_risk_rating": "Relatively Low"}, building_attributes={"fortified_status": "unknown"},
        )
        rule = next(r for r in recs if r["rule_id"] == "WIND_NO_FORTIFIED_DOC")
        self.assertEqual(rule["priority"], "Within 12 months")

    def test_shutters_unknown_fires_by_default(self):
        recs = generate_recommendations({}, building_attributes={})
        self.assertIn("WIND_SHUTTERS_UNKNOWN", _rule_ids(recs))

    def test_shutters_known_suppresses_that_rule(self):
        recs = generate_recommendations({}, building_attributes={"shutters_status": "yes"})
        self.assertNotIn("WIND_SHUTTERS_UNKNOWN", _rule_ids(recs))


class DrainageRuleTests(unittest.TestCase):
    def test_no_data_triggers_drainage_no_data(self):
        recs = generate_recommendations({"drainage_data_available": False})
        self.assertIn("DRAINAGE_NO_DATA", _rule_ids(recs))

    def test_nothing_nearby_triggers_no_mapped_feature_nearby(self):
        recs = generate_recommendations({"drainage_data_available": True})
        self.assertIn("DRAINAGE_NO_MAPPED_FEATURE_NEARBY", _rule_ids(recs))

    def test_near_mapped_water_fires(self):
        recs = generate_recommendations({
            "drainage_data_available": True, "nearest_stream_or_river_m": 50,
        })
        self.assertIn("DRAINAGE_NEAR_MAPPED_WATER", _rule_ids(recs))

    def test_near_water_and_low_elevation_also_escalates(self):
        recs = generate_recommendations({
            "drainage_data_available": True, "nearest_stream_or_river_m": 50,
            "elevation_percentile_rank": 10, "elevation_relative_position": "notably lower",
        })
        ids = _rule_ids(recs)
        self.assertIn("DRAINAGE_NEAR_MAPPED_WATER", ids)
        self.assertIn("DRAINAGE_LOW_ELEVATION_NEAR_WATER", ids)

    def test_near_levee_fires_independently_of_water_distance(self):
        recs = generate_recommendations({"drainage_data_available": True, "nearest_levee_m": 100})
        self.assertIn("DRAINAGE_NEAR_LEVEE", _rule_ids(recs))

    def test_ebr_stormwater_infrastructure_fires_when_close(self):
        recs = generate_recommendations({
            "ebr_drainage_data_available": True, "nearest_stormwater_pipe_m": 10,
        })
        self.assertIn("EBR_NEAR_STORMWATER_INFRASTRUCTURE", _rule_ids(recs))

    def test_ebr_rule_does_not_fire_outside_service_area(self):
        recs = generate_recommendations({"ebr_drainage_data_available": False})
        self.assertNotIn("EBR_NEAR_STORMWATER_INFRASTRUCTURE", _rule_ids(recs))


class RulesetVersioningTests(unittest.TestCase):
    def test_every_rule_stamps_current_ruleset_version(self):
        recs = generate_recommendations({
            "flood_data_available": True, "special_flood_hazard_area": True, "floodway_flag": True,
        }, building_attributes={})
        self.assertTrue(recs)
        for rule in recs:
            self.assertEqual(rule["ruleset_version"], RULESET_VERSION)

    def test_empty_indicators_does_not_crash(self):
        # No indicators, no building_attributes at all — every "no data"
        # branch should degrade gracefully rather than raising.
        recs = generate_recommendations({})
        self.assertIsInstance(recs, list)


if __name__ == "__main__":
    unittest.main()
