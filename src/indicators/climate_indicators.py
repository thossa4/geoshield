"""Query NOAA NCEI for historical climate/heat context near a point.

Implements the climate portion of Phase 4.3, Step 4.3.1 of the GeoShield
blueprint: "Historical heat/climate context from NOAA or other
authoritative sources." Also matches the `heat_context` field in the
Phase A data dictionary ("Historical climate/heat context... Not indoor
temperature prediction").

This was previously flagged in this repo as blocked — "NCEI's API
requires a requested token" — based on the token-gated CDO v2 API
(cdo-web/api/v2). That assumption turned out to be wrong for this use
case: NCEI separately publishes a free, no-key "Data Service" (v1) that
serves the same underlying climate-normals data, plus a matching
no-key "Search Service" to find the nearest weather station to a
lon/lat point. Both were found by testing NCEI's own access-services
documentation paths directly, not guessed.

Data sources (both official NOAA/NCEI, no API key required):
  Search:  https://www.ncei.noaa.gov/access/services/search/v1/data
  Data:    https://www.ncei.noaa.gov/access/services/data/v1
  Dataset: normals-monthly-1991-2020 (the current 30-year normals period)

Verified against two real Louisiana points during development:
  - Baton Rouge -> nearest station USW00013970 (Baton Rouge Metro
    Airport), July TMAX normal 91.9F, correctly the hottest month.
  - New Orleans -> distinct, geographically appropriate set of nearby
    stations returned (USC00168941, USW00012916, etc.), confirming the
    search is real point-based lookup, not a fixed/cached result.

Limitation stated up front, consistent with the rest of this codebase:
this is STATION-level point data (the nearest weather station, which
may be several km away), not a spatial interpolation to the exact
address, and normals describe 1991-2020 averages, not this year's
actual or forecast conditions.
"""

from __future__ import annotations

import datetime
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request

SEARCH_URL = "https://www.ncei.noaa.gov/access/services/search/v1/data"
DATA_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
DATASET = "normals-monthly-1991-2020"
SOURCE_ID = "NOAA_NCEI_NORMALS_MONTHLY"

MONTH_NAMES = {
    "01": "January", "02": "February", "03": "March", "04": "April",
    "05": "May", "06": "June", "07": "July", "08": "August",
    "09": "September", "10": "October", "11": "November", "12": "December",
}


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _find_candidate_stations(lon: float, lat: float, timeout: int) -> list[tuple[str, float]]:
    """Return [(station_id, distance_km), ...] sorted nearest-first,
    widening the search bounding box a few times if nothing is found
    nearby (e.g. remote/rural coordinates).

    Returns multiple candidates rather than just the single nearest
    station because not every station returned by the search actually
    has complete monthly-normals data (e.g. precipitation-only
    stations) — the caller should try candidates in order until one
    has usable data, rather than giving up on the nearest one alone.
    """
    for delta in (0.3, 0.75, 1.5):
        bbox = f"{lat + delta},{lon - delta},{lat - delta},{lon + delta}"
        params = {
            "dataset": DATASET,
            "bbox": bbox,
            "startDate": "2010-01-01",
            "endDate": "2020-12-31",
            "limit": 25,
        }
        url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "GeoShield-Prototype/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)

        candidates: list[tuple[str, float]] = []
        for result in payload.get("results", []):
            stations = result.get("stations") or []
            coords = (result.get("location") or {}).get("coordinates")
            if not stations or not coords:
                continue
            station_id = stations[0].get("id")
            dist = round(_haversine_km(lon, lat, coords[0], coords[1]), 1)
            candidates.append((station_id, dist))

        if candidates:
            candidates.sort(key=lambda c: c[1])
            return candidates

    return []


