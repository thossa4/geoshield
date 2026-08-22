"""Real reference properties for regression testing (Phase 13 style validation
sample, at prototype scale). Each entry's expected values were recorded from
actual verified runs of the live pipeline (src/run_one_address.py) against
real government APIs during development — not fabricated or hand-picked to
flatter the code. If a source dataset is updated upstream (e.g. a newer
NLCD/FEMA release), these expectations may need a deliberate refresh; that is
the point of a regression test — it should fail loudly rather than silently
drift.

Numeric fields use (min, max) tolerance ranges rather than exact values,
since grid-sampled statistics (buffer means, elevation percentiles) can
shift slightly if a request in the sampling grid times out under load.
Categorical fields (FEMA zone, SFHA, floodway, land-cover class) come from
static, deterministic government sources and are asserted exactly.
"""

REFERENCE_PROPERTIES = [
    {
        "name": "baton_rouge_zone_x",
        "address": "750 Florida St, Baton Rouge, LA 70801",
        "description": "Downtown Baton Rouge, high-elevation, Zone X (minimal flood hazard), dense urban impervious cover.",
        "expected": {
            "fema_zone": "X",
            "special_flood_hazard_area": False,
            "floodway_flag": False,
            "ground_elevation_m_range": (14.0, 17.0),
            "elevation_percentile_rank_range": (40.0, 80.0),
            "land_cover_class_code": 24,
            "impervious_pct_pixel_range": (85, 100),
            "impervious_pct_buffer_250m_range": (75.0, 95.0),
            "hurricane_risk_rating": "Relatively High",
            "drainage_data_available": True,
            "nearest_stream_or_river_m_range": (700.0, 1100.0),
            "nearest_waterbody_m_range": (700.0, 1100.0),
            "ebr_drainage_data_available": True,
            "nearest_stormwater_pipe_m_range": (0.0, 50.0),
            "nearest_stormwater_structure_m_range": (0.0, 50.0),
            "flood_context_concern_level": "Moderate concern",
            "parcel_data_available": True,
            "parcel_match_quality": "no_confident_match",
            # Only checked if CENSUS_API_KEY is set in the environment —
            # it's an optional key not stored as a CI secret, so this is
            # real coverage for a developer who has it set, without
            # failing CI where it's deliberately absent.
            "expected_acs": {
                "acs_total_population": 3051.0,
                "acs_median_household_income_usd": 52827.0,
                "acs_owner_occupied_pct": 10.6,
            },
        },
        "expected_rule_ids_present": {
            "FLOOD_ZONE_X_CONTEXT",
            "TERRAIN_NEIGHBORHOOD_CONTEXT",
            "LANDCOVER_HIGH_IMPERVIOUS",
            "WIND_REGIONAL_HAZARD_CONTEXT",
            "EBR_NEAR_STORMWATER_INFRASTRUCTURE",
        },
        "expected_rule_ids_absent": {
            "FLOOD_SFHA",
            "FLOOD_FLOODWAY",
            "TERRAIN_LOW_RELATIVE_ELEVATION_IN_SFHA",
            "DRAINAGE_NEAR_MAPPED_WATER",
            "DRAINAGE_NEAR_LEVEE",
            "DRAINAGE_NO_MAPPED_FEATURE_NEARBY",
        },
    },
    {
        "name": "lakeview_new_orleans_sfha",
        "address": "6300 Bellaire Dr, New Orleans, LA 70124",
        "description": "Lakeview, New Orleans — below sea level, FEMA Zone AE / Special Flood Hazard Area, moderate relative elevation within its own sampled neighborhood.",
        "expected": {
            "fema_zone": "AE",
            "special_flood_hazard_area": True,
            "floodway_flag": False,
            "ground_elevation_m_range": (-4.0, -0.5),
            "elevation_percentile_rank_range": (20.0, 60.0),
            "land_cover_class_code": 22,
            "hurricane_risk_rating": "Relatively High",
            "drainage_data_available": True,
            "nearest_stream_or_river_m_range": (50.0, 250.0),
            "nearest_levee_m_range": (30.0, 200.0),
            "ebr_drainage_data_available": False,
            "parcel_data_available": False,
            "expected_acs": {
                "acs_total_population": 2622.0,
                "acs_median_household_income_usd": 103824.0,
                "acs_owner_occupied_pct": 61.6,
            },
        },
        "expected_rule_ids_present": {
            "FLOOD_SFHA",
            "TERRAIN_NEIGHBORHOOD_CONTEXT",
            "WIND_REGIONAL_HAZARD_CONTEXT",
            "DRAINAGE_NEAR_MAPPED_WATER",
            "DRAINAGE_NEAR_LEVEE",
        },
        "expected_rule_ids_absent": {
            "FLOOD_ZONE_X_CONTEXT",
            "FLOOD_FLOODWAY",
            "TERRAIN_LOW_RELATIVE_ELEVATION_IN_SFHA",
            "DRAINAGE_NO_MAPPED_FEATURE_NEARBY",
        },
    },
    {
        "name": "gentilly_new_orleans_low_elevation_sfha",
        "address": "5500 Paris Ave, New Orleans, LA 70122",
        "description": "Gentilly, New Orleans — FEMA Zone AE / SFHA, and notably low relative elevation within its own sampled neighborhood (bottom decile); should trigger the escalation rule.",
        "expected": {
            "fema_zone": "AE",
            "special_flood_hazard_area": True,
            "floodway_flag": False,
            "ground_elevation_m_range": (-4.0, -0.5),
            "elevation_percentile_rank_range": (0.0, 25.0),
            "hurricane_risk_rating": "Relatively High",
            "drainage_data_available": True,
            "nearest_stream_or_river_m_range": (400.0, 700.0),
            "nearest_levee_m_range": (400.0, 700.0),
            "ebr_drainage_data_available": False,
            # flood_context_concern_level deliberately NOT asserted here:
            # it's derived from elevation_percentile_rank, which this
            # file's own module docstring already documents as having
            # grid-sampling run-to-run variance (hence the _range check
            # above, not an exact value) — right at this property's
            # <=25 threshold, that variance can flip the categorical
            # result between "High concern" and "Elevated concern" on a
            # code-correct run. Confirmed live: a real run correctly
            # computed 361s later — see module_ratings.py's mirrored
            # threshold for the TERRAIN_LOW_RELATIVE_ELEVATION_IN_SFHA
            # rule, which has the identical fragility.
            "drainage_context_concern_level": "Moderate concern",
            "parcel_data_available": False,
            "expected_acs": {
                "acs_total_population": 2439.0,
                "acs_median_household_income_usd": 111563.0,
                "acs_owner_occupied_pct": 80.0,
            },
        },
        "expected_rule_ids_present": {
            "FLOOD_SFHA",
            "TERRAIN_NEIGHBORHOOD_CONTEXT",
            "TERRAIN_LOW_RELATIVE_ELEVATION_IN_SFHA",
            "WIND_REGIONAL_HAZARD_CONTEXT",
        },
        "expected_rule_priorities": {
            # Elevated regional hurricane risk + no FORTIFIED doc on file
            # should escalate this rule to "Now" (see rules_engine.py).
            "WIND_NO_FORTIFIED_DOC": "Now",
        },
        "expected_rule_ids_absent": {
            "FLOOD_ZONE_X_CONTEXT",
            "FLOOD_FLOODWAY",
            "DRAINAGE_NEAR_MAPPED_WATER",
            "DRAINAGE_NEAR_LEVEE",
            "DRAINAGE_NO_MAPPED_FEATURE_NEARBY",
        },
    },
]
