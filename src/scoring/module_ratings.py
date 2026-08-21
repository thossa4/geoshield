"""Per-module concern ratings — Phase 5, Step 5.1 of the blueprint.

Phase 5 is titled "Create the GeoShield Scoring System," but its own 5
steps are explicit about what that does NOT mean:

  - Step 5.1: "Version 1 should show separate Flood Context, Wind
    Resilience, Heat/Surface, and Drainage Context ratings." Four
    per-module ratings, not one score.
  - Step 5.5: "Avoid a single overall score until users prove they need
    one." No blending across modules happens anywhere in this file.
  - Step 5.4: "A high concern / low confidence result is different from
    high concern / high confidence... Missing data should reduce
    confidence — not automatically reduce the risk score." Every rating
    below returns concern_level and confidence as two separate fields.

Step 5.2 calls for "transparent percentile or threshold-based
transforms." Every threshold used here is the SAME threshold already
verified and used in src/recommendations/rules_engine.py's escalation
rules — not a new number invented for this file — so a module's rating
and its corresponding recommendation are always consistent with each
other. Each rating function's docstring cross-references the matching
rule_id; if a threshold changes, check both files.

Step 5.3 ("weight with evidence and sensitivity testing... compare
scores with known historical cases... publish a methodology summary")
is DELIBERATELY NOT fully implemented here, and this is not an
oversight: sensitivity analysis and historical-case validation require
real observed loss/damage data this prototype does not have. Doing that
with invented weights would be exactly the "false precision" Step 5.5
warns against. See docs/methodology_scoring.md for what this file does
and does not claim, published per Step 5.3's last checklist item.

Never computes, stores, or exposes a single overall score. Never lets a
concern_level of "Low concern" mean "safe" — Flood Context and Drainage
Context in particular are capped at "Moderate concern" even with no
nearby hazard signal, because absence of a mapped feature/zone is not
evidence of safety (the same caution already baked into
FLOOD_ZONE_X_CONTEXT and DRAINAGE_NO_MAPPED_FEATURE_NEARBY).
"""

from __future__ import annotations

MODULE_RATINGS_VERSION = "module_ratings_v0.1"

CONCERN_LEVELS = ("Insufficient data", "Low concern", "Moderate concern", "Elevated concern", "High concern")
CONFIDENCE_LEVELS = ("N/A", "Low", "Medium", "High")


def _rating(concern_level: str, confidence: str, evidence: str) -> dict:
    assert concern_level in CONCERN_LEVELS
    assert confidence in CONFIDENCE_LEVELS
    return {"concern_level": concern_level, "confidence": confidence, "evidence": evidence}


def rate_flood_context(record: dict) -> dict:
    """Mirrors rules_engine.py's FLOOD_SFHA / FLOOD_FLOODWAY /
    TERRAIN_LOW_RELATIVE_ELEVATION_IN_SFHA / FLOOD_ZONE_X_CONTEXT
    thresholds. Never returns "Low concern" — Zone X context is capped at
    "Moderate concern" per FLOOD_ZONE_X_CONTEXT's own "maps don't capture
    everything" caution.
    """
    if record.get("flood_data_available") is not True:
        return _rating("Insufficient data", "N/A", "flood_data_available is False")

    sfha = record.get("special_flood_hazard_area")
    floodway = record.get("floodway_flag")
    percentile = record.get("elevation_percentile_rank")
    confidence = "High" if percentile is not None else "Medium"

    if floodway is True or (sfha is True and percentile is not None and percentile <= 25):
        return _rating("High concern", confidence,
                        f"floodway={floodway}, SFHA={sfha}, elevation_percentile={percentile}")
    if sfha is True:
        return _rating("Elevated concern", confidence, f"SFHA={sfha}, zone={record.get('fema_zone')}")
    return _rating("Moderate concern", confidence,
                    f"zone={record.get('fema_zone')} (no SFHA/floodway, but map coverage is not total)")


def rate_wind_resilience(record: dict) -> dict:
    """Mirrors rules_engine.py's elevated_regional_wind_risk /
    WIND_NO_FORTIFIED_DOC thresholds.
    """
    hurricane = record.get("hurricane_risk_rating")
    strong_wind = record.get("strong_wind_risk_rating")
    if hurricane is None and strong_wind is None:
        return _rating("Insufficient data", "N/A", "no FEMA NRI regional rating available")

    fortified = (record.get("building_attributes") or {}).get("fortified_status", "unknown")
    confidence = "High" if fortified != "unknown" else "Medium"

    if fortified == "yes":
        return _rating("Low concern", confidence, "FORTIFIED documentation on file")

    elevated = hurricane in ("Relatively High", "Very High") or strong_wind in ("Relatively High", "Very High")
    if hurricane == "Very High":
        return _rating("High concern", confidence, f"hurricane_risk_rating={hurricane}, fortified={fortified}")
    if elevated:
        return _rating("Elevated concern", confidence,
                        f"hurricane_risk_rating={hurricane}, strong_wind_risk_rating={strong_wind}, fortified={fortified}")
    return _rating("Moderate concern", confidence,
                    f"hurricane_risk_rating={hurricane}, strong_wind_risk_rating={strong_wind}, fortified={fortified}")


