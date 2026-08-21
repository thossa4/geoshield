"""Shared geometry helpers for grid-sampling around a property point.

Used by both the land-cover buffer stats (Phase 4.3) and the
neighborhood relative-elevation percentile (Phase 4.1.2) — both features
need to convert a center lon/lat into a set of nearby sample points
within a radius, query a raster/API at each point, and aggregate. Kept
in one place so the coordinate math is verified once rather than
maintained in two copies that could silently diverge.

Web Mercator (EPSG:3857, spherical approximation, R ~ 6378137m) is used
as the working projection because both the MRLC WMS layers and simple
meter-based offsets are naturally expressed in it. Round-trip accuracy
was verified against a real Baton Rouge coordinate to floating-point
precision (~1e-15 degrees) during development.
"""

from __future__ import annotations

import math

# Half the WGS84-sphere equatorial circumference in meters (EPSG:3857 constant).
_WEBMERCATOR_HALF_CIRCUMFERENCE_M = 20037508.34


def lonlat_to_webmercator(lon: float, lat: float) -> tuple[float, float]:
    x = lon * _WEBMERCATOR_HALF_CIRCUMFERENCE_M / 180
    y = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180)
    y = y * _WEBMERCATOR_HALF_CIRCUMFERENCE_M / 180
    return x, y


def webmercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    radius = _WEBMERCATOR_HALF_CIRCUMFERENCE_M / math.pi
    lon = x / _WEBMERCATOR_HALF_CIRCUMFERENCE_M * 180
    lat_rad = 2 * math.atan(math.exp(y / radius)) - math.pi / 2
    lat = lat_rad * 180 / math.pi
    return lon, lat


def grid_offsets_m(radius_m: float, step_m: float) -> list[tuple[float, float]]:
    """Return (dx, dy) meter offsets within a circle of ``radius_m``,
    spaced ``step_m`` apart on a square grid centered at the origin.
    Always includes the center point (0, 0)."""
    n = max(1, round(radius_m / step_m))
    coords = [i * step_m for i in range(-n, n + 1)]
    return [(dx, dy) for dx in coords for dy in coords if dx * dx + dy * dy <= radius_m * radius_m]


# Nearest-feature distance helpers, originally written for
# indicators/drainage_indicators.py (USGS NHD) and promoted here so
# indicators/ebr_local_drainage_indicators.py (East Baton Rouge Parish
# GIS) can reuse the same, already-verified coordinate math rather than a
# second copy — the exact duplication this module's docstring says to
# avoid. All operate in Web Mercator meters via lonlat_to_webmercator.

def point_to_segment_distance_m(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def min_distance_to_paths(px: float, py: float, paths: list) -> float:
    """Minimum distance from (px, py) [Web Mercator meters] to any segment
    across a list of paths, each a list of [lon, lat] vertices."""
    best = math.inf
    for path in paths:
        merc = [lonlat_to_webmercator(x, y) for x, y in path]
        for (ax, ay), (bx, by) in zip(merc, merc[1:]):
            best = min(best, point_to_segment_distance_m(px, py, ax, ay, bx, by))
    return best


def point_in_rings(px: float, py: float, rings: list) -> bool:
    """Even-odd point-in-polygon test summed across all rings (each a list
    of [lon, lat] vertices), so exterior rings and interior (hole) rings
    combine correctly without needing to know which is which."""
    inside = False
    for ring in rings:
        merc = [lonlat_to_webmercator(x, y) for x, y in ring]
        closed = merc if merc[0] == merc[-1] else merc + [merc[0]]
        for (ax, ay), (bx, by) in zip(closed, closed[1:]):
            if (ay > py) != (by > py):
                x_at_py = ax + (py - ay) * (bx - ax) / (by - ay)
                if px < x_at_py:
                    inside = not inside
    return inside


def min_distance_to_polygon(px: float, py: float, rings: list) -> float:
    """0.0 if (px, py) is inside the polygon, else the minimum distance to
    its boundary. ``rings`` is a list of rings, each a list of [lon, lat]
    vertices (esri JSON polygon-geometry shape)."""
    if point_in_rings(px, py, rings):
        return 0.0
    return min_distance_to_paths(px, py, rings)
