"""Resolve a geocoded point to its East Baton Rouge Parish tax parcel.

Implements Phase 3, Step 3.2 of the blueprint: parcel-level geometry
lookup, so a report can eventually say more than "here is a single
point" (every report currently carries an explicit caveat that no
parcel polygon lookup exists — this closes that gap for the pilot
parish).

Data source: East Baton Rouge Parish's own Tax Parcels layer
(``Tax_Parcels_2026``), part of the EBRGIS open-data portal already used
by ebr_local_drainage_indicators.py:
  https://services.arcgis.com/KYvXadMcgf0K1EzK/arcgis/rest/services/Tax_Parcels_2026/FeatureServer/0

CRITICAL — this layer's full schema includes real PII and financial
data: ``OWNER``, ``OWNER_ADDRESS``, ``OWNER_CITY_STATE_ZIP``, and several
``SUM_*`` assessment/valuation/homestead-exemption fields. ``OUT_FIELDS``
below is a deliberate whitelist — those fields are NEVER requested, not
merely filtered out afterward, the same "don't even transiently hold it"
discipline already used for the Census API key in
census_acs_indicators.py.

CRITICAL — exact point-in-parcel intersection is unreliable in practice.
Live-tested at 2 real East Baton Rouge addresses during development
(750 Florida St and 7117 Jefferson Hwy): BOTH returned zero features at
a zero-tolerance point intersect. Widening the search radius finds
candidates, but they are not in tidy address-number order near the
point (near "7117 Jefferson Hwy" the nearest candidates within 25m were
numbered 7054/7059/7125/7147 — no exact match), so "nearest polygon" is
NOT a safe stand-in for "correct parcel": it risks confidently
attributing a report to the wrong property, which is worse than
reporting no match. Because of this, a match is only ever returned when
either (a) the point falls exactly inside exactly one parcel, or
(b) exactly one nearby candidate's own ``PHYSICAL_ADDRESS`` field
text-matches the geocoded address. Anything else returns
``match_quality: "no_confident_match"`` rather than a guess — expect
this to happen often, not rarely.

The parish's own ``FLOOD_ZONE`` field (e.g. observed live: "X / X
PROTECTED BY LEVEE") is reported as parcel context, explicitly labeled
as the assessor's record — it is NOT a substitute for the live FEMA
NFHL query in flood_indicators.py, and the two are never merged; both
can be shown, and they can legitimately disagree.

No other indicator module was changed to use the parcel polygon in this
pass — flood/terrain/wind/etc. all still query by point. Using the
parcel boundary to improve those (e.g. "does any part of this parcel
intersect the floodway") is a real future improvement, not bundled here.
"""

from __future__ import annotations

import datetime
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.ebr_parish import point_in_parish  # noqa: E402

TAX_PARCELS_URL = "https://services.arcgis.com/KYvXadMcgf0K1EzK/arcgis/rest/services/Tax_Parcels_2026/FeatureServer/0/query"
SOURCE_ID = "EBR_TAX_PARCELS"

# Deliberate whitelist — see module docstring. Never add OWNER,
# OWNER_ADDRESS, OWNER_CITY_STATE_ZIP, or any SUM_* field here.
OUT_FIELDS = "ID1,ASSESSMENT_NUM,PHYSICAL_ADDRESS,SUBDIVISION,LOT,BLOCK,WARD_SECTION,FLOOD_ZONE,STATUS,Shape__Area"

ADDRESS_MATCH_BUFFER_M = 75


def _ci_attrs(attrs: dict) -> dict:
    return {str(k).lower(): v for k, v in attrs.items()}


def _query_point(lon: float, lat: float, timeout: int) -> list[dict]:
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": OUT_FIELDS,
        "returnGeometry": "false",
        "f": "json",
    }
    return _run_query(params, timeout)


def _query_buffer(lon: float, lat: float, radius_m: float, timeout: int) -> list[dict]:
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "distance": radius_m,
        "units": "esriSRUnit_Meter",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": OUT_FIELDS,
        "returnGeometry": "false",
        "f": "json",
    }
    return _run_query(params, timeout)


def _run_query(params: dict, timeout: int) -> list[dict]:
    url = f"{TAX_PARCELS_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "GeoShield-Prototype/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    return payload.get("features", [])


def _address_parts(address: str) -> tuple[str | None, set[str]]:
    """(house_number, street_name_words) — simple, auditable text
    matching, not fuzzy scoring. Words under 3 letters (e.g. "ST", "DR"
    direction/suffix abbreviations) are excluded so a match requires a
    real distinguishing word (e.g. "JEFFERSON")."""
    if not address:
        return None, set()
    tokens = address.strip().upper().replace(",", " ").split()
    if not tokens:
        return None, set()
    house_number = tokens[0] if tokens[0].isdigit() else None
    words = {t for t in tokens[1:] if len(t) >= 3 and t.isalpha()}
    return house_number, words


