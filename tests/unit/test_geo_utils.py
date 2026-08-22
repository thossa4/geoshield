"""Fast, deterministic unit tests for src/common/geo_utils.py.

No network calls — this file's functions are pure math, unlike almost
everything else in this repo. Complements
tests/regression/test_reference_properties.py rather than replacing
it: the regression suite proves the live pipeline works end-to-end
against real government data; this file proves the shared geometry
math itself is correct in isolation, in seconds rather than minutes,
so a bug here is caught before it silently corrupts every distance
calculation downstream (drainage proximity, EBR stormwater proximity,
parcel matching, land-cover/terrain grid-sampling).

Run with:
    python -m unittest tests.unit.test_geo_utils -v
(from the geoshield/ directory)
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from common.geo_utils import (  # noqa: E402
    grid_offsets_m,
    lonlat_to_webmercator,
    min_distance_to_paths,
    min_distance_to_polygon,
    point_in_rings,
    point_to_segment_distance_m,
    webmercator_to_lonlat,
)

# Baton Rouge-ish reference point, reused across tests so results stay
# comparable and realistic (Web Mercator distortion is negligible at
# the small degree-offsets used below, but using a real mid-latitude
# point rather than lon=0/lat=0 keeps the tests representative of this
# project's actual usage).
BASE_LON, BASE_LAT = -91.182207024764, 30.449439880338


class WebMercatorRoundTripTests(unittest.TestCase):
    def test_round_trip_preserves_coordinates(self):
        x, y = lonlat_to_webmercator(BASE_LON, BASE_LAT)
        lon, lat = webmercator_to_lonlat(x, y)
        self.assertAlmostEqual(lon, BASE_LON, places=9)
        self.assertAlmostEqual(lat, BASE_LAT, places=9)

    def test_equator_prime_meridian_maps_to_origin(self):
        x, y = lonlat_to_webmercator(0.0, 0.0)
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)

    def test_east_of_base_has_larger_x(self):
        x1, _ = lonlat_to_webmercator(BASE_LON, BASE_LAT)
        x2, _ = lonlat_to_webmercator(BASE_LON + 0.01, BASE_LAT)
        self.assertGreater(x2, x1)

    def test_north_of_base_has_larger_y(self):
        _, y1 = lonlat_to_webmercator(BASE_LON, BASE_LAT)
        _, y2 = lonlat_to_webmercator(BASE_LON, BASE_LAT + 0.01)
        self.assertGreater(y2, y1)


class GridOffsetsTests(unittest.TestCase):
    def test_always_includes_center_point(self):
        offsets = grid_offsets_m(250, 125)
        self.assertIn((0.0, 0.0), offsets)

    def test_all_points_within_radius(self):
        radius_m = 250
        for dx, dy in grid_offsets_m(radius_m, 125):
            self.assertLessEqual(math.hypot(dx, dy), radius_m + 1e-9)

    def test_matches_known_verified_count(self):
        # Live-verified this session: 250m radius / 125m step produces
        # exactly 13 points (see terrain_indicators.py's own docstring
        # and multiple live regression runs this session).
        self.assertEqual(len(grid_offsets_m(250, 125)), 13)

    def test_smaller_step_produces_more_points(self):
        coarse = grid_offsets_m(250, 175)
        fine = grid_offsets_m(250, 125)
        self.assertLess(len(coarse), len(fine))


class PointToSegmentDistanceTests(unittest.TestCase):
    def test_point_on_segment_is_zero(self):
        self.assertAlmostEqual(point_to_segment_distance_m(5, 0, 0, 0, 10, 0), 0.0)

    def test_point_perpendicular_to_segment_midpoint(self):
        # Segment along the x-axis from (0,0) to (10,0); query point
        # directly above its midpoint.
        self.assertAlmostEqual(point_to_segment_distance_m(5, 3, 0, 0, 10, 0), 3.0)

    def test_point_beyond_endpoint_measures_to_nearest_endpoint(self):
        # Query point is past (10,0), off the end of the segment — the
        # nearest point on the segment is the endpoint itself, not a
        # perpendicular projection past it.
        dist = point_to_segment_distance_m(15, 0, 0, 0, 10, 0)
        self.assertAlmostEqual(dist, 5.0)

    def test_degenerate_zero_length_segment(self):
        # Both endpoints identical — should behave as plain point-to-point
        # distance rather than dividing by zero.
        self.assertAlmostEqual(point_to_segment_distance_m(3, 4, 0, 0, 0, 0), 5.0)


class MinDistanceToPathsTests(unittest.TestCase):
    def setUp(self):
        # A short path running east from BASE, in real degree coordinates
        # (as this function expects — it converts internally).
        self.path = [[BASE_LON, BASE_LAT], [BASE_LON + 0.01, BASE_LAT]]

    def test_query_point_at_a_vertex_is_near_zero(self):
        px, py = lonlat_to_webmercator(BASE_LON, BASE_LAT)
        dist = min_distance_to_paths(px, py, [self.path])
        self.assertLess(dist, 1.0)

    def test_query_point_far_away_has_large_distance(self):
        px, py = lonlat_to_webmercator(BASE_LON + 1.0, BASE_LAT + 1.0)
        dist = min_distance_to_paths(px, py, [self.path])
        self.assertGreater(dist, 50_000)

    def test_picks_nearest_of_multiple_paths(self):
        near_path = [[BASE_LON, BASE_LAT], [BASE_LON + 0.001, BASE_LAT]]
        far_path = [[BASE_LON + 1.0, BASE_LAT], [BASE_LON + 1.001, BASE_LAT]]
        px, py = lonlat_to_webmercator(BASE_LON, BASE_LAT)
        dist = min_distance_to_paths(px, py, [far_path, near_path])
        self.assertLess(dist, 200)


class PointInRingsAndPolygonDistanceTests(unittest.TestCase):
    def setUp(self):
        # A small square ring (~200m per side) centered near BASE.
        d = 0.001  # roughly 100m at this latitude
        self.square_ring = [[
            [BASE_LON - d, BASE_LAT - d],
            [BASE_LON + d, BASE_LAT - d],
            [BASE_LON + d, BASE_LAT + d],
            [BASE_LON - d, BASE_LAT + d],
            [BASE_LON - d, BASE_LAT - d],
        ]]

    def test_center_point_is_inside(self):
        px, py = lonlat_to_webmercator(BASE_LON, BASE_LAT)
        self.assertTrue(point_in_rings(px, py, self.square_ring))

    def test_far_point_is_outside(self):
        px, py = lonlat_to_webmercator(BASE_LON + 1.0, BASE_LAT + 1.0)
        self.assertFalse(point_in_rings(px, py, self.square_ring))

    def test_distance_inside_polygon_is_zero(self):
        px, py = lonlat_to_webmercator(BASE_LON, BASE_LAT)
        self.assertEqual(min_distance_to_polygon(px, py, self.square_ring), 0.0)

    def test_distance_outside_polygon_is_positive(self):
        px, py = lonlat_to_webmercator(BASE_LON + 1.0, BASE_LAT + 1.0)
        dist = min_distance_to_polygon(px, py, self.square_ring)
        self.assertGreater(dist, 50_000)


if __name__ == "__main__":
    unittest.main()
