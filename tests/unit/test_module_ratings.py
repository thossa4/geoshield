"""Fast, deterministic unit tests for src/scoring/module_ratings.py.

No network calls — every rating function is a pure function of a
synthetic indicator dict. Complements the live regression suite (which
proves real addresses produce sensible ratings) by directly exercising
every branch, including edge cases a handful of real addresses won't
happen to hit (e.g. SFHA true but the elevation percentile missing).

Run with:
    python -m unittest tests.unit.test_module_ratings -v
(from the geoshield/ directory)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from scoring.module_ratings import (  # noqa: E402
    CONCERN_LEVELS,
    CONFIDENCE_LEVELS,
    rate_all_modules,
    rate_drainage_context,
    rate_flood_context,
    rate_heat_surface,
    rate_wind_resilience,
)


class FloodContextRatingTests(unittest.TestCase):
    def test_no_data_is_insufficient_data(self):
        r = rate_flood_context({"flood_data_available": False})
        self.assertEqual(r["concern_level"], "Insufficient data")
        self.assertEqual(r["confidence"], "N/A")

    def test_floodway_is_high_concern(self):
        r = rate_flood_context({"flood_data_available": True, "floodway_flag": True,
                                 "special_flood_hazard_area": False})
        self.assertEqual(r["concern_level"], "High concern")

    def test_sfha_with_low_percentile_is_high_concern(self):
        r = rate_flood_context({"flood_data_available": True, "special_flood_hazard_area": True,
                                 "floodway_flag": False, "elevation_percentile_rank": 10})
        self.assertEqual(r["concern_level"], "High concern")

    def test_sfha_with_high_percentile_is_elevated_not_high(self):
        r = rate_flood_context({"flood_data_available": True, "special_flood_hazard_area": True,
                                 "floodway_flag": False, "elevation_percentile_rank": 60})
        self.assertEqual(r["concern_level"], "Elevated concern")

    def test_sfha_with_missing_percentile_is_elevated_not_high(self):
        r = rate_flood_context({"flood_data_available": True, "special_flood_hazard_area": True,
                                 "floodway_flag": False})
        self.assertEqual(r["concern_level"], "Elevated concern")

    def test_no_sfha_is_moderate_never_low(self):
        r = rate_flood_context({"flood_data_available": True, "special_flood_hazard_area": False,
                                 "floodway_flag": False})
        self.assertEqual(r["concern_level"], "Moderate concern")

    def test_confidence_high_with_percentile_medium_without(self):
        with_pct = rate_flood_context({"flood_data_available": True, "special_flood_hazard_area": False,
                                        "floodway_flag": False, "elevation_percentile_rank": 50})
        without_pct = rate_flood_context({"flood_data_available": True, "special_flood_hazard_area": False,
                                           "floodway_flag": False})
        self.assertEqual(with_pct["confidence"], "High")
        self.assertEqual(without_pct["confidence"], "Medium")


class WindResilienceRatingTests(unittest.TestCase):
    def test_no_regional_rating_is_insufficient_data(self):
        r = rate_wind_resilience({})
        self.assertEqual(r["concern_level"], "Insufficient data")

    def test_fortified_yes_is_low_concern_regardless_of_regional_risk(self):
        r = rate_wind_resilience({
            "hurricane_risk_rating": "Very High",
            "building_attributes": {"fortified_status": "yes"},
        })
        self.assertEqual(r["concern_level"], "Low concern")

    def test_very_high_hurricane_no_fortified_is_high_concern(self):
        r = rate_wind_resilience({"hurricane_risk_rating": "Very High"})
        self.assertEqual(r["concern_level"], "High concern")

    def test_relatively_high_hurricane_no_fortified_is_elevated(self):
        r = rate_wind_resilience({"hurricane_risk_rating": "Relatively High"})
        self.assertEqual(r["concern_level"], "Elevated concern")

    def test_relatively_high_strong_wind_alone_is_elevated(self):
        r = rate_wind_resilience({"hurricane_risk_rating": "Relatively Low",
                                   "strong_wind_risk_rating": "Relatively High"})
        self.assertEqual(r["concern_level"], "Elevated concern")

    def test_low_regional_risk_no_fortified_is_moderate(self):
        r = rate_wind_resilience({"hurricane_risk_rating": "Relatively Low",
                                   "strong_wind_risk_rating": "Relatively Low"})
        self.assertEqual(r["concern_level"], "Moderate concern")

    def test_confidence_depends_on_fortified_status_being_known(self):
        known = rate_wind_resilience({"hurricane_risk_rating": "Relatively Low",
                                       "building_attributes": {"fortified_status": "no"}})
        unknown = rate_wind_resilience({"hurricane_risk_rating": "Relatively Low"})
        self.assertEqual(known["confidence"], "High")
        self.assertEqual(unknown["confidence"], "Medium")


class HeatSurfaceRatingTests(unittest.TestCase):
    def test_no_data_is_insufficient_data(self):
        r = rate_heat_surface({})
        self.assertEqual(r["concern_level"], "Insufficient data")

    def test_all_three_signals_is_high_concern(self):
        r = rate_heat_surface({
            "impervious_pct_buffer_250m": 85, "tree_canopy_pct_buffer_250m": 5,
            "hottest_month_max_temp_f": 95,
        })
        self.assertEqual(r["concern_level"], "High concern")

    def test_low_canopy_high_impervious_pair_is_elevated(self):
        r = rate_heat_surface({"impervious_pct_buffer_250m": 60, "tree_canopy_pct_buffer_250m": 5,
                                "hottest_month_max_temp_f": 70})
        self.assertEqual(r["concern_level"], "Elevated concern")

    def test_single_signal_is_moderate(self):
        r = rate_heat_surface({"impervious_pct_buffer_250m": 85, "tree_canopy_pct_buffer_250m": 40,
                                "hottest_month_max_temp_f": 70})
        self.assertEqual(r["concern_level"], "Moderate concern")

    def test_no_signals_is_low_concern(self):
        r = rate_heat_surface({"impervious_pct_buffer_250m": 20, "tree_canopy_pct_buffer_250m": 40,
                                "hottest_month_max_temp_f": 70})
        self.assertEqual(r["concern_level"], "Low concern")

    def test_pixel_values_used_as_fallback_when_buffer_missing(self):
        r = rate_heat_surface({"impervious_pct_pixel": 85, "tree_canopy_pct_pixel": 5,
                                "hottest_month_max_temp_f": 95})
        self.assertEqual(r["concern_level"], "High concern")

    def test_confidence_high_only_with_both_landcover_and_climate(self):
        both = rate_heat_surface({"impervious_pct_pixel": 20, "hottest_month_max_temp_f": 70})
        one_only = rate_heat_surface({"impervious_pct_pixel": 20})
        self.assertEqual(both["confidence"], "High")
        self.assertEqual(one_only["confidence"], "Medium")


class DrainageContextRatingTests(unittest.TestCase):
    def test_no_data_is_insufficient_data(self):
        r = rate_drainage_context({"drainage_data_available": False})
        self.assertEqual(r["concern_level"], "Insufficient data")

    def test_near_water_and_low_elevation_is_high_concern(self):
        r = rate_drainage_context({
            "drainage_data_available": True, "nearest_stream_or_river_m": 50,
            "elevation_percentile_rank": 10,
        })
        self.assertEqual(r["concern_level"], "High concern")

    def test_near_water_alone_is_elevated_not_high(self):
        r = rate_drainage_context({
            "drainage_data_available": True, "nearest_stream_or_river_m": 50,
            "elevation_percentile_rank": 80,
        })
        self.assertEqual(r["concern_level"], "Elevated concern")

    def test_near_levee_alone_is_elevated(self):
        r = rate_drainage_context({"drainage_data_available": True, "nearest_levee_m": 100})
        self.assertEqual(r["concern_level"], "Elevated concern")

    def test_near_ebr_stormwater_alone_is_elevated(self):
        r = rate_drainage_context({"drainage_data_available": True,
                                    "ebr_drainage_data_available": True,
                                    "nearest_stormwater_pipe_m": 20})
        self.assertEqual(r["concern_level"], "Elevated concern")

    def test_nothing_nearby_is_moderate_never_low(self):
        r = rate_drainage_context({
            "drainage_data_available": True, "nearest_stream_or_river_m": 5000,
            "nearest_levee_m": 5000,
        })
        self.assertEqual(r["concern_level"], "Moderate concern")

    def test_overall_water_distance_is_min_across_categories(self):
        # Regression guard: the "overall" distance must be recomputed
        # from the flat per-category fields, not read from a field that
        # doesn't exist at the top level of the record (a real bug found
        # live this session — see module_ratings.py's comment on this).
        r = rate_drainage_context({
            "drainage_data_available": True,
            "nearest_stream_or_river_m": 5000,
            "nearest_canal_or_ditch_m": 40,
            "nearest_waterbody_m": 3000,
            "elevation_percentile_rank": 90,
        })
        self.assertEqual(r["concern_level"], "Elevated concern")
        self.assertIn("nearest_water_or_drainage=40", r["evidence"])

    def test_confidence_high_only_when_ebr_local_data_also_available(self):
        national_only = rate_drainage_context({"drainage_data_available": True,
                                                 "nearest_stream_or_river_m": 5000})
        with_ebr = rate_drainage_context({"drainage_data_available": True,
                                           "nearest_stream_or_river_m": 5000,
                                           "ebr_drainage_data_available": True})
        self.assertEqual(national_only["confidence"], "Medium")
        self.assertEqual(with_ebr["confidence"], "High")


class RateAllModulesTests(unittest.TestCase):
    def test_returns_all_four_modules(self):
        result = rate_all_modules({})
        self.assertEqual(set(result.keys()), {"flood_context", "wind_resilience", "heat_surface", "drainage_context"})

    def test_never_produces_a_single_overall_score(self):
        # Deliberate guard for the blueprint's Step 5.5 rule, which this
        # module's own docstring commits to: no combined/overall key of
        # any kind should ever appear anywhere in the result.
        result = rate_all_modules({"flood_data_available": True, "special_flood_hazard_area": True,
                                    "floodway_flag": True})
        self.assertNotIn("overall", result)
        self.assertNotIn("score", result)
        for rating in result.values():
            self.assertNotIn("score", rating)

    def test_every_rating_uses_only_documented_levels(self):
        result = rate_all_modules({"flood_data_available": True, "special_flood_hazard_area": True,
                                    "floodway_flag": True, "hurricane_risk_rating": "Very High"})
        for rating in result.values():
            self.assertIn(rating["concern_level"], CONCERN_LEVELS)
            self.assertIn(rating["confidence"], CONFIDENCE_LEVELS)


if __name__ == "__main__":
    unittest.main()