def _address_matches(candidate_address: str | None, geocoded_address: str) -> bool:
    cand_num, cand_words = _address_parts(candidate_address or "")
    geo_num, geo_words = _address_parts(geocoded_address)
    if cand_num is None or geo_num is None or cand_num != geo_num:
        return False
    return bool(cand_words & geo_words)


def get_parcel_context(lon: float, lat: float, matched_address: str, timeout: int = 20) -> dict:
    """Return East Baton Rouge Parish tax-parcel context for a point, or
    an honest "no confident match" rather than a guess.

    Never fetches owner/financial fields (see module docstring). Never
    returns a spatially-nearest parcel as if it were confirmed — only an
    exact point-in-parcel hit or an address-text-confirmed nearby parcel
    counts as a match.
    """
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        in_parish = point_in_parish(lon, lat, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError) as exc:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "error": f"Parish Boundary lookup failed: {exc}",
            "quality_flag": "N/A",
        }

    if not in_parish:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "in_service_area": False,
            "note": "This point is outside East Baton Rouge Parish. This "
                    "parish-specific tax parcel layer has no coverage "
                    "here — expected for any pilot address outside the "
                    "parish, not a data error.",
            "quality_flag": "N/A",
        }

    try:
        exact = _query_point(lon, lat, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError) as exc:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "in_service_area": True,
            "error": f"Tax Parcels query failed: {exc}",
            "quality_flag": "N/A",
        }

    match = None
    match_quality = "no_confident_match"

    if len(exact) == 1:
        match = exact[0]
        match_quality = "exact_spatial_match"
    elif len(exact) == 0:
        try:
            candidates = _query_buffer(lon, lat, ADDRESS_MATCH_BUFFER_M, timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError) as exc:
            return {
                "source_id": SOURCE_ID,
                "checked_at_utc": checked_at,
                "data_available": False,
                "in_service_area": True,
                "error": f"Tax Parcels buffer query failed: {exc}",
                "quality_flag": "N/A",
            }
        address_matches = [
            f for f in candidates
            if _address_matches(_ci_attrs(f.get("attributes", {})).get("physical_address"), matched_address)
        ]
        if len(address_matches) == 1:
            match = address_matches[0]
            match_quality = "address_matched"
    # len(exact) > 1 (overlapping/duplicate records) also falls through
    # to no_confident_match — ambiguous, not guessed.

    if match is None:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": True,
            "in_service_area": True,
            "parcel_found": False,
            "match_quality": match_quality,
            "quality_flag": "N/A",
            "customer_caveat": (
                "No parcel could be confidently identified for this "
                "point in East Baton Rouge Parish's tax parcel records. "
                "This means the match couldn't be verified, not that no "
                "parcel exists — a nearby-but-unconfirmed parcel is "
                "deliberately not shown, since attributing a report to "
                "the wrong property would be worse than showing nothing."
            ),
        }

    attrs = _ci_attrs(match.get("attributes", {}))
    area_sqft = attrs.get("shape__area")
    return {
        "source_id": SOURCE_ID,
        "checked_at_utc": checked_at,
        "data_available": True,
        "in_service_area": True,
        "parcel_found": True,
        "match_quality": match_quality,
        "parcel_id": attrs.get("assessment_num"),
        "parcel_physical_address": attrs.get("physical_address"),
        "parcel_subdivision": attrs.get("subdivision"),
        "parcel_lot": attrs.get("lot"),
        "parcel_block": attrs.get("block"),
        "parcel_area_sqft": round(area_sqft, 1) if isinstance(area_sqft, (int, float)) else None,
        "parcel_flood_zone": attrs.get("flood_zone"),
        "quality_flag": "A" if match_quality == "exact_spatial_match" else "B",
        "customer_caveat": (
            "Parcel identification only, not a surveyed building "
            "footprint. Owner name/address and assessment/valuation "
            "fields are deliberately never fetched from this source. "
            "'parcel_flood_zone' is East Baton Rouge Parish's own "
            "assessor record, separate from and not a substitute for "
            "the live FEMA NFHL flood-zone query elsewhere in this "
            "report — the two can legitimately disagree."
        ),
    }


def main() -> None:
    if len(sys.argv) != 4:
        print(f"Usage: python {sys.argv[0]} <longitude> <latitude> <matched_address>", file=sys.stderr)
        raise SystemExit(2)
    result = get_parcel_context(float(sys.argv[1]), float(sys.argv[2]), sys.argv[3])
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
