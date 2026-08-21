"""Query USGS National Hydrography Dataset (NHD) services for distance to
mapped water/drainage features near a point.

Implements Phase 4.1's checklist item "Distance to mapped water/drainage
features" and Phase 4.4's Step 7.1 report requirement ("Terrain/drainage
proxies and explicit limitations"). Deliberately does NOT implement Step
4.4.1's DEM-conditioning/flow-accumulation/depression-mapping work — the
blueprint requires local validation against observed events before any
modeled surface-water accumulation or drainage-performance finding is
published, and none of that validation has been done. This module only
ever reports proximity to features NHD has already mapped; it never infers
or scores drainage performance.

Data source: USGS National Map hydrography services, hosted as a public
ArcGIS MapServer (no API key required):
  https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer

Four sublayers are queried:
  - Flowline - Large Scale (layer 6): NHDFlowline — streams/rivers and
    canals/ditches (StreamRiver/ArtificialPath FCodes bucket into
    ``nearest_stream_or_river_m``; CanalDitch FCodes bucket into
    ``nearest_canal_or_ditch_m``). Connector, Pipeline, and Underground
    Conduit FTypes are deliberately excluded — they are network-topology
    artifacts or buried infrastructure, not surface channels a homeowner
    could observe.
  - Waterbody - Large Scale (layer 12): NHDWaterbody — lakes/ponds,
    reservoirs, swamp/marsh, estuary, ice mass, playa.
  - Area - Large Scale (layer 9): NHDArea — the same real-world feature
    types as above but represented as polygons at this scale (e.g. wide
    rivers/canals, bays, inundation areas); merged into the matching
    category by FCode rather than treated as a separate bucket.
  - Line - Large Scale (layer 2), filtered to FCode 56800 only: NHDLine's
    LEVEE feature type. Other NHDLine ancillary types (bridge, dam/weir,
    wall, etc.) are out of scope for a drainage-context module.

FCode -> label mapping is taken from the official USGS NHD FCode reference
("Complete FCode List for NHD Hydrography Features"), not guessed.

Field-name casing is NOT consistent across these sublayers — confirmed by
live querying during development: the Flowline layer returns lowercase
attribute keys (``fcode``, ``gnis_name``, ...) while Waterbody/Area/Line
return uppercase (``FCODE``, ``GNIS_NAME``, ...). All attribute access
below goes through ``_ci_attrs`` (case-insensitive) specifically because
this was found to silently break a fixed-case lookup during testing.

Verified live against all 3 existing regression addresses during
development:
  - 750 Florida St, Baton Rouge (downtown, ~1km from the river): flowline
    query correctly returned "Mississippi River" (FCode 55800,
    ArtificialPath).
  - 6300 Bellaire Dr, New Orleans (Lakeview): line-layer query correctly
    returned 3 nearby Levee (FCode 56800) features — Lakeview sits behind
    the 17th St/Orleans Ave canal levees, so this is physically correct,
    not a placeholder.
  - 5500 Paris Ave, New Orleans (Gentilly): waterbody query correctly
    returned "Lake Pontchartrain" plus nearby unnamed LakePond features.

Critical limitation, stated here and repeated in every returned record's
``customer_caveat``: this reports proximity to *mapped* features only. No
flow-accumulation, depression, or drainage-performance modeling has been
done. Many small or local drainage ditches are not captured in this
national dataset, so the absence of a nearby feature is not evidence of
good drainage.
"""

from __future__ import annotations

import datetime
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.geo_utils import (  # noqa: E402
    lonlat_to_webmercator,
    min_distance_to_paths,
    min_distance_to_polygon,
)

NHD_MAPSERVER_URL = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer"
SOURCE_ID = "USGS_NHD"

FLOWLINE_LAYER = 6
WATERBODY_LAYER = 12
AREA_LAYER = 9
LINE_LAYER = 2

DEFAULT_RADIUS_M = 1000

