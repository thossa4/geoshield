"""Query USGS 3DEP elevation for a point via the Elevation Point Query Service.

Implements the elevation portion of Phase 4.1.2 of the GeoShield
blueprint: sample the best available DEM at/near the parcel.
``get_terrain_indicators`` returns the raw sampled elevation only.
``get_neighborhood_elevation_stats`` (added later) implements the rest
of Step 4.1.2 / Phase 3 Step 3.3 — "Calculate local neighborhood
elevation distribution... Report relative position in plain language
(for example, lower/higher than nearby terrain)" — by grid-sampling
EPQS around the point, the same discrete-grid pattern proven for
land-cover buffer stats (src/indicators/landcover_indicators.py). This
is still not a surveyed finished-floor elevation, and the "neighborhood"
reference geography here is simply the sampled grid itself, not an
independently-chosen administrative or hydrologic boundary — that
distinction is called out in the result's caveat text.

Data source: USGS Elevation Point Query Service (EPQS v1), no API key
required.
  https://epqs.nationalmap.gov/v1/json
"""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.geo_utils import lonlat_to_webmercator, webmercator_to_lonlat, grid_offsets_m  # noqa: E402

EPQS_URL = "https://epqs.nationalmap.gov/v1/json"
SOURCE_ID = "USGS_3DEP_EPQS"
NODATA_SENTINEL_THRESHOLD = -1e6


def get_terrain_indicators(lon: float, lat: float, timeout: int = 20) -> dict:
    """Return the sampled ground elevation at (lon, lat) in meters.

    Returns ``data_available: False`` (never a fabricated elevation) if
    the service errors or returns no usable value.
    """
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    elevation_m, resolution_m, error = _fetch_elevation_m(lon, lat, timeout)

    if error is not None:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "error": error,
            "quality_flag": "N/A",
        }

    if elevation_m is None:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "note": "USGS EPQS returned no usable elevation value at this point.",
            "quality_flag": "N/A",
        }

    return {
        "source_id": SOURCE_ID,
        "checked_at_utc": checked_at,
        "data_available": True,
        "ground_elevation_m": elevation_m,
        "resolution_m": resolution_m,
        "quality_flag": "B",
        "customer_caveat": (
            "Sampled DEM elevation at this point only; not a surveyed "
            "finished-floor elevation. See neighborhood relative-elevation "
            "fields for how this compares to nearby sampled points."
        ),
    }


def _fetch_elevation_m(lon: float, lat: float, timeout: int) -> tuple[float | None, float | None, str | None]:
    """Fetch a single EPQS elevation value. Returns (elevation_m,
    resolution_m, error_message) — exactly one of elevation_m or
    error_message will be meaningfully set (both None means "no usable
    value, but no request error either," e.g. the sentinel case)."""
    params = {"x": lon, "y": lat, "units": "Meters", "wkid": 4326, "includeDate": "false"}
    url = f"{EPQS_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return None, None, str(exc)

    raw_value = payload.get("value")
    try:
        elevation_m = float(raw_value)
    except (TypeError, ValueError):
        return None, None, None

    if elevation_m <= NODATA_SENTINEL_THRESHOLD:
        # EPQS returns a large negative sentinel for no-data locations.
        return None, None, None

    return elevation_m, payload.get("resolution"), None


DEFAULT_NEIGHBORHOOD_RADIUS_M = 250
DEFAULT_NEIGHBORHOOD_STEP_M = 125


