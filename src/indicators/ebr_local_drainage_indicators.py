"""Query East Baton Rouge Parish's own GIS services (EBRGIS open-data
portal) for local stormwater infrastructure and drainage-district context.

This closes a real, explicitly-documented gap in
``drainage_indicators.py`` (USGS NHD, national): *"Many small or local
drainage ditches are not captured in this national dataset."* EBR Parish
maintains its own municipal stormwater asset inventory — individual pipe/
ditch segments and catch basins/manholes — that NHD has no knowledge of.

This module is deliberately separate from ``drainage_indicators.py``
rather than an extension of it: this source is parish-scoped and will
NEVER have data outside East Baton Rouge Parish. That is a categorically
different kind of "unavailable" than a national API having a transient
failure, so it gets its own ``source_id``/``data_available``/
``in_service_area`` semantics rather than being folded into NHD's.

Same scope boundary as ``drainage_indicators.py``: this reports asset
*locations* only — pipe/structure proximity — never a capacity, flow, or
drainage-performance model. The blueprint's Phase 4.4 validation gate
still applies.

Four EBRGIS ArcGIS REST services are used, all confirmed live and
publicly queryable (no API key) via the portal's DCAT catalog
(``https://web-ebrgis.opendata.arcgis.com/api/feed/dcat-us/1.1.json``,
255 datasets total):

  - Parish Boundary (coverage gate) —
    maps.brla.gov/gis/rest/services/Governmental_Units/Parish_Boundary/MapServer/0
    Used FIRST to distinguish "outside East Baton Rouge Parish" (expected,
    correct, not an error) from "in-parish but nothing nearby" or "API
    failed." Verified live: the Baton Rouge reference point correctly
    intersects (PARISH_NAME "East Baton Rouge"); the existing Lakeview,
    New Orleans reference point correctly does NOT (0 features — Orleans
    is a different parish).
  - Stormwater Conveyance (pipes/ditches, line geometry) —
    utility.arcgis.com/usrsvcs/servers/de50e129067b480c808ec3552d7b2fc8/rest/services/Infrastructure_Secure/Stormwater_Asset/MapServer/1
    Despite the "Infrastructure_Secure" path segment, confirmed publicly
    queryable with no auth error — 761 real segments returned within
    500m of the Baton Rouge reference point.
  - Stormwater Structure (catch basins/manholes, point geometry) —
    utility.arcgis.com/usrsvcs/servers/a8d2ff1f6b7e43139d72a3050970823a/rest/services/Infrastructure_Secure/Stormwater_Asset/MapServer/0
    773 real features in the same test.
  - Drainage District (administrative polygon) —
    services.arcgis.com/KYvXadMcgf0K1EzK/arcgis/rest/services/Drainage_District/FeatureServer/0
    Point-in-polygon at the Baton Rouge point correctly returned "Gravity
    Drainage District #1".

Structure/material field codes (e.g. ``STRUCTURE_TYPE: "SI"``,
``MATERIAL: "CONC"``) are reported RAW, not translated — the service's
own field metadata (``?f=json``) exposes no coded-value domain for them,
so guessing a label would risk fabricating meaning. A data dictionary
exists at city.brla.gov/gis/metadata/STORMWATER_STRUCTURE.html
(confirmed live) for a future pass to decode these properly.

Portal license (site-level metadata): "For public use ... provides the
information herein for general reference purposes only." No restriction
found blocking this use.
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
from common.geo_utils import lonlat_to_webmercator, min_distance_to_paths, min_distance_to_polygon  # noqa: E402
from common.ebr_parish import point_in_parish  # noqa: E402

STORMWATER_CONVEYANCE_URL = (
    "https://utility.arcgis.com/usrsvcs/servers/de50e129067b480c808ec3552d7b2fc8"
    "/rest/services/Infrastructure_Secure/Stormwater_Asset/MapServer/1/query"
)
STORMWATER_STRUCTURE_URL = (
    "https://utility.arcgis.com/usrsvcs/servers/a8d2ff1f6b7e43139d72a3050970823a"
    "/rest/services/Infrastructure_Secure/Stormwater_Asset/MapServer/0/query"
)
DRAINAGE_DISTRICT_URL = "https://services.arcgis.com/KYvXadMcgf0K1EzK/arcgis/rest/services/Drainage_District/FeatureServer/0/query"

SOURCE_ID = "EBR_PARISH_GIS"
DEFAULT_RADIUS_M = 500


def _ci_attrs(attrs: dict) -> dict:
    """Case-insensitive view of an ArcGIS feature's attributes dict — EBR's
    services return uppercase field names, same defensive pattern used in
    drainage_indicators.py for NHD's inconsistent casing."""
    return {str(k).lower(): v for k, v in attrs.items()}


