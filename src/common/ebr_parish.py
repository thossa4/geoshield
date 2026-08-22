"""Shared "is this point inside East Baton Rouge Parish" check.

Promoted out of indicators/ebr_local_drainage_indicators.py so
geocoding/ebr_parcel_lookup.py can reuse the identical, already-verified
gate rather than a second copy — both EBR-only data sources need to
distinguish "outside East Baton Rouge Parish" (expected, correct, not an
error) from an actual API failure or an in-parish "nothing found."

Data source: East Baton Rouge Parish's own Parish Boundary polygon,
public ArcGIS MapServer (no API key). Verified live: the existing Baton
Rouge reference point correctly intersects (PARISH_NAME "East Baton
Rouge"); the existing Lakeview, New Orleans reference point correctly
does not (0 features — Orleans is a different parish).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

PARISH_BOUNDARY_URL = "https://maps.brla.gov/gis/rest/services/Governmental_Units/Parish_Boundary/MapServer/0/query"


def point_in_parish(lon: float, lat: float, timeout: int = 20) -> bool:
    """Return True if (lon, lat) is inside East Baton Rouge Parish.

    Raises the same network/JSON exceptions as urllib/json on failure —
    callers decide how to report that (see ebr_local_drainage_indicators.py
    and ebr_parcel_lookup.py for the established data_available:False
    convention).
    """
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "PARISH_NAME",
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{PARISH_BOUNDARY_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "GeoShield-Prototype/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    return bool(payload.get("features"))
