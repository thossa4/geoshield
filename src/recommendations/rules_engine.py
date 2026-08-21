"""Deterministic, versioned recommendation rules engine.

Implements Phase 6 of the GeoShield blueprint: turn atomic indicators
(and optional user-supplied building attributes) into a prioritized
action list — without inventing risk facts or silently modifying scores
(Step 6.2). No score/rating is computed anywhere in this module; Phase 5
scoring is explicitly out of scope for this prototype.

Action taxonomy (Step 6.1):
    Verify | Low-cost maintenance | Professional assessment |
    Capital improvement | Financial/program search | Emergency preparedness

Each recommendation carries (Step 6.3):
    priority       Now / Before purchase / Within 12 months / Monitor
    cost_band      No-cost / Low / Moderate / Major / Unknown until quote
    evidence       what finding triggered the action
    confidence     High / Medium / Low
    provider_type  Inspector / roofer / drainage contractor / arborist /
                   engineer / surveyor / other
    program_link   official program reference, if applicable, with a
                   last-checked date (never a fabricated eligibility claim)

RULESET_VERSION must be bumped whenever a rule's condition or output text
changes, per Phase 9.3 ("every score/recommendation stores rule/weight
version... never recompute an old report silently").
"""

from __future__ import annotations

RULESET_VERSION = "recommendations_v0.7"

# The Louisiana Fortify Homes program is the only state program wired in
# so far (Phase 24 source list). URL and status live-verified 2026-08-20
# (see docs/data_registry.csv, LA_FORTIFY_HOMES row) — re-verify before
# each release, since grant rounds and eligibility geography change per
# round (the round live at verification time was restricted to the
# Coastal Zone plus Lake Charles/Sulphur/Westlake, not statewide).
LA_FORTIFY_HOMES_PROGRAM_NOTE = (
    "Louisiana Fortify Homes Program — https://www.ldi.la.gov/fortifyhomes "
    "(verified live 2026-08-20). Verify current lottery/registration "
    "status and eligibility geography at that official page before "
    "relying on this reference — grant rounds, funding, and eligible "
    "areas change per round and are not statewide by default."
)


def _rule(rule_id, action_class, action, priority, cost_band, evidence, confidence, provider_type, program_link=None):
    return {
        "rule_id": rule_id,
        "action_class": action_class,
        "action": action,
        "priority": priority,
        "cost_band": cost_band,
        "evidence": evidence,
        "confidence": confidence,
        "provider_type": provider_type,
        "program_link": program_link,
        "ruleset_version": RULESET_VERSION,
    }