def _degree_offsets(lat: float, radius_m: float) -> tuple[float, float]:
    dlat = radius_m / 111320
    dlon = radius_m / (111320 * math.cos(math.radians(lat)))
    return dlon, dlat


def _query(url: str, lon: float, lat: float, radius_m: float, timeout: int) -> list[dict]:
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
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(full_url, headers={"User-Agent": "GeoShield-Prototype/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    return payload.get("features", [])


def _nearest_asset(px: float, py: float, features: list[dict], id_field: str,
                    extra_fields: tuple[str, ...]) -> dict | None:
    best = None
    for feat in features:
        geom = feat.get("geometry", {})
        if geom.get("paths"):
            dist = min_distance_to_paths(px, py, geom["paths"])
        elif geom.get("rings"):
            dist = min_distance_to_polygon(px, py, geom["rings"])
        elif geom.get("x") is not None and geom.get("y") is not None:
            fx, fy = lonlat_to_webmercator(geom["x"], geom["y"])
            dist = math.hypot(px - fx, py - fy)
        else:
            continue
        if best is None or dist < best["distance_m"]:
            attrs = _ci_attrs(feat.get("attributes", {}))
            best = {
                "distance_m": round(dist, 1),
                "asset_id": attrs.get(id_field.lower()),
                **{f: attrs.get(f.lower()) for f in extra_fields},
            }
    return best


def get_ebr_local_drainage_context(lon: float, lat: float, radius_m: float = DEFAULT_RADIUS_M,
                                    timeout: int = 20) -> dict:
    """Return nearest local stormwater pipe/structure distances and
    drainage-district name for a point, from East Baton Rouge Parish's
    own GIS services.

    Returns ``data_available: False, in_service_area: False`` (not an
    error) for any point outside East Baton Rouge Parish — this dataset
    genuinely does not exist there, checked first via the Parish Boundary
    layer rather than inferred from an empty stormwater-asset query
    (which would be indistinguishable from "in-parish but nothing
    nearby").
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
            "note": (
                "This point is outside East Baton Rouge Parish. EBR "
                "Parish's local stormwater GIS has no coverage here — "
                "this is expected for any pilot address outside the "
                "parish, not a data error."
            ),
            "quality_flag": "N/A",
        }

    px, py = lonlat_to_webmercator(lon, lat)
    try:
        conveyance_feats = _query(STORMWATER_CONVEYANCE_URL, lon, lat, radius_m, timeout)
        structure_feats = _query(STORMWATER_STRUCTURE_URL, lon, lat, radius_m, timeout)
        district_feats = _query(DRAINAGE_DISTRICT_URL, lon, lat, radius_m, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError) as exc:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "in_service_area": True,
            "error": f"EBR stormwater asset query failed: {exc}",
            "quality_flag": "N/A",
        }

    nearest_pipe = _nearest_asset(px, py, conveyance_feats, "CONVEYANCE_ID", ("MATERIAL",))
    nearest_structure = _nearest_asset(px, py, structure_feats, "STRUCTURE_ID", ("STRUCTURE_TYPE", "MATERIAL"))

    district_name = None
    for feat in district_feats:
        geom = feat.get("geometry", {})
        if geom.get("rings") and min_distance_to_polygon(px, py, geom["rings"]) == 0.0:
            district_name = _ci_attrs(feat.get("attributes", {})).get("name")
            break

    overall = min(
        (c["distance_m"] for c in (nearest_pipe, nearest_structure) if c is not None),
        default=None,
    )

    return {
        "source_id": SOURCE_ID,
        "checked_at_utc": checked_at,
        "data_available": True,
        "in_service_area": True,
        "search_radius_m": radius_m,
        "nearest_stormwater_pipe_m": nearest_pipe["distance_m"] if nearest_pipe else None,
        "nearest_stormwater_pipe_material": nearest_pipe.get("MATERIAL") if nearest_pipe else None,
        "nearest_stormwater_structure_m": nearest_structure["distance_m"] if nearest_structure else None,
        "nearest_stormwater_structure_type": nearest_structure.get("STRUCTURE_TYPE") if nearest_structure else None,
        "drainage_district_name": district_name,
        "nearest_local_stormwater_asset_m": overall,
        "quality_flag": "C",
        "customer_caveat": (
            "East Baton Rouge Parish's own stormwater asset inventory — "
            "pipe/structure LOCATIONS only, not a capacity or "
            "flow-performance model. Covers East Baton Rouge Parish "
            "only. Structure/material codes are reported as recorded by "
            "the parish, not translated to plain language, pending the "
            "parish's own data dictionary."
        ),
    }


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <longitude> <latitude>", file=sys.stderr)
        raise SystemExit(2)
    result = get_ebr_local_drainage_context(float(sys.argv[1]), float(sys.argv[2]))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