def rate_heat_surface(record: dict) -> dict:
    """Mirrors rules_engine.py's LANDCOVER_HIGH_IMPERVIOUS /
    LANDCOVER_LOW_CANOPY_HEAT / CLIMATE_HIGH_HEAT_EXPOSURE thresholds.
    """
    impervious = record.get("impervious_pct_buffer_250m")
    if impervious is None:
        impervious = record.get("impervious_pct_pixel")
    canopy = record.get("tree_canopy_pct_buffer_250m")
    if canopy is None:
        canopy = record.get("tree_canopy_pct_pixel")
    hottest_temp = record.get("hottest_month_max_temp_f")

    landcover_available = impervious is not None or canopy is not None
    climate_available = hottest_temp is not None
    if not landcover_available and not climate_available:
        return _rating("Insufficient data", "N/A", "no landcover or climate data available")
    confidence = "High" if (landcover_available and climate_available) else "Medium"

    high_impervious = impervious is not None and impervious >= 80
    low_canopy_high_impervious = canopy is not None and impervious is not None and canopy < 10 and impervious >= 50
    high_heat = hottest_temp is not None and hottest_temp >= 90
    evidence = f"impervious={impervious}, canopy={canopy}, hottest_month_max_temp_f={hottest_temp}"

    if high_impervious and canopy is not None and canopy < 10 and high_heat:
        return _rating("High concern", confidence, evidence)
    if low_canopy_high_impervious or (high_heat and impervious is not None and impervious >= 50):
        return _rating("Elevated concern", confidence, evidence)
    if high_impervious or high_heat or (canopy is not None and canopy < 10):
        return _rating("Moderate concern", confidence, evidence)
    return _rating("Low concern", confidence, evidence)


def rate_drainage_context(record: dict) -> dict:
    """Mirrors rules_engine.py's DRAINAGE_NEAR_MAPPED_WATER /
    DRAINAGE_LOW_ELEVATION_NEAR_WATER / DRAINAGE_NEAR_LEVEE /
    EBR_NEAR_STORMWATER_INFRASTRUCTURE thresholds. Never returns "Low
    concern" — same "absence isn't evidence of good drainage" caution as
    DRAINAGE_NO_MAPPED_FEATURE_NEARBY.
    """
    if record.get("drainage_data_available") is not True:
        return _rating("Insufficient data", "N/A", "drainage_data_available is False")

    # run_one_address.py flattens NHD's per-category distances but not its
    # combined "overall" figure (that only exists inside
    # _full_drainage_response); recompute it here from the same 3 fields
    # rules_engine.py's drainage rules already read, rather than reaching
    # into the nested _full_* response other rating functions don't use.
    nhd_distances = (record.get("nearest_stream_or_river_m"), record.get("nearest_canal_or_ditch_m"),
                      record.get("nearest_waterbody_m"))
    nearest_water = min((d for d in nhd_distances if d is not None), default=None)
    nearest_levee = record.get("nearest_levee_m")
    percentile = record.get("elevation_percentile_rank")
    ebr_available = record.get("ebr_drainage_data_available") is True
    ebr_asset = record.get("nearest_stormwater_pipe_m"), record.get("nearest_stormwater_structure_m")
    ebr_nearest = min((d for d in ebr_asset if d is not None), default=None)
    confidence = "High" if ebr_available else "Medium"
    evidence = (f"nearest_water_or_drainage={nearest_water}m, nearest_levee={nearest_levee}m, "
                f"elevation_percentile={percentile}, ebr_nearest_stormwater={ebr_nearest}m")

    near_water = nearest_water is not None and nearest_water <= 100
    near_levee = nearest_levee is not None and nearest_levee <= 300
    near_ebr = ebr_nearest is not None and ebr_nearest <= 50

    if near_water and percentile is not None and percentile <= 25:
        return _rating("High concern", confidence, evidence)
    if near_water or near_levee or near_ebr:
        return _rating("Elevated concern", confidence, evidence)
    return _rating("Moderate concern", confidence, evidence)


def rate_all_modules(record: dict) -> dict:
    """Return all 4 Step 5.1 module ratings, keyed by module name. Never
    combines them into a single score — see module docstring."""
    return {
        "flood_context": rate_flood_context(record),
        "wind_resilience": rate_wind_resilience(record),
        "heat_surface": rate_heat_surface(record),
        "drainage_context": rate_drainage_context(record),
    }
