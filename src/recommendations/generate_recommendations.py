"""CLI wrapper for the recommendation rules engine.

Matches the script role named ``09_recommendations.py`` in Phase 8.4 of
the GeoShield blueprint: "Generate action objects from deterministic
rules." Reads an indicator record (the JSON shape produced by
run_one_address.py) from a file or stdin, and prints the recommendation
list as JSON.

Usage:
    python run_one_address.py "750 Florida St, Baton Rouge, LA 70801" > /tmp/rec.json
    python -m recommendations.generate_recommendations /tmp/rec.json

    # or pipe directly:
    python run_one_address.py "..." | python -m recommendations.generate_recommendations -
"""

from __future__ import annotations

import json
import sys

from .rules_engine import generate_recommendations


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <indicator_record.json | ->", file=sys.stderr)
        raise SystemExit(2)

    source = sys.stdin if sys.argv[1] == "-" else open(sys.argv[1], encoding="utf-8")
    with source:
        record = json.load(source)

    building_attributes = record.get("building_attributes")
    recs = generate_recommendations(record, building_attributes)
    print(json.dumps(recs, indent=2))


if __name__ == "__main__":
    main()
