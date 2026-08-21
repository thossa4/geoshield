"""Query USGS/MRLC NLCD land cover, impervious %, and tree canopy % for a point.

Implements the land-cover portion of Phase 4.3, Step 4.3.1 of the
GeoShield blueprint (tree canopy/land-cover around property, impervious
surface percentage). This was previously flagged in this repo as "no
working public point-query endpoint found yet" — that has now been
resolved: MRLC's GeoServer WMS GetFeatureInfo operation returns the raw
pixel value at a point for the CONUS NLCD raster layers, no API key
required.

Data source: MRLC GeoServer WMS (https://www.mrlc.gov/geoserver/wms),
layers:
  - mrlc_display:NLCD_2021_Land_Cover_L48   (categorical class code)
  - mrlc_display:NLCD_2021_Impervious_L48   (% impervious, 0-100)
  - mrlc_display:nlcd_tcc_conus_2021_v2021-4 (% tree canopy cover, 0-100)

Verified against three real Louisiana points during development:
  - Downtown Baton Rouge  -> class 24 (Developed, High Intensity), 94% impervious, 0% canopy
  - Same downtown block   -> consistent repeat result
  - Atchafalaya Basin     -> class 90 (Woody Wetlands), 0% impervious, 90% canopy
These are physically sensible, confirming the endpoint returns real data,
not a placeholder/error value.

Important limitation the blueprint explicitly warns about (Step 4.3.1,
and the general raster-resolution caveat repeated throughout Phase 3-4):
``get_landcover_indicators`` samples a SINGLE 30m pixel at the point,
not an areal statistic. ``get_landcover_buffer_stats`` (added later)
approximates the blueprint's `impervious_250m_pct` / `tree_250m_pct`
data-dictionary fields (Phase A) by grid-sampling multiple points across
a buffer and averaging — this is a discrete-grid approximation, not a
true pixel-weighted zonal statistic (which would require a WCS raster
clip). Both sampling strategies are exposed separately; do not present
the single-pixel value to a customer as a buffer/neighborhood statistic.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.geo_utils import lonlat_to_webmercator, grid_offsets_m  # noqa: E402

WMS_URL = "https://www.mrlc.gov/geoserver/wms"
SOURCE_ID = "USGS_NLCD_MRLC_WMS"

LAND_COVER_LAYER = "mrlc_display:NLCD_2021_Land_Cover_L48"
IMPERVIOUS_LAYER = "mrlc_display:NLCD_2021_Impervious_L48"
TREE_CANOPY_LAYER = "mrlc_display:nlcd_tcc_conus_2021_v2021-4"

# Standard NLCD 2021 class legend (public, from MRLC documentation).
NLCD_CLASS_LABELS = {
    11: "Open Water",
    12: "Perennial Ice/Snow",
    21: "Developed, Open Space",
    22: "Developed, Low Intensity",
    23: "Developed, Medium Intensity",
    24: "Developed, High Intensity",
    31: "Barren Land",
    41: "Deciduous Forest",
    42: "Evergreen Forest",
    43: "Mixed Forest",
    52: "Shrub/Scrub",
    71: "Grassland/Herbaceous",
    81: "Pasture/Hay",
    82: "Cultivated Crops",
    90: "Woody Wetlands",
    95: "Emergent Herbaceous Wetlands",
}

# No-data sentinel used by these byte rasters.
NODATA_VALUE = 127


def _get_feature_info_at_xy(layer: str, x: float, y: float, timeout: int, half_extent_m: float = 20) -> int | None:
    bbox = f"{x - half_extent_m},{y - half_extent_m},{x + half_extent_m},{y + half_extent_m}"
    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetFeatureInfo",
        "layers": layer,
        "query_layers": layer,
        "crs": "EPSG:3857",
        "bbox": bbox,
        "width": "3",
        "height": "3",
        "i": "1",
        "j": "1",
        "info_format": "application/json",
    }
    url = f"{WMS_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        payload = json.load(resp)
    features = payload.get("features", [])
    if not features:
        return None
    return features[0].get("properties", {}).get("PALETTE_INDEX")


def _get_feature_info(layer: str, lon: float, lat: float, timeout: int, half_extent_m: float = 20) -> int | None:
    x, y = lonlat_to_webmercator(lon, lat)
    return _get_feature_info_at_xy(layer, x, y, timeout, half_extent_m)


def get_landcover_indicators(lon: float, lat: float, timeout: int = 20) -> dict:
    """Return single-pixel (30m) NLCD land cover / impervious / canopy values.

    Returns ``data_available: False`` per-field if a layer query fails or
    returns the NODATA sentinel, rather than fabricating a value.
    """
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = {
        "source_id": SOURCE_ID,
        "checked_at_utc": checked_at,
        "data_available": False,
        "land_cover_class_code": None,
        "land_cover_class_label": None,
        "impervious_pct_pixel": None,
        "tree_canopy_pct_pixel": None,
        "sample_type": "single_30m_pixel_at_point",
        "quality_flag": None,
    }

    try:
        class_code = _get_feature_info(LAND_COVER_LAYER, lon, lat, timeout)
        impervious = _get_feature_info(IMPERVIOUS_LAYER, lon, lat, timeout)
        canopy = _get_feature_info(TREE_CANOPY_LAYER, lon, lat, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        result["error"] = str(exc)
        result["quality_flag"] = "N/A"
        return result

    if class_code is not None and class_code != NODATA_VALUE:
        result["land_cover_class_code"] = class_code
        result["land_cover_class_label"] = NLCD_CLASS_LABELS.get(class_code, f"Unrecognized class {class_code}")
        result["data_available"] = True

    if impervious is not None and impervious != NODATA_VALUE:
        result["impervious_pct_pixel"] = impervious

    if canopy is not None and canopy != NODATA_VALUE:
        result["tree_canopy_pct_pixel"] = canopy

    if result["data_available"]:
        result["quality_flag"] = "C"  # area-scale 30m pixel proxy, not parcel-specific (Step 3.4)
        result["customer_caveat"] = (
            "Single 30m-pixel sample at this point (NLCD 2021), not a "
            "parcel- or buffer-area statistic; raster resolution limits "
            "parcel-scale interpretation."
        )
    else:
        result["quality_flag"] = "N/A"
        result["note"] = "No usable NLCD pixel value returned at this point."

    return result


DEFAULT_BUFFER_RADIUS_M = 250
DEFAULT_BUFFER_STEP_M = 125


def get_landcover_buffer_stats(
    lon: float,
    lat: float,
    radius_m: float = DEFAULT_BUFFER_RADIUS_M,
    step_m: float = DEFAULT_BUFFER_STEP_M,
    timeout: int = 20,
    max_workers: int = 8,
) -> dict:
    """Approximate impervious%/tree-canopy% within ``radius_m`` of a point.

    Grid-samples the same live MRLC WMS layers used by
    ``get_landcover_indicators`` at multiple points spaced ``step_m``
    apart across the buffer, and averages the valid (non-NODATA)
    results. This is a discrete-grid mean, not a true pixel-weighted
    zonal statistic — with the default 250m radius / 125m step it
    queries ~21 points per layer.

    Never fabricates a value: if a layer returns zero valid samples,
    its buffer-mean field is ``None`` and the quality flag reflects
    that. Partial coverage (some points failed/timed out) is reported
    via the sample-count fields rather than silently ignored.
    """
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cx, cy = lonlat_to_webmercator(lon, lat)
    offsets = grid_offsets_m(radius_m, step_m)
    points = [(cx + dx, cy + dy) for dx, dy in offsets]
    expected_count = len(points)

    def _sample_layer(layer: str) -> list[int]:
        values: list[int] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_get_feature_info_at_xy, layer, x, y, timeout) for x, y in points]
            for future in futures:
                try:
                    value = future.result()
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
                    value = None
                if value is not None and value != NODATA_VALUE:
                    values.append(value)
        return values

    impervious_values = _sample_layer(IMPERVIOUS_LAYER)
    canopy_values = _sample_layer(TREE_CANOPY_LAYER)

    result = {
        "source_id": f"{SOURCE_ID}_BUFFER",
        "checked_at_utc": checked_at,
        "data_available": bool(impervious_values or canopy_values),
        "radius_m": radius_m,
        "step_m": step_m,
        "sample_type": "grid_sample_mean",
        "impervious_pct_buffer_mean": round(sum(impervious_values) / len(impervious_values), 1) if impervious_values else None,
        "impervious_sample_count": len(impervious_values),
        "tree_canopy_pct_buffer_mean": round(sum(canopy_values) / len(canopy_values), 1) if canopy_values else None,
        "tree_canopy_sample_count": len(canopy_values),
        "expected_sample_count": expected_count,
    }

    if result["data_available"]:
        coverage = max(len(impervious_values), len(canopy_values)) / expected_count if expected_count else 0
        result["quality_flag"] = "C" if coverage >= 0.5 else "D"
        result["customer_caveat"] = (
            f"Grid-sampled mean over {expected_count} points spaced "
            f"{step_m:.0f}m apart within a {radius_m:.0f}m radius (NLCD "
            "2021, 30m raster) — a discrete-grid approximation of a "
            "buffer-area statistic, not a true pixel-weighted zonal "
            "calculation. Raster resolution still limits parcel-scale "
            "precision."
        )
    else:
        result["quality_flag"] = "N/A"
        result["note"] = "No usable NLCD pixel values returned across the sampled buffer."

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Query NLCD land cover for a point, optionally with a buffer-area estimate.")
    parser.add_argument("longitude", type=float)
    parser.add_argument("latitude", type=float)
    parser.add_argument("--buffer", action="store_true", help="Also compute grid-sampled buffer-area stats (slower, multiple requests).")
    parser.add_argument("--radius-m", type=float, default=DEFAULT_BUFFER_RADIUS_M)
    args = parser.parse_args()

    result = get_landcover_indicators(args.longitude, args.latitude)
    if args.buffer:
        result["buffer_stats"] = get_landcover_buffer_stats(args.longitude, args.latitude, radius_m=args.radius_m)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