def _fetch_monthly_normals(station_id: str, timeout: int) -> tuple[dict[str, float], dict[str, float]]:
    """Fetch monthly TMAX/CLDD normals for one station. Returns two
    dicts keyed by month code ("01".."12"); either may be empty if that
    field wasn't reported by this station."""
    params = {"dataset": DATASET, "stations": station_id, "format": "json"}
    url = f"{DATA_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "GeoShield-Prototype/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        monthly_records = json.load(resp)

    monthly_max: dict[str, float] = {}
    monthly_cldd: dict[str, float] = {}
    for rec in monthly_records:
        month = rec.get("DATE")
        tmax_raw = rec.get("MLY-TMAX-NORMAL")
        cldd_raw = rec.get("MLY-CLDD-BASE50")
        try:
            if tmax_raw is not None:
                monthly_max[month] = float(tmax_raw)
        except (TypeError, ValueError):
            pass
        try:
            if cldd_raw is not None:
                monthly_cldd[month] = float(cldd_raw)
        except (TypeError, ValueError):
            pass
    return monthly_max, monthly_cldd


def get_climate_context(lon: float, lat: float, timeout: int = 20, max_candidates: int = 12) -> dict:
    """Return heat/climate normals context for the nearest weather
    station to (lon, lat) that actually has usable monthly TMAX data.

    Tries up to ``max_candidates`` nearest stations in distance order,
    since not every station in the search results reports complete
    normals — many nearby volunteer precipitation-only stations
    ("US1..." CoCoRaHS-style IDs) have no temperature fields at all, so
    the default is set generously (12) based on real testing where the
    nearest station with usable TMAX data was the 7th-closest overall.
    Never fabricates values: if no candidate station is found or none
    has usable data, returns ``data_available: False``.
    """
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        candidates = _find_candidate_stations(lon, lat, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "error": str(exc),
            "quality_flag": "N/A",
        }

    if not candidates:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "note": "No NOAA NCEI normals station found near this point.",
            "quality_flag": "N/A",
        }

    station_id, distance_km = None, None
    monthly_max, monthly_cldd = {}, {}
    tried_stations = []
    for candidate_id, candidate_dist in candidates[:max_candidates]:
        tried_stations.append(candidate_id)
        try:
            candidate_max, candidate_cldd = _fetch_monthly_normals(candidate_id, timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            continue
        if candidate_max:
            station_id, distance_km = candidate_id, candidate_dist
            monthly_max, monthly_cldd = candidate_max, candidate_cldd
            break

    if not monthly_max:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "note": f"No usable monthly TMAX normals found among {len(tried_stations)} nearest stations: {tried_stations}.",
            "quality_flag": "N/A",
        }

    hottest_month_code = max(monthly_max, key=monthly_max.get)
    annual_mean_max_temp_f = round(sum(monthly_max.values()) / len(monthly_max), 1)
    annual_cooling_degree_days = round(sum(monthly_cldd.values()), 1) if monthly_cldd else None

    return {
        "source_id": SOURCE_ID,
        "checked_at_utc": checked_at,
        "data_available": True,
        "station_id": station_id,
        "station_distance_km": distance_km,
        "normals_period": "1991-2020",
        "annual_mean_max_temp_f": annual_mean_max_temp_f,
        "hottest_month": MONTH_NAMES.get(hottest_month_code, hottest_month_code),
        "hottest_month_max_temp_f": round(monthly_max[hottest_month_code], 1),
        "annual_cooling_degree_days": annual_cooling_degree_days,
        "quality_flag": "B" if (distance_km is not None and distance_km <= 25) else "C",
        "customer_caveat": (
            f"Based on 1991-2020 climate normals from the nearest NOAA "
            f"weather station ({distance_km} km away), not a measurement "
            "at this exact address. Describes typical historical "
            "conditions, not this year's actual or forecast weather, "
            "and is not an indoor temperature prediction."
        ),
    }


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <longitude> <latitude>", file=sys.stderr)
        raise SystemExit(2)
    result = get_climate_context(float(sys.argv[1]), float(sys.argv[2]))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
