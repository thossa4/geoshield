"""Fast, deterministic unit tests for the address-matching logic in
src/geocoding/ebr_parcel_lookup.py.

No network calls. This is the safety-critical logic behind this
session's core design decision for that module: exact point-in-parcel
intersection is unreliable (0/2 initial live test addresses matched),
so a nearby candidate parcel is only ever accepted if its own
PHYSICAL_ADDRESS field text-matches the geocoded address — getting
this matching logic wrong risks silently attributing a report to the
wrong property, so it's tested directly and thoroughly here rather
than only indirectly through the ~1-2 live addresses the regression
suite happens to cover.

Run with:
    python -m unittest tests.unit.test_address_matching -v
(from the geoshield/ directory)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from geocoding.ebr_parcel_lookup import _address_matches, _address_parts  # noqa: E402


class AddressPartsTests(unittest.TestCase):
    def test_extracts_house_number_and_street_words(self):
        num, words = _address_parts("7059 JEFFERSON HWY")
        self.assertEqual(num, "7059")
        self.assertIn("JEFFERSON", words)

    def test_short_words_excluded_from_street_words(self):
        # "HWY" is 3 letters so it's kept, but this checks that a
        # 1-2 letter token (e.g. a directional "N"/"E") wouldn't be
        # treated as a distinguishing word.
        _num, words = _address_parts("100 N MAIN ST")
        self.assertNotIn("N", words)

    def test_case_insensitive(self):
        num, words = _address_parts("750 florida st")
        self.assertEqual(num, "750")
        self.assertIn("FLORIDA", words)

    def test_empty_address_returns_none_and_empty_set(self):
        num, words = _address_parts("")
        self.assertIsNone(num)
        self.assertEqual(words, set())

    def test_non_numeric_leading_token_has_no_house_number(self):
        num, _words = _address_parts("JEFFERSON HWY")
        self.assertIsNone(num)

    def test_comma_treated_as_separator(self):
        num, words = _address_parts("7059 Jefferson Hwy, Baton Rouge, LA 70806")
        self.assertEqual(num, "7059")
        self.assertIn("JEFFERSON", words)
        self.assertIn("BATON", words)


class AddressMatchesTests(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(_address_matches("7059 JEFFERSON HWY", "7059 Jefferson Hwy, Baton Rouge, LA 70806"))

    def test_different_house_number_does_not_match(self):
        self.assertFalse(_address_matches("7054 JEFFERSON HWY", "7059 Jefferson Hwy, Baton Rouge, LA 70806"))

    def test_same_number_different_street_does_not_match(self):
        # This is the exact failure mode the "nearest parcel" approach
        # was rejected for — a numerically-close address on a
        # completely different street must not count as a match.
        self.assertFalse(_address_matches("7059 ANNABELLE AVE", "7059 Jefferson Hwy, Baton Rouge, LA 70806"))

    def test_candidate_none_does_not_match(self):
        self.assertFalse(_address_matches(None, "7059 Jefferson Hwy, Baton Rouge, LA 70806"))

    def test_candidate_missing_house_number_does_not_match(self):
        self.assertFalse(_address_matches("JEFFERSON HWY", "7059 Jefferson Hwy, Baton Rouge, LA 70806"))

    def test_geocoded_address_missing_house_number_does_not_match(self):
        self.assertFalse(_address_matches("7059 JEFFERSON HWY", "Jefferson Hwy, Baton Rouge, LA"))

    def test_matches_on_any_shared_street_word_not_full_string(self):
        # Real observed case this session: the candidate's on-file
        # address can have minor formatting differences from the
        # geocoder's matched address (e.g. an extra space) and should
        # still match as long as the house number and a real street
        # word agree.
        self.assertTrue(_address_matches("7150 JEFFERSON  HWY", "7150 Jefferson Hwy, Baton Rouge, LA 70806"))


if __name__ == "__main__":
    unittest.main()