def generate_recommendations(indicators: dict, building_attributes: dict | None = None) -> list[dict]:
    """Return a list of recommendation dicts for one property.

    ``indicators`` is the record shape produced by
    ``src/run_one_address.py`` (flood/terrain/land-cover fields).
    ``building_attributes`` is optional, user-supplied, always treated as
    unverified: ``{"roof_age": int|None, "fortified_status":
    "yes"|"no"|"unknown", "shutters_status": "yes"|"no"|"unknown"}``.
    """
    building_attributes = building_attributes or {}
    recs: list[dict] = []

    # --- Flood context rules (Phase 4.1.1 no-data rule + Step 6.2 style) ---
    if indicators.get("flood_data_available") is False:
        recs.append(_rule(
            "FLOOD_NO_DATA",
            "Verify",
            "GeoShield found no effective digital FEMA flood-hazard data "
            "at this location. Check the FEMA Flood Map Service Center "
            "directly rather than assuming low risk.",
            "Before purchase", "No-cost",
            "No NFHL flood-zone feature intersected this point.",
            "High", "Surveyor",
        ))
    elif indicators.get("floodway_flag") is True:
        recs.append(_rule(
            "FLOOD_FLOODWAY",
            "Verify",
            "This property intersects a mapped regulatory floodway. "
            "Consult a floodplain administrator or engineer before any "
            "construction, fill, or improvement — floodway rules are "
            "typically stricter than the surrounding flood zone.",
            "Now", "Unknown until quote",
            f"FEMA NFHL zone subtype: {indicators.get('flood_zone_subtype')}",
            "High", "Engineer",
        ))
    elif indicators.get("special_flood_hazard_area") is True:
        recs.append(_rule(
            "FLOOD_SFHA",
            "Verify",
            "Property is within a FEMA Special Flood Hazard Area "
            f"(zone {indicators.get('fema_zone')}). Obtain an elevation "
            "certificate documenting finished-floor elevation relative "
            "to the Base Flood Elevation before relying on map zone "
            "alone.",
            "Before purchase", "Low",
            f"FEMA NFHL zone: {indicators.get('fema_zone')}",
            "High", "Surveyor",
        ))
    elif indicators.get("flood_data_available") is True:
        recs.append(_rule(
            "FLOOD_ZONE_X_CONTEXT",
            "Verify",
            "No mapped Special Flood Hazard Area at this point (zone "
            f"{indicators.get('fema_zone')}), but FEMA maps do not "
            "capture every flood source. Monitor local drainage "
            "conditions and consider flood insurance regardless of zone.",
            "Monitor", "No-cost",
            f"FEMA NFHL zone: {indicators.get('fema_zone')}, "
            f"SFHA: {indicators.get('special_flood_hazard_area')}",
            "Medium", "Other",
        ))

    # --- Terrain rules ---
    percentile = indicators.get("elevation_percentile_rank")
    relative_position = indicators.get("elevation_relative_position")

    if indicators.get("terrain_data_available") is False:
        recs.append(_rule(
            "TERRAIN_NO_DATA",
            "Verify",
            "GeoShield could not retrieve elevation data for this point. "
            "A licensed surveyor can establish ground and finished-floor "
            "elevation directly.",
            "Before purchase", "Low",
            "USGS 3DEP EPQS returned no usable value.",
            "High", "Surveyor",
        ))
    elif percentile is not None:
        recs.append(_rule(
            "TERRAIN_NEIGHBORHOOD_CONTEXT",
            "Verify",
            "Ground elevation of "
            f"~{indicators.get('ground_elevation_m')}m was sampled at "
            f"this point, which is {relative_position} within a "
            "250m-radius sample. This is not a surveyed finished-floor "
            "elevation; request a surveyed elevation certificate before "
            "relying on it for a flood-risk decision.",
            "Monitor", "No-cost",
            f"USGS 3DEP point elevation: {indicators.get('ground_elevation_m')}m, "
            f"neighborhood percentile: {percentile}",
            "Medium", "Surveyor",
        ))
        if percentile <= 25 and indicators.get("special_flood_hazard_area"):
            recs.append(_rule(
                "TERRAIN_LOW_RELATIVE_ELEVATION_IN_SFHA",
                "Professional assessment",
                "This property is both in a FEMA Special Flood Hazard "
                f"Area and {relative_position} (elevation percentile "
                f"{percentile} of sampled nearby points). Prioritize "
                "obtaining a surveyed elevation certificate and consult a "
                "flood-mitigation professional before finalizing any "
                "purchase or major improvement decision.",
                "Now", "Low",
                f"SFHA: True, elevation percentile: {percentile} ({relative_position})",
                "Medium", "Surveyor",
            ))
    elif indicators.get("terrain_data_available") is True:
        recs.append(_rule(
            "TERRAIN_RAW_ONLY",
            "Verify",
            "Ground elevation of "
            f"~{indicators.get('ground_elevation_m')}m was sampled at "
            "this point, but a neighborhood comparison could not be "
            "computed. Do not treat this figure alone as a flood-risk "
            "indicator; request a surveyed elevation certificate for "
            "finished-floor elevation.",
            "Monitor", "No-cost",
            f"USGS 3DEP point elevation: {indicators.get('ground_elevation_m')}m",
            "Medium", "Surveyor",
        ))

    # --- Land-cover / drainage-proxy rules (Phase 4.3, Phase 4.4 caution) ---
    # Prefer the 250m grid-sampled buffer mean (less noise-sensitive than
    # a single pixel) when available; fall back to the single-pixel value.
    impervious_buffer = indicators.get("impervious_pct_buffer_250m")
    canopy_buffer = indicators.get("tree_canopy_pct_buffer_250m")
    impervious = impervious_buffer if impervious_buffer is not None else indicators.get("impervious_pct_pixel")
    canopy = canopy_buffer if canopy_buffer is not None else indicators.get("tree_canopy_pct_pixel")
    landcover_evidence_label = "250m buffer mean" if impervious_buffer is not None else "single pixel"

    if impervious is not None and impervious >= 80:
        recs.append(_rule(
            "LANDCOVER_HIGH_IMPERVIOUS",
            "Professional assessment",
            f"High impervious-surface coverage (~{impervious}% "
            f"{landcover_evidence_label}) can increase stormwater runoff "
            "and localized ponding. A drainage professional can review "
            "grading, gutters, and downspout management for this "
            "property.",
            "Within 12 months", "Low",
            f"NLCD 2021 impervious ({landcover_evidence_label}): {impervious}%",
            "Medium", "Drainage contractor",
        ))

    if canopy is not None and impervious is not None and canopy < 10 and impervious >= 50:
        recs.append(_rule(
            "LANDCOVER_LOW_CANOPY_HEAT",
            "Low-cost maintenance",
            f"Low tree canopy (~{canopy}% {landcover_evidence_label}) "
            f"combined with high impervious cover (~{impervious}% "
            f"{landcover_evidence_label}) suggests elevated local heat "
            "exposure. Consider shade tree planting, and ask about "
            "cool-roof or attic-insulation options during any roof "
            "work.",
            "Within 12 months", "Low",
            f"NLCD 2021 ({landcover_evidence_label}) tree canopy: {canopy}%, impervious: {impervious}%",
            "Medium", "Arborist",
        ))

    # --- Climate/heat rules (Step 4.3.2: HVAC efficiency review action) ---
    hottest_month_temp = indicators.get("hottest_month_max_temp_f")
    hottest_month = indicators.get("hottest_month")
    cooling_degree_days = indicators.get("annual_cooling_degree_days")

    if hottest_month_temp is not None and hottest_month_temp >= 90:
        recs.append(_rule(
            "CLIMATE_HIGH_HEAT_EXPOSURE",
            "Professional assessment",
            f"This area's typical hottest month ({hottest_month}) has a "
            f"1991-2020 average high of {hottest_month_temp}°F, based "
            "on the nearest NOAA weather station. Consider an HVAC "
            "efficiency review and attic/insulation air-sealing "
            "assessment given sustained summer heat exposure.",
            "Within 12 months", "Low",
            f"NOAA NCEI normals: hottest_month={hottest_month}, "
            f"hottest_month_max_temp_f={hottest_month_temp}, "
            f"annual_cooling_degree_days={cooling_degree_days}",
            "Medium", "Other",
        ))

    # --- Wind/roof rules ---
    # Regional context (Phase 4.2.1: "Regional wind/hurricane context can
    # come from authoritative hazard/climate sources. Building
    # vulnerability cannot be inferred accurately from a map alone.") is
    # kept strictly separate from the user-attribute-driven building
    # rules below — it can raise urgency, but never substitutes for or
    # infers a building attribute.
    hurricane_rating = indicators.get("hurricane_risk_rating")
    strong_wind_rating = indicators.get("strong_wind_risk_rating")
    elevated_regional_wind_risk = hurricane_rating in ("Relatively High", "Very High") or \
        strong_wind_rating in ("Relatively High", "Very High")

    if hurricane_rating is not None or strong_wind_rating is not None:
        recs.append(_rule(
            "WIND_REGIONAL_HAZARD_CONTEXT",
            "Verify",
            f"This area's FEMA National Risk Index rates hurricane risk "
            f"as \"{hurricane_rating}\" and strong-wind risk as "
            f"\"{strong_wind_rating}\" (census-tract level, not "
            "property-specific). This describes the surrounding area, "
            "not this building's actual condition.",
            "Monitor", "No-cost",
            f"FEMA NRI hurricane_risk_rating={hurricane_rating}, strong_wind_risk_rating={strong_wind_rating}",
            "Medium", "Other",
        ))

    roof_age = building_attributes.get("roof_age")
    fortified_status = building_attributes.get("fortified_status", "unknown")
    shutters_status = building_attributes.get("shutters_status", "unknown")

    if roof_age is None:
        recs.append(_rule(
            "WIND_ROOF_AGE_UNKNOWN",
            "Verify",
            "Verify roof age/documentation before relying on any "
            "wind-resilience assumptions.",
            "Before purchase", "No-cost",
            "roof_age not supplied or unknown.",
            "High", "Roofer",
        ))

    if fortified_status != "yes":
        if elevated_regional_wind_risk:
            fortified_priority = "Now"
            fortified_action = (
                "No FORTIFIED roof documentation on file, and this area's "
                f"FEMA National Risk Index rates hurricane risk as "
                f"\"{hurricane_rating}\". Prioritize investigating whether "
                "a FORTIFIED evaluation or upgrade is appropriate for "
                "this home."
            )
        else:
            fortified_priority = "Within 12 months"
            fortified_action = (
                "No FORTIFIED roof documentation on file. Investigate "
                "whether a FORTIFIED evaluation or upgrade is appropriate "
                "for this home."
            )
        recs.append(_rule(
            "WIND_NO_FORTIFIED_DOC",
            "Professional assessment",
            fortified_action,
            fortified_priority, "Unknown until quote",
            f"fortified_status = {fortified_status}, hurricane_risk_rating = {hurricane_rating}",
            "Medium", "Roofer",
            program_link=LA_FORTIFY_HOMES_PROGRAM_NOTE,
        ))
        recs.append(_rule(
            "WIND_LA_PROGRAM_CHECK",
            "Financial/program search",
            "A Louisiana state roof-mitigation program may be worth "
            "checking; review current official eligibility requirements "
            "before assuming qualification.",
            "Within 12 months", "No-cost",
            "Property is in the Louisiana pilot market with no "
            "confirmed FORTIFIED documentation on file.",
            "Medium", "Other",
            program_link=LA_FORTIFY_HOMES_PROGRAM_NOTE,
        ))

    # --- Drainage rules (Phase 4.1/4.4: proximity to mapped water/drainage
    # features only — no flow-accumulation or depression modeling, per the
    # blueprint's Phase 4.4 validation gate) ---
    if indicators.get("drainage_data_available") is False:
        recs.append(_rule(
            "DRAINAGE_NO_DATA",
            "Verify",
            "GeoShield could not retrieve mapped water/drainage-feature "
            "data for this point. Ask about local drainage history "
            "directly — nearby ditches, canals, or low spots — rather "
            "than assuming none exist.",
            "Before purchase", "No-cost",
            "USGS NHD query did not return usable data.",
            "Medium", "Drainage contractor",
        ))
    elif indicators.get("drainage_data_available") is True:
        nearest_distances = [
            d for d in (
                indicators.get("nearest_stream_or_river_m"),
                indicators.get("nearest_canal_or_ditch_m"),
                indicators.get("nearest_waterbody_m"),
                indicators.get("nearest_levee_m"),
            ) if d is not None
        ]
        nearest_overall = min(nearest_distances) if nearest_distances else None
        levee_distance = indicators.get("nearest_levee_m")

        if nearest_overall is None:
            recs.append(_rule(
                "DRAINAGE_NO_MAPPED_FEATURE_NEARBY",
                "Verify",
                "No mapped stream, canal/ditch, waterbody, or levee was "
                "found within GeoShield's search radius of this property. "
                "This does not rule out local ditches or drainage ponding "
                "— many small drainage features are not captured in "
                "national hydrography data.",
                "Monitor", "No-cost",
                "USGS NHD: no mapped water/drainage feature within search radius.",
                "Low", "Other",
            ))
        elif nearest_overall <= 100:
            recs.append(_rule(
                "DRAINAGE_NEAR_MAPPED_WATER",
                "Low-cost maintenance",
                "A mapped stream, canal/ditch, or waterbody is close to "
                f"this property (~{nearest_overall}m). Check grading, "
                "gutters, and downspout management, and ask a drainage "
                "professional about local drainage capacity during heavy "
                "rainfall.",
                "Within 12 months", "Low",
                f"nearest mapped water/drainage feature: {nearest_overall}m",
                "Medium", "Drainage contractor",
            ))
            percentile = indicators.get("elevation_percentile_rank")
            if percentile is not None and percentile <= 25:
                recs.append(_rule(
                    "DRAINAGE_LOW_ELEVATION_NEAR_WATER",
                    "Professional assessment",
                    "This property is both close to a mapped water/drainage "
                    f"feature (~{nearest_overall}m) and "
                    f"{indicators.get('elevation_relative_position')} "
                    f"(elevation percentile {percentile}) within its own "
                    "sampled neighborhood. A drainage professional should "
                    "review site grading and local drainage capacity before "
                    "finalizing any purchase or major improvement decision.",
                    "Now", "Low",
                    f"nearest mapped water/drainage feature: "
                    f"{nearest_overall}m, elevation percentile: {percentile}",
                    "Medium", "Drainage contractor",
                ))

        if levee_distance is not None and levee_distance <= 300:
            recs.append(_rule(
                "DRAINAGE_NEAR_LEVEE",
                "Verify",
                f"A mapped levee is nearby (~{levee_distance}m). "
                "Levee-protected areas can still experience "
                "interior/rainfall-driven flooding when local drainage or "
                "pump capacity is exceeded, independent of river or "
                "storm-surge levels. Ask about local drainage and pumping "
                "capacity for this area.",
                "Monitor", "No-cost",
                f"nearest levee: {levee_distance}m",
                "Medium", "Other",
            ))

    # --- East Baton Rouge Parish local stormwater infrastructure rule ---
    # Parish-scoped (ebr_local_drainage_indicators.py) — never fires
    # outside East Baton Rouge Parish, where in_service_area is False and
    # ebr_drainage_data_available is correspondingly False. Tighter
    # threshold (50m vs. the national-NHD rule's 100m) because municipal
    # storm infrastructure is expected to be near most urban EBR parcels;
    # 100m would fire on nearly every address and stop being a signal.
    if indicators.get("ebr_drainage_data_available") is True:
        nearest_pipe = indicators.get("nearest_stormwater_pipe_m")
        nearest_structure = indicators.get("nearest_stormwater_structure_m")
        nearest_local = min(
            (d for d in (nearest_pipe, nearest_structure) if d is not None),
            default=None,
        )
        if nearest_local is not None and nearest_local <= 50:
            recs.append(_rule(
                "EBR_NEAR_STORMWATER_INFRASTRUCTURE",
                "Low-cost maintenance",
                "East Baton Rouge Parish's own GIS shows municipal "
                f"stormwater infrastructure close to this property "
                f"(~{nearest_local}m — a drainage pipe/ditch and/or catch "
                "basin). Keep the area around it clear of debris and "
                "landscaping that could block flow, and mention it to a "
                "drainage contractor if you notice standing water nearby.",
                "Within 12 months", "No-cost",
                f"nearest EBR stormwater pipe: {nearest_pipe}m, "
                f"nearest structure: {nearest_structure}m",
                "Medium", "Drainage contractor",
            ))

    if shutters_status == "unknown":
        recs.append(_rule(
            "WIND_SHUTTERS_UNKNOWN",
            "Verify",
            "Ask an appropriate professional about opening protection "
            "(shutters/impact-rated windows) for this property.",
            "Within 12 months", "Unknown until quote",
            "shutters_status not supplied or unknown.",
            "Medium", "Roofer",
        ))

    return recs
