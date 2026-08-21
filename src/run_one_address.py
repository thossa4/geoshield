"""Phase C driver: run one address end-to-end and write atomic indicators.

This implements Phase C, "The First 10 Things to Do Tomorrow," steps 7-8
of the GeoShield blueprint:

    "Write every atomic indicator you can calculate for that address into
    a single table—do not score it yet."

It chains together the working prototype modules built so far:
  - src/geocoding/geocode_address.py  (Census Geocoder — Phase 3, Step 3.1)
  - src/indicators/flood_indicators.py (FEMA NFHL — Phase 4.1.1)
  - src/indicators/terrain_indicators.py (USGS 3DEP EPQS — Phase 4.1.2: point
    elevation plus a 250m grid-sampled neighborhood percentile)
  - src/indicators/landcover_indicators.py (MRLC/NLCD WMS — Phase 4.3, Step 4.3.1: both
    single-pixel and a 250m grid-sampled buffer approximation)
  - src/indicators/wind_indicators.py (FEMA National Risk Index — Phase 4.2.1
    regional hurricane/strong-wind hazard context, census-tract level)
  - src/indicators/climate_indicators.py (NOAA NCEI 1991-2020 normals — Phase
    4.3, Step 4.3.1 heat/climate context, nearest-weather-station level)
  - src/indicators/drainage_indicators.py (USGS NHD — Phase 4.1/4.4 distance
    to mapped stream/river, canal/ditch, waterbody, and levee; no
    flow-accumulation or drainage-performance modeling)
  - src/indicators/ebr_local_drainage_indicators.py (East Baton Rouge
    Parish's own GIS — nearest local stormwater pipe/structure and
    drainage district; parish-scoped, returns data_available: False,
    in_service_area: False outside East Baton Rouge Parish)
  - src/recommendations/rules_engine.py (Phase 6 deterministic rules)

Optional user-supplied building attributes (--roof-age, --fortified,
--shutters) feed the wind/roof rules in Phase 4.2.2's table. They are
always unverified unless a real verification workflow is added later.

Deliberately NOT implemented yet (do not fake these):
  - Any score or rating of any kind — scoring is Phase 5, out of scope
    here on purpose.

Usage:
    python run_one_address.py "750 Florida St, Baton Rouge, LA 70801"

Appends one row to data/processed/property_indicators.csv and prints the
full record as JSON.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import sys
import uuid
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC_DIR))

from geocoding.geocode_address import geocode  # noqa: E402
from indicators.flood_indicators import get_flood_indicators  # noqa: E402
from indicators.terrain_indicators import get_terrain_indicators, get_neighborhood_elevation_stats  # noqa: E402
from indicators.landcover_indicators import get_landcover_indicators, get_landcover_buffer_stats  # noqa: E402
from indicators.wind_indicators import get_wind_hazard_context  # noqa: E402
from indicators.climate_indicators import get_climate_context  # noqa: E402
from indicators.drainage_indicators import get_drainage_context  # noqa: E402
from indicators.ebr_local_drainage_indicators import get_ebr_local_drainage_context  # noqa: E402
from scoring.module_ratings import rate_all_modules, MODULE_RATINGS_VERSION  # noqa: E402
from recommendations.rules_engine import generate_recommendations  # noqa: E402
from reporting.report_generator import write_report  # noqa: E402

OUTPUT_CSV = SRC_DIR.parent / "data" / "processed" / "property_indicators.csv"
REPORTS_DIR = SRC_DIR.parent / "reports"
RECOMMENDATIONS_CSV = SRC_DIR.parent / "data" / "processed" / "recommendations.csv"

RECOMMENDATION_FIELDNAMES = [
    "property_id",
    "rule_id",
    "action_class",
    "action",
    "priority",
    "cost_band",
    "evidence",
    "confidence",
    "provider_type",
    "program_link",
    "ruleset_version",
]

FIELDNAMES = [
    "property_id",
    "analysis_date_utc",
    "input_address",
    "matched_address",
    "longitude",
    "latitude",
    "geocode_match_quality",
    "geocode_provider",
    "flood_data_available",
    "fema_zone",
    "flood_zone_subtype",
    "special_flood_hazard_area",
    "floodway_flag",
    "base_flood_elevation_ft",
    "flood_quality_flag",
    "terrain_data_available",
    "ground_elevation_m",
    "terrain_quality_flag",
    "elevation_percentile_rank",
    "elevation_relative_position",
    "terrain_neighborhood_quality_flag",
    "landcover_data_available",
    "land_cover_class_code",
    "land_cover_class_label",
    "impervious_pct_pixel",
    "tree_canopy_pct_pixel",
    "landcover_quality_flag",
    "impervious_pct_buffer_250m",
    "tree_canopy_pct_buffer_250m",
    "landcover_buffer_quality_flag",
    "hurricane_risk_score",
    "hurricane_risk_rating",
    "strong_wind_risk_score",
    "strong_wind_risk_rating",
    "wind_hazard_quality_flag",
    "annual_mean_max_temp_f",
    "hottest_month",
    "hottest_month_max_temp_f",
    "annual_cooling_degree_days",
    "climate_quality_flag",
    "drainage_data_available",
    "nearest_stream_or_river_m",
    "nearest_canal_or_ditch_m",
    "nearest_waterbody_m",
    "nearest_levee_m",
    "drainage_quality_flag",
    "ebr_drainage_data_available",
    "nearest_stormwater_pipe_m",
    "nearest_stormwater_structure_m",
    "drainage_district_name",
    "ebr_drainage_quality_flag",
    "flood_context_concern_level",
    "flood_context_confidence",
    "wind_resilience_concern_level",
    "wind_resilience_confidence",
    "heat_surface_concern_level",
    "heat_surface_confidence",
    "drainage_context_concern_level",
    "drainage_context_confidence",
    "module_ratings_version",
]


def run_one_address(address: str, building_attributes: dict | None = None) -> dict:
    property_id = f"GS-{uuid.uuid4().hex[:8].upper()}"
    analysis_date = datetime.datetime.now(datetime.timezone.utc).isoformat()

    geo = geocode(address)

    record = {
        "property_id": property_id,
        "analysis_date_utc": analysis_date,
        "input_address": geo["input_address"],
        "matched_address": geo["matched_address"],
        "longitude": geo["longitude"],
        "latitude": geo["latitude"],
        "geocode_match_quality": geo["match_quality"],
        "geocode_provider": geo["geocoder_provider"],
        "flood_data_available": None,
        "fema_zone": None,
        "flood_zone_subtype": None,
        "special_flood_hazard_area": None,
        "floodway_flag": None,
        "base_flood_elevation_ft": None,
        "flood_quality_flag": None,
        "terrain_data_available": None,
        "ground_elevation_m": None,
        "terrain_quality_flag": None,
        "elevation_percentile_rank": None,
        "elevation_relative_position": None,
        "terrain_neighborhood_quality_flag": None,
        "landcover_data_available": None,
        "land_cover_class_code": None,
        "land_cover_class_label": None,
        "impervious_pct_pixel": None,
        "tree_canopy_pct_pixel": None,
        "landcover_quality_flag": None,
        "impervious_pct_buffer_250m": None,
        "tree_canopy_pct_buffer_250m": None,
        "landcover_buffer_quality_flag": None,
        "hurricane_risk_score": None,
        "hurricane_risk_rating": None,
        "strong_wind_risk_score": None,
        "strong_wind_risk_rating": None,
        "wind_hazard_quality_flag": None,
        "annual_mean_max_temp_f": None,
        "hottest_month": None,
        "hottest_month_max_temp_f": None,
        "annual_cooling_degree_days": None,
        "climate_quality_flag": None,
        "drainage_data_available": None,
        "nearest_stream_or_river_m": None,
        "nearest_canal_or_ditch_m": None,
        "nearest_waterbody_m": None,
        "nearest_levee_m": None,
        "drainage_quality_flag": None,
        "ebr_drainage_data_available": None,
        "nearest_stormwater_pipe_m": None,
        "nearest_stormwater_structure_m": None,
        "drainage_district_name": None,
        "ebr_drainage_quality_flag": None,
        "flood_context_concern_level": None,
        "flood_context_confidence": None,
        "wind_resilience_concern_level": None,
        "wind_resilience_confidence": None,
        "heat_surface_concern_level": None,
        "heat_surface_confidence": None,
        "drainage_context_concern_level": None,
        "drainage_context_confidence": None,
        "module_ratings_version": None,
        "module_ratings": None,
        "_full_flood_response": None,
        "_full_terrain_response": None,
        "_full_terrain_neighborhood_response": None,
        "_full_landcover_response": None,
        "_full_landcover_buffer_response": None,
        "_full_wind_hazard_response": None,
        "_full_climate_response": None,
        "_full_drainage_response": None,
        "_full_ebr_drainage_response": None,
        "building_attributes": building_attributes or {},
        "recommendations": [],
    }

    if geo["longitude"] is None or geo["latitude"] is None:
        record["_note"] = (
            "Address did not geocode; no flood/terrain indicators were "
            "queried. A real product must ask the user to confirm/correct "
            "the address rather than stopping silently."
        )
        return record

    lon, lat = geo["longitude"], geo["latitude"]

    flood = get_flood_indicators(lon, lat)
    record["flood_data_available"] = flood.get("data_available")
    record["fema_zone"] = flood.get("fema_zone")
    record["flood_zone_subtype"] = flood.get("zone_subtype")
    record["special_flood_hazard_area"] = flood.get("special_flood_hazard_area")
    record["floodway_flag"] = flood.get("floodway_flag")
    record["base_flood_elevation_ft"] = flood.get("base_flood_elevation_ft")
    record["flood_quality_flag"] = flood.get("quality_flag")
    record["_full_flood_response"] = flood

    terrain = get_terrain_indicators(lon, lat)
    record["terrain_data_available"] = terrain.get("data_available")
    record["ground_elevation_m"] = terrain.get("ground_elevation_m")
    record["terrain_quality_flag"] = terrain.get("quality_flag")
    record["_full_terrain_response"] = terrain

    terrain_neighborhood = get_neighborhood_elevation_stats(lon, lat)
    record["elevation_percentile_rank"] = terrain_neighborhood.get("percentile_rank")
    record["elevation_relative_position"] = terrain_neighborhood.get("relative_position_label")
    record["terrain_neighborhood_quality_flag"] = terrain_neighborhood.get("quality_flag")
    record["_full_terrain_neighborhood_response"] = terrain_neighborhood

    landcover = get_landcover_indicators(lon, lat)
    record["landcover_data_available"] = landcover.get("data_available")
    record["land_cover_class_code"] = landcover.get("land_cover_class_code")
    record["land_cover_class_label"] = landcover.get("land_cover_class_label")
    record["impervious_pct_pixel"] = landcover.get("impervious_pct_pixel")
    record["tree_canopy_pct_pixel"] = landcover.get("tree_canopy_pct_pixel")
    record["landcover_quality_flag"] = landcover.get("quality_flag")
    record["_full_landcover_response"] = landcover

    landcover_buffer = get_landcover_buffer_stats(lon, lat)
    record["impervious_pct_buffer_250m"] = landcover_buffer.get("impervious_pct_buffer_mean")
    record["tree_canopy_pct_buffer_250m"] = landcover_buffer.get("tree_canopy_pct_buffer_mean")
    record["landcover_buffer_quality_flag"] = landcover_buffer.get("quality_flag")
    record["_full_landcover_buffer_response"] = landcover_buffer

    wind_hazard = get_wind_hazard_context(lon, lat)
    record["hurricane_risk_score"] = wind_hazard.get("hurricane_risk_score")
    record["hurricane_risk_rating"] = wind_hazard.get("hurricane_risk_rating")
    record["strong_wind_risk_score"] = wind_hazard.get("strong_wind_risk_score")
    record["strong_wind_risk_rating"] = wind_hazard.get("strong_wind_risk_rating")
    record["wind_hazard_quality_flag"] = wind_hazard.get("quality_flag")
    record["_full_wind_hazard_response"] = wind_hazard

    climate = get_climate_context(lon, lat)
    record["annual_mean_max_temp_f"] = climate.get("annual_mean_max_temp_f")
    record["hottest_month"] = climate.get("hottest_month")
    record["hottest_month_max_temp_f"] = climate.get("hottest_month_max_temp_f")
    record["annual_cooling_degree_days"] = climate.get("annual_cooling_degree_days")
    record["climate_quality_flag"] = climate.get("quality_flag")
    record["_full_climate_response"] = climate

    drainage = get_drainage_context(lon, lat)
    record["drainage_data_available"] = drainage.get("data_available")
    record["nearest_stream_or_river_m"] = drainage.get("nearest_stream_or_river_m")
    record["nearest_canal_or_ditch_m"] = drainage.get("nearest_canal_or_ditch_m")
    record["nearest_waterbody_m"] = drainage.get("nearest_waterbody_m")
    record["nearest_levee_m"] = drainage.get("nearest_levee_m")
    record["drainage_quality_flag"] = drainage.get("quality_flag")
    record["_full_drainage_response"] = drainage

    ebr_drainage = get_ebr_local_drainage_context(lon, lat)
    record["ebr_drainage_data_available"] = ebr_drainage.get("data_available")
    record["nearest_stormwater_pipe_m"] = ebr_drainage.get("nearest_stormwater_pipe_m")
    record["nearest_stormwater_structure_m"] = ebr_drainage.get("nearest_stormwater_structure_m")
    record["drainage_district_name"] = ebr_drainage.get("drainage_district_name")
    record["ebr_drainage_quality_flag"] = ebr_drainage.get("quality_flag")
    record["_full_ebr_drainage_response"] = ebr_drainage

    module_ratings = rate_all_modules(record)
    record["module_ratings"] = module_ratings
    record["flood_context_concern_level"] = module_ratings["flood_context"]["concern_level"]
    record["flood_context_confidence"] = module_ratings["flood_context"]["confidence"]
    record["wind_resilience_concern_level"] = module_ratings["wind_resilience"]["concern_level"]
    record["wind_resilience_confidence"] = module_ratings["wind_resilience"]["confidence"]
    record["heat_surface_concern_level"] = module_ratings["heat_surface"]["concern_level"]
    record["heat_surface_confidence"] = module_ratings["heat_surface"]["confidence"]
    record["drainage_context_concern_level"] = module_ratings["drainage_context"]["concern_level"]
    record["drainage_context_confidence"] = module_ratings["drainage_context"]["confidence"]
    record["module_ratings_version"] = MODULE_RATINGS_VERSION

    record["recommendations"] = generate_recommendations(record, building_attributes)

    return record


def append_to_csv(record: dict) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not OUTPUT_CSV.exists()
    row = {k: record.get(k) for k in FIELDNAMES}
    with OUTPUT_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def append_recommendations_to_csv(property_id: str, recommendations: list[dict]) -> None:
    if not recommendations:
        return
    RECOMMENDATIONS_CSV.parent.mkdir(parents=True, exist_ok=True)
    write_header = not RECOMMENDATIONS_CSV.exists()
    with RECOMMENDATIONS_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RECOMMENDATION_FIELDNAMES)
        if write_header:
            writer.writeheader()
        for rec in recommendations:
            row = {k: rec.get(k) for k in RECOMMENDATION_FIELDNAMES if k != "property_id"}
            row["property_id"] = property_id
            writer.writerow(row)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Geocode one address and gather real atomic indicators + recommendations."
    )
    parser.add_argument("address", help="Street address to process")
    parser.add_argument(
        "--roof-age", type=int, default=None,
        help="User-supplied roof age in years (unverified). Omit if unknown.",
    )
    parser.add_argument(
        "--fortified", choices=["yes", "no", "unknown"], default="unknown",
        help="User-supplied FORTIFIED roof documentation status (unverified).",
    )
    parser.add_argument(
        "--shutters", choices=["yes", "no", "unknown"], default="unknown",
        help="User-supplied opening-protection/shutters status (unverified).",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Also render the fixed 10-section Home Passport HTML report to reports/.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    building_attributes = {
        "roof_age": args.roof_age,
        "fortified_status": args.fortified,
        "shutters_status": args.shutters,
    }

    record = run_one_address(args.address, building_attributes)
    append_to_csv(record)
    append_recommendations_to_csv(record["property_id"], record.get("recommendations", []))

    print(json.dumps(record, indent=2, default=str))
    print(f"\nAppended indicators to {OUTPUT_CSV}", file=sys.stderr)
    if record.get("recommendations"):
        print(f"Appended recommendations to {RECOMMENDATIONS_CSV}", file=sys.stderr)

    if args.report:
        report_path = write_report(record, REPORTS_DIR)
        print(f"Wrote report to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