# FCodes bucketed by category. Connector (33400), Pipeline (428xx), and
# Underground Conduit (420xx) are deliberately excluded — see module
# docstring.
STREAM_OR_RIVER_FCODES = {46000, 46003, 46006, 46007, 55800}
CANAL_OR_DITCH_FCODES = {33600, 33601, 33603}
LEVEE_FCODE = 56800

FCODE_LABELS = {
    46000: "Stream/River", 46003: "Stream/River (intermittent)",
    46006: "Stream/River (perennial)", 46007: "Stream/River (ephemeral)",
    55800: "River/waterway (mapped centerline)",
    33600: "Canal/Ditch", 33601: "Canal/Ditch (aqueduct)", 33603: "Canal/Ditch (stormwater)",
    39000: "Lake/Pond", 39001: "Lake/Pond (intermittent)", 39004: "Lake/Pond (perennial)",
    39005: "Lake/Pond (intermittent)", 39006: "Lake/Pond (intermittent)",
    39009: "Lake/Pond (perennial)", 39010: "Lake/Pond (perennial)",
    39011: "Lake/Pond (perennial)", 39012: "Lake/Pond (perennial)",
    46600: "Swamp/Marsh", 46601: "Swamp/Marsh (intermittent)", 46602: "Swamp/Marsh (perennial)",
    49300: "Estuary", 37800: "Ice Mass", 36100: "Playa",
    31200: "Bay/Inlet", 44500: "Sea/Ocean", 48400: "Wash",
    56800: "Levee",
}


def _fcode_label(fcode: int) -> str:
    if fcode in FCODE_LABELS:
        return FCODE_LABELS[fcode]
    if 43600 <= fcode < 43700:
        return "Reservoir"
    if 40300 <= fcode < 40400:
        return "Inundation area"
    return f"Mapped water feature (FCode {fcode})"


def _ci_attrs(attrs: dict) -> dict:
    """Case-insensitive view of an ArcGIS feature's attributes dict.

    Field-name casing differs across NHD sublayers (see module docstring);
    all callers should read through this rather than a fixed-case key.
    """
    return {str(k).lower(): v for k, v in attrs.items()}


def _degree_offsets(lat: float, radius_m: float) -> tuple[float, float]:
    dlat = radius_m / 111320
    dlon = radius_m / (111320 * math.cos(math.radians(lat)))
    return dlon, dlat


def _feature_distance_m(px: float, py: float, geom: dict) -> float | None:
    if geom.get("paths"):
        return min_distance_to_paths(px, py, geom["paths"])
    if geom.get("rings"):
        return min_distance_to_polygon(px, py, geom["rings"])
    return None


def _nearest(px: float, py: float, features: list[dict]) -> dict | None:
    best = None
    for feat in features:
        dist = _feature_distance_m(px, py, feat.get("geometry", {}))
        if dist is None:
            continue
        if best is None or dist < best["distance_m"]:
            attrs = _ci_attrs(feat.get("attributes", {}))
            fcode = attrs.get("fcode")
            best = {
                "distance_m": round(dist, 1),
                "feature_name": attrs.get("gnis_name") or "unnamed",
                "feature_type_label": _fcode_label(fcode) if fcode is not None else "Mapped water feature",
            }
    return best


def _query_layer(layer_id: int, lon: float, lat: float, radius_m: float, timeout: int) -> list[dict]:
    dlon, dlat = _degree_offsets(lat, radius_m)
    envelope = {
        "xmin": lon - dlon, "ymin": lat - dlat,
        "xmax": lon + dlon, "ymax": lat + dlat,
        "spatialReference": {"wkid": 4326},
    }
    params = {
        "geometry": json.dumps(envelope),
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": 4326,
        "f": "json",
    }
    url = f"{NHD_MAPSERVER_URL}/{layer_id}/query?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "GeoShield-Prototype/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    return payload.get("features", [])


