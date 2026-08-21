"""Query FEMA's National Risk Index for county/census-tract-level
hurricane and strong-wind hazard context.

Implements Phase 4.2.1 of the GeoShield blueprint: "Regional wind/
hurricane context can come from authoritative hazard/climate sources.
Building vulnerability cannot be inferred accurately from a map alone."
This module supplies exactly the regional half of that split — it never
infers roof condition, structural vulnerability, or FORTIFIED status
from area-level data. That half stays user-attribute-driven in
src/recommendations/rules_engine.py, as the blueprint requires.

This was the last remaining "no independent data source, rules only"
gap in the wind module, closed by using FEMA's National Risk Index
(NRI) — the same source category this repo's data registry already
listed as FEMA_RAPT/TODO (Phase 24's official source list references
"FEMA Resilience Analysis and Planning Tool (RAPT) — Community-scale
resilience and National Risk Index access/context").

Data source: FEMA National Risk Index, Census Tracts layer, hosted as a
public ArcGIS FeatureServer (no API key required). The exact service URL
was found via ArcGIS Online's public item-search API
(https://www.arcgis.com/sharing/rest/search) rather than guessed, since
FEMA's own hazards.fema.gov NRI endpoint returned 403 Forbidden during
development.
  https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Census_Tracts/FeatureServer

Verified against two real Louisiana points during development:
  - Downtown Baton Rouge (East Baton Rouge Parish, tract 005100):
    Hurricane risk score 95.3 "Relatively High"; Strong Wind risk score
    41.1 "Relatively Low".
  - Lakeview, New Orleans (Orleans Parish, tract 007607):
    Hurricane risk score 92.2 "Relatively High"; Strong Wind risk score
    13.1 "Very Low".
Both physically sensible (coastal Louisiana correctly rated high
hurricane risk) and clearly distinguish hurricane risk from the
separate, lower strong-wind risk category — confirming this is real
per-tract data, not a placeholder.

Critical limitation, stated in the blueprint's own FEMA resilience
source-category caution ("Often too coarse for property-level
conclusions; present as area context") and repeated here: this is
CENSUS-TRACT-level data, not parcel- or address-level. Every property
within the same tract gets the identical value. Never present this as a
property-specific finding.
"""

from __future__ import annotations

import datetime
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

NRI_FEATURESERVER_URL = (
    "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
    "National_Risk_Index_Census_Tracts/FeatureServer/0/query"
)
SOURCE_ID = "FEMA_NRI_CENSUS_TRACTS"

OUT_FIELDS = (
    "STATEABBRV,COUNTY,TRACT,"
    "HRCN_RISKS,HRCN_RISKR,HRCN_EALR,HRCN_AFREQ,"
    "SWND_RISKS,SWND_RISKR,SWND_EALR,SWND_AFREQ"
)


def get_wind_hazard_context(lon: float, lat: float, timeout: int = 20) -> dict:
    """Return census-tract-level hurricane and strong-wind hazard
    context for a point, from FEMA's National Risk Index.

    Never fabricates a rating when no tract feature intersects the
    point (e.g. outside the covered geography) — returns
    ``data_available: False`` instead.
    """
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": OUT_FIELDS,
        "returnGeometry": "false",
        "f": "json",
    }
    url = f"{NRI_FEATURESERVER_URL}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GeoShield-Prototype/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "error": str(exc),
            "quality_flag": "N/A",
        }

    if "error" in payload:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "error": str(payload["error"]),
            "quality_flag": "N/A",
        }

    features = payload.get("features", [])
    if not features:
        return {
            "source_id": SOURCE_ID,
            "checked_at_utc": checked_at,
            "data_available": False,
            "note": "No National Risk Index census-tract feature intersects this point.",
            "quality_flag": "N/A",
        }

    attrs = features[0].get("attributes", {})

    def _round(value):
        return round(value, 1) if isinstance(value, (int, float)) else value

    return {
        "source_id": SOURCE_ID,
        "checked_at_utc": checked_at,
        "data_available": True,
        "state": attrs.get("STATEABBRV"),
        "county": attrs.get("COUNTY"),
        "census_tract": attrs.get("TRACT"),
        "hurricane_risk_score": _round(attrs.get("HRCN_RISKS")),
        "hurricane_risk_rating": attrs.get("HRCN_RISKR"),
        "hurricane_expected_annual_loss_rating": attrs.get("HRCN_EALR"),
        "hurricane_annualized_frequency": _round(attrs.get("HRCN_AFREQ")),
        "strong_wind_risk_score": _round(attrs.get("SWND_RISKS")),
        "strong_wind_risk_rating": attrs.get("SWND_RISKR"),
        "strong_wind_expected_annual_loss_rating": attrs.get("SWND_EALR"),
        "strong_wind_annualized_frequency": _round(attrs.get("SWND_AFREQ")),
        "quality_flag": "C",
        "customer_caveat": (
            "Census-tract-level FEMA National Risk Index context, not a "
            "property-specific assessment — every address in the same "
            "tract shares this value. Risk score is a nationally "
            "percentile-ranked composite (0-100), not a wind speed or "
            "structural design value. Does not reflect this specific "
            "building's roof, construction, or FORTIFIED status."
        ),
    }


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <longitude> <latitude>", file=sys.stderr)
        raise SystemExit(2)
    result = get_wind_hazard_context(float(sys.argv[1]), float(sys.argv[2]))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