def get_neighborhood_elevation_stats(
    lon: float,
    lat: float,
    radius_m: float = DEFAULT_NEIGHBORHOOD_RADIUS_M,
    step_m: float = DEFAULT_NEIGHBORHOOD_STEP_M,
    timeout: int = 20,
    max_workers: int = 8,
) -> dict:
    """Grid-sample USGS 3DEP elevation around a point and report where
    the center point sits relative to its sampled surroundings.

    Implements Phase 3 Step 3.3 ("local min/max; relative elevation to
    neighborhood") and the Step 4.1.2 instruction to "report relative
    position in plain language... rather than implying a surveyed
    finished-floor elevation." The "neighborhood" here is the discrete
    grid actually sampled (same 250m/125m default as the land-cover
    buffer stats), not an independently chosen administrative or
    hydrologic reference geography — that is a real limitation, stated
    in the output caveat, not glossed over.

    Never fabricates a percentile from an empty sample: if fewer than 2
    neighborhood points return usable elevation (in addition to the
    center point itself), ``data_available`` is False.
    """
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cx, cy = lonlat_to_webmercator(lon, lat)
    offsets = grid_offsets_m(radius_m, step_m)
    points = [(cx + dx, cy + dy) for dx, dy in offsets]
    expected_count = len(points)

    def _sample(xy: tuple[float, float]) -> float | None:
        plon, plat = webmercator_to_lonlat(*xy)
        elevation_m, _resolution, _error = _fetch_elevation_m(plon, plat, timeout)
        return elevation_m

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        neighborhood_values = [v for v in executor.map(_sample, points) if v is not None]

    center_elevation_m, _center_resolution, center_error = _fetch_elevation_m(lon, lat, timeout)

    result = {
        "source_id": f"{SOURCE_ID}_NEIGHBORHOOD",
        "checked_at_utc": checked_at,
        "data_available": False,
        "radius_m": radius_m,
        "step_m": step_m,
        "sample_type": "grid_sample_percentile",
        "center_elevation_m": center_elevation_m,
        "neighborhood_sample_count": len(neighborhood_values),
        "expected_sample_count": expected_count,
    }

    if center_elevation_m is None or len(neighborhood_values) < 2:
        result["quality_flag"] = "N/A"
        result["note"] = (
            "Insufficient usable elevation samples to compute a "
            "neighborhood comparison."
            + (f" ({center_error})" if center_error else "")
        )
        return result

    sorted_values = sorted(neighborhood_values)
    rank = sum(1 for v in sorted_values if v <= center_elevation_m)
    percentile_rank = round(100 * rank / len(sorted_values), 1)

    if percentile_rank <= 25:
        label = "notably lower than most sampled nearby points"
    elif percentile_rank <= 45:
        label = "somewhat lower than most sampled nearby points"
    elif percentile_rank <= 55:
        label = "about the same elevation as sampled nearby points"
    elif percentile_rank <= 75:
        label = "somewhat higher than most sampled nearby points"
    else:
        label = "notably higher than most sampled nearby points"

    result.update({
        "data_available": True,
        "neighborhood_min_m": round(min(sorted_values), 2),
        "neighborhood_max_m": round(max(sorted_values), 2),
        "neighborhood_mean_m": round(statistics.mean(sorted_values), 2),
        "neighborhood_median_m": round(statistics.median(sorted_values), 2),
        "percentile_rank": percentile_rank,
        "relative_position_label": label,
        "quality_flag": "C",
        "customer_caveat": (
            f"Relative position is computed against {len(sorted_values)} "
            f"points grid-sampled within {radius_m:.0f}m of this address "
            "(same source, same 30m-ish DEM resolution) — not against an "
            "independently defined neighborhood or drainage boundary, "
            "and not a substitute for a surveyed finished-floor "
            "elevation."
        ),
    })
    return result


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Query USGS 3DEP elevation for a point, optionally with a neighborhood percentile.")
    parser.add_argument("longitude", type=float)
    parser.add_argument("latitude", type=float)
    parser.add_argument("--neighborhood", action="store_true", help="Also compute grid-sampled neighborhood elevation percentile.")
    args = parser.parse_args()

    result = get_terrain_indicators(args.longitude, args.latitude)
    if args.neighborhood:
        result["neighborhood_stats"] = get_neighborhood_elevation_stats(args.longitude, args.latitude)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
