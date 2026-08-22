"""Query FEMA's effective National Flood Hazard Layer (NFHL) for a point.

Implements Phase 4.1.1 of the GeoShield blueprint:
  - Intersect the property/point with effective NFHL features where available.
  - Record zone/subtype and effective map date/metadata.
  - Flag mapped floodway separately.
  - If no effective digital data are present, state that clearly rather
    than assigning a false low-risk result.

Data source: FEMA NFHL public MapServer (no API key required).
  https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer
  Layer 28 = Flood Hazard Zones, Layer 3 = FIRM Panels (effective date).

This is real, live public data — not a mock. Coverage is not nationwide
digital/effective everywhere; a query returning zero features must be
reported as "no effective digital NFHL data at this location," never as
a low-risk result (blueprint quality rule, Phase 3 Step 3.4: quality
flag N/A when no reliable data exists).
"""

from __future__ import annotations

import datetime
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

NFHL_BASE = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
FLOOD_ZONE_LAYER = 28
FIRM_PANEL_LAYER = 3
SOURCE_ID = "FEMA_NFHL_EFFECTIVE"


def _query_layer(layer_id: int, lon: float, lat: float, out_fields: str, timeout: int) -> list[dict]:
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{NFHL_BASE}/{layer_id}/query?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "GeoShield-Prototype/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    if "error" in payload:
        raise RuntimeError(f"NFHL layer {layer_id} query error: {payload['error']}")
    return [f["attributes"] for f in payload.get("features", [])]


def get_flood_indicators(lon: float, lat: float, timeout: int = 20) -> dict:
    """Return flood-zone atomic indicators for a point, per Step 4.1.1.

    Never fabricates a zone when none is found — returns
    ``fema_zone: None`` and ``data_available: False`` instead, matching
    the blueprint's explicit no-data rule.
    """
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        zone_features = _query_layer(
            FLOOD_ZONE_LAYER, lon, lat,
            "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,DFIRM_ID",
            timeout,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError) as exc:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "error": str(exc),
            "quality_flag": "N/A",
        }

    if not zone_features:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "note": "No effective digital NFHL flood-zone feature intersects this point.",
            "fema_zone": None,
            "floodway_flag": None,
            "quality_flag": "N/A",
        }

    zf = zone_features[0]
    zone_subtype = (zf.get("ZONE_SUBTY") or "")
    floodway_flag = "FLOODWAY" in zone_subtype.upper()

    # Effective map date, from the FIRM panel covering this point (best effort).
    eff_date = None
    try:
        panel_features = _query_layer(FIRM_PANEL_LAYER, lon, lat, "EFF_DATE,FIRM_PAN", timeout)
        if panel_features:
            eff_date = panel_features[0].get("EFF_DATE")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError):
        pass  # Panel date is supplementary; absence doesn't invalidate the zone result.

    static_bfe = zf.get("STATIC_BFE")
    if static_bfe == -9999.0:
        static_bfe = None  # FEMA sentinel value for "not applicable."

    return {
        "source_id": SOURCE_ID,
        "checked_at_utc": checked_at,
        "data_available": True,
        "fema_zone": zf.get("FLD_ZONE"),
        "zone_subtype": zone_subtype or None,
        "special_flood_hazard_area": zf.get("SFHA_TF") == "T",
        "floodway_flag": floodway_flag,
        "base_flood_elevation_ft": static_bfe,
        "dfirm_id": zf.get("DFIRM_ID"),
        "effective_date_epoch_ms": eff_date,
        "quality_flag": "A",
        "customer_caveat": (
            "Zone is FEMA map context, not total flood risk; FEMA maps do "
            "not capture every flood source or future conditions."
        ),
    }


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <longitude> <latitude>", file=sys.stderr)
        raise SystemExit(2)
    result = get_flood_indicators(float(sys.argv[1]), float(sys.argv[2]))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