def get_drainage_context(lon: float, lat: float, radius_m: float = DEFAULT_RADIUS_M,
                          timeout: int = 20) -> dict:
    """Return the nearest mapped stream/river, canal/ditch, waterbody, and
    levee within ``radius_m`` of a point, from USGS NHD.

    Never computes or infers a drainage grade, flow-accumulation value, or
    depression map — Phase 4.4 explicitly requires local validation before
    any of that can be published, and none has been done. This function
    reports mapped-feature proximity only.
    """
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    px, py = lonlat_to_webmercator(lon, lat)

    try:
        flowlines = _query_layer(FLOWLINE_LAYER, lon, lat, radius_m, timeout)
        areas = _query_layer(AREA_LAYER, lon, lat, radius_m, timeout)
        waterbodies = _query_layer(WATERBODY_LAYER, lon, lat, radius_m, timeout)
        lines = _query_layer(LINE_LAYER, lon, lat, radius_m, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError) as exc:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "error": str(exc),
            "quality_flag": "N/A",
        }

    def _fcode_of(feat: dict):
        return _ci_attrs(feat.get("attributes", {})).get("fcode")

    stream_feats = [f for f in flowlines + areas if _fcode_of(f) in STREAM_OR_RIVER_FCODES]
    ditch_feats = [f for f in flowlines + areas if _fcode_of(f) in CANAL_OR_DITCH_FCODES]
    other_area_feats = [f for f in areas
                         if _fcode_of(f) not in STREAM_OR_RIVER_FCODES and _fcode_of(f) not in CANAL_OR_DITCH_FCODES]
    levee_feats = [f for f in lines if _fcode_of(f) == LEVEE_FCODE]

    nearest_stream = _nearest(px, py, stream_feats)
    nearest_ditch = _nearest(px, py, ditch_feats)
    nearest_waterbody = _nearest(px, py, waterbodies + other_area_feats)
    nearest_levee = _nearest(px, py, levee_feats)

    overall = min(
        (c["distance_m"] for c in (nearest_stream, nearest_ditch, nearest_waterbody, nearest_levee) if c is not None),
        default=None,
    )

    record = {
        "source_id": SOURCE_ID,
        "checked_at_utc": checked_at,
        "data_available": True,
        "search_radius_m": radius_m,
        "nearest_stream_or_river_m": nearest_stream["distance_m"] if nearest_stream else None,
        "nearest_stream_or_river_name": nearest_stream["feature_name"] if nearest_stream else None,
        "nearest_canal_or_ditch_m": nearest_ditch["distance_m"] if nearest_ditch else None,
        "nearest_canal_or_ditch_name": nearest_ditch["feature_name"] if nearest_ditch else None,
        "nearest_waterbody_m": nearest_waterbody["distance_m"] if nearest_waterbody else None,
        "nearest_waterbody_name": nearest_waterbody["feature_name"] if nearest_waterbody else None,
        "nearest_waterbody_type": nearest_waterbody["feature_type_label"] if nearest_waterbody else None,
        "nearest_levee_m": nearest_levee["distance_m"] if nearest_levee else None,
        "nearest_mapped_water_or_drainage_feature_m": overall,
        "quality_flag": "C",
        "customer_caveat": (
            "Proximity to features mapped in the USGS National Hydrography "
            "Dataset only — not a drainage-performance model. No "
            "flow-accumulation, depression, or surface-water-modeling "
            "analysis has been done (the blueprint requires validating any "
            "such model against observed local events first). Many small "
            "or local drainage ditches are not captured in this national "
            "dataset, so no nearby feature within "
            f"{radius_m:.0f}m is not evidence of good drainage."
        ),
    }
    if overall is None:
        record["note"] = (
            f"No stream, canal/ditch, waterbody, or levee mapped in NHD "
            f"within {radius_m:.0f}m of this point."
        )
    return record


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <longitude> <latitude>", file=sys.stderr)
        raise SystemExit(2)
    result = get_drainage_context(float(sys.argv[1]), float(sys.argv[2]))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
