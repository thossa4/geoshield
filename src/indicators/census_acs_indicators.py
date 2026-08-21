"""Query the Census Bureau's American Community Survey (ACS) 5-Year
Detailed Tables for census-tract-level housing/social context.

Implements the blueprint's Phase 2.1 source list entry for Census ACS:
"Neighborhood-level housing/social context for optional B2B/community
views." This is deliberately NOT a hazard indicator and NOT part of the
core Home Passport pipeline (run_one_address.py does not call this module)
— it exists for a possible future community/B2B view, per the blueprint's
own scoping of this source.

Two live services are involved:

1. Census Geocoder "geographies/coordinates" endpoint (keyless, public) —
   resolves a lon/lat point to its containing state/county/census-tract
   FIPS codes. Verified live during development against the existing
   Baton Rouge reference point (750 Florida St): correctly returned tract
   GEOID 22033005100 (East Baton Rouge Parish, tract 005100) — the exact
   same tract already independently confirmed in
   src/indicators/wind_indicators.py's FEMA NRI verification notes, which
   is a real cross-source consistency check, not a coincidence.

2. Census Data API ACS 5-Year Detailed Tables (requires a free registered
   API key — confirmed live 2026-08-20 that every request without one
   redirects to https://api.census.gov/data/missing_key.html with an
   ``X-DataWebAPI-KeyError`` header; this was re-tested across two
   release years to confirm it is a platform-wide policy, not specific to
   one dataset). Unlike every other live source in this repo (FEMA, USGS,
   NOAA, USGS NHD), this one is NOT keyless. See docs/data_registry.csv,
   CENSUS_ACS row.

Verified live 2026-08-21 (with a founder-provided API key) at all 3
existing reference addresses:
  - Baton Rouge (tract 22033005100): population 3,051; median household
    income $52,827; owner-occupied 10.6% — a dense downtown tract with
    heavy rental/apartment stock, physically plausible.
  - Lakeview, New Orleans (tract 22071007607 — the exact same tract
    already independently confirmed in wind_indicators.py's own live
    verification, a real cross-source consistency check, not a
    coincidence): population 2,622; median household income $103,824;
    owner-occupied 61.6%.
  - Gentilly, New Orleans (tract 22071003301): population 2,439; median
    household income $111,563; owner-occupied 80.0% — both New Orleans
    tracts show the higher-income, higher-owner-occupancy pattern typical
    of stable, rebuilt residential neighborhoods, a sensible contrast
    with downtown Baton Rouge's dense rental tract.

ACS suppresses certain estimates for small/unreliable samples using
sentinel values (commonly -666666666 for "not available/not computed").
``_clean`` filters any large-magnitude negative value out rather than
returning it as a real number — same defensive pattern this repo already
uses for FEMA's -9999 BFE sentinel and NLCD's 127 NODATA sentinel. None
of the 4 variables queried above happened to be suppressed at any of the
3 verified tracts, so this specific sentinel path is implemented per
Census's documented convention but still not directly exercised by a
real response — worth rechecking if a future address hits a
small-sample tract.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

GEOCODER_GEOGRAPHIES_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
ACS5_URL = "https://api.census.gov/data/2024/acs/acs5"
SOURCE_ID = "CENSUS_ACS_5YEAR"
API_KEY_ENV_VAR = "CENSUS_API_KEY"

# variable -> (label, unit note)
ACS_VARIABLES = {
    "B01003_001E": ("total_population", None),
    "B19013_001E": ("median_household_income_usd", None),
    "B25003_001E": ("occupied_housing_units_total", None),
    "B25003_002E": ("owner_occupied_housing_units", None),
}

# ACS suppresses unreliable/unavailable estimates with large-magnitude
# negative sentinels (documented Census convention; not yet live-observed
# in this module — see module docstring).
_SUPPRESSED_SENTINEL_THRESHOLD = -1_000_000


def _clean(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return value
    if num <= _SUPPRESSED_SENTINEL_THRESHOLD:
        return None
    return num


def _get_tract_geography(lon: float, lat: float, timeout: int) -> dict | None:
    params = {
        "x": lon, "y": lat,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    url = f"{GEOCODER_GEOGRAPHIES_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "GeoShield-Prototype/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    tracts = payload.get("result", {}).get("geographies", {}).get("Census Tracts", [])
    if not tracts:
        return None
    tract = tracts[0]
    return {"state": tract.get("STATE"), "county": tract.get("COUNTY"), "tract": tract.get("TRACT"), "geoid": tract.get("GEOID")}


def get_acs_context(lon: float, lat: float, timeout: int = 20) -> dict:
    """Return tract-level ACS 5-year housing/social context for a point.

    Requires ``CENSUS_API_KEY`` to be set in the environment. Returns
    ``data_available: False`` (not an exception) if the key is missing,
    the geocoder can't resolve a tract, or the ACS request fails — same
    graceful-degradation convention as every other indicator module here.
    """
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    api_key = os.environ.get(API_KEY_ENV_VAR)
    if not api_key:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "error": f"{API_KEY_ENV_VAR} is not set. Get a free key at "
                     "https://api.census.gov/data/key_signup.html and set "
                     f"the {API_KEY_ENV_VAR} environment variable.",
            "quality_flag": "N/A",
        }

    try:
        geo = _get_tract_geography(lon, lat, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "error": f"Census Geocoder geographies lookup failed: {exc}",
            "quality_flag": "N/A",
        }
    if geo is None:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "note": "No Census Tract found for this point.",
            "quality_flag": "N/A",
        }

    get_fields = ",".join(["NAME"] + list(ACS_VARIABLES.keys()))
    params = {
        "get": get_fields,
        "for": f"tract:{geo['tract']}",
        "in": f"state:{geo['state']} county:{geo['county']}",
        "key": api_key,
    }
    url = f"{ACS5_URL}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GeoShield-Prototype/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            rows = json.load(resp)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "error": f"Census ACS5 request failed: {exc}",
            "quality_flag": "N/A",
            "census_tract_geoid": geo["geoid"],
        }

    if len(rows) < 2:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "note": "ACS5 returned no data row for this tract.",
            "quality_flag": "N/A",
            "census_tract_geoid": geo["geoid"],
        }

    header, values = rows[0], rows[1]
    record = dict(zip(header, values))

    result = {
        "source_id": SOURCE_ID,
        "checked_at_utc": checked_at,
        "data_available": True,
        "census_tract_geoid": geo["geoid"],
        "census_tract_name": record.get("NAME"),
    }
    for var, (label, _unit) in ACS_VARIABLES.items():
        result[label] = _clean(record.get(var))

    owner_occ = result.get("owner_occupied_housing_units")
    total_occ = result.get("occupied_housing_units_total")
    result["owner_occupied_pct"] = (
        round(100 * owner_occ / total_occ, 1)
        if owner_occ is not None and total_occ else None
    )
    result["quality_flag"] = "C"
    result["customer_caveat"] = (
        "Census-tract-level American Community Survey 5-year estimate, "
        "not a property-specific figure — every address in the same "
        "tract shares this value. 5-year estimates carry sampling error "
        "and describe a multi-year period, not the current year. This is "
        "neighborhood housing/social context, not a hazard indicator, "
        "and is not currently part of the Home Passport report."
    )
    return result


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <longitude> <latitude>", file=sys.stderr)
        raise SystemExit(2)
    result = get_acs_context(float(sys.argv[1]), float(sys.argv[2]))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
