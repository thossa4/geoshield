"""Geocode a US street address using the free US Census Geocoder.

Implements Phase 3, Step 3.1 of the GeoShield blueprint: normalize the
address, geocode to lat/long, return match quality, and store the
geocoder/provider, timestamp, input address, matched address, and
coordinates. This is a public, no-API-key-required government service —
appropriate for an MVP prototype. Swap for a commercial geocoder later if
match rates on real customer addresses prove insufficient.

Usage:
    python geocode_address.py "750 Florida St, Baton Rouge, LA 70801"
"""

from __future__ import annotations

import datetime
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

CENSUS_GEOCODER_URL = (
    "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
)
SOURCE_ID = "CENSUS_GEOCODER_ONELINE"


def geocode(address: str, timeout: int = 15) -> dict:
    """Geocode ``address`` and return a GeoShield-shaped result dict.

    Raises ``RuntimeError`` if the request fails or the service returns no
    match. Callers must decide how to prompt the user for confirmation on
    low-confidence or missing matches (Step 3.1) rather than silently
    guessing.
    """
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "format": "json",
    }
    url = f"{CENSUS_GEOCODER_URL}?{urllib.parse.urlencode(params)}"
    requested_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GeoShield-Prototype/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"Census geocoder request failed: {exc}") from exc

    matches = payload.get("result", {}).get("addressMatches", [])
    if not matches:
        return {
            "input_address": address,
            "matched_address": None,
            "longitude": None,
            "latitude": None,
            "match_quality": "no_match",
            "geocoder_provider": SOURCE_ID,
            "requested_at_utc": requested_at,
            "needs_user_confirmation": True,
        }

    # The Census geocoder does not return a numeric confidence score; a
    # single match on a oneline query is treated as a candidate that still
    # requires user pin confirmation per Step 3.1, and multiple matches are
    # always ambiguous.
    best = matches[0]
    coords = best["coordinates"]
    match_quality = "single_candidate" if len(matches) == 1 else "ambiguous"

    return {
        "input_address": address,
        "matched_address": best.get("matchedAddress"),
        "longitude": coords["x"],
        "latitude": coords["y"],
        "match_quality": match_quality,
        "candidate_count": len(matches),
        "geocoder_provider": SOURCE_ID,
        "requested_at_utc": requested_at,
        "needs_user_confirmation": True,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} \"<address>\"", file=sys.stderr)
        raise SystemExit(2)
    result = geocode(sys.argv[1])
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
