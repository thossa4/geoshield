"""Render one property's indicator + recommendation record into the
GeoShield Home Passport report.

Implements Phase 7 of the blueprint: "The report must make a complicated
GIS workflow understandable in less than five minutes." Uses the fixed
10-section structure from Step 7.1:

    1. Property identity
    2. Executive snapshot
    3. Flood context
    4. Wind resilience
    5. Heat/land surface
    6. Drainage context
    7. Action plan
    8. Programs/resources
    9. Data sources
    10. Disclaimer

This is the "Instant Passport" tier only (Step 7.2) — automated output,
no human review step. Deliberately does NOT compute or display any
single overall score (Phase 5, Step 5.5), and drainage context (Section
6) explicitly labels itself as mapped-feature proximity only — never a
modeled drainage grade — per the blueprint's Phase 4.4 validation gate.
Any section with genuinely unavailable data is labeled "not available"
rather than omitted silently, so a reader can see what was and wasn't
checked.

Also follows the visual-trust rules in Step 7.3 as far as a single
self-contained HTML file reasonably can: every finding shows its source
and quality flag, missing/unavailable data is shown as "not available"
rather than hidden, and the page is single-column/mobile-first.

Output is a standalone .html file with inline CSS (no external
dependencies, no JavaScript) so it opens directly in a browser or can be
printed to PDF by the user — a real PDF-generation step is a later,
separate build task (Step 6, "customer-ready PDF/web report").
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

REPORT_TEMPLATE_VERSION = "report_v0.1"

PRIORITY_ORDER = {"Now": 0, "Before purchase": 1, "Within 12 months": 2, "Monitor": 3}

QUALITY_FLAG_LABELS = {
    "A": "A — Authoritative source, property-scale, current",
    "B": "B — Authoritative, moderate spatial/temporal limitations",
    "C": "C — Area-scale proxy, not a parcel-specific conclusion",
    "D": "D — User-entered/unverified or incomplete",
    "N/A": "N/A — No reliable data available",
}


def _esc(value) -> str:
    if value is None:
        return "Not available"
    return html.escape(str(value))


def _quality_badge(flag: str | None) -> str:
    label = QUALITY_FLAG_LABELS.get(flag or "N/A", f"{flag} — unrecognized flag")
    return f'<span class="badge">{_esc(label)}</span>'


def _sorted_recommendations(recommendations: list[dict]) -> list[dict]:
    return sorted(recommendations, key=lambda r: PRIORITY_ORDER.get(r.get("priority"), 99))


def _section_property_identity(record: dict) -> str:
    return f"""
    <section id="property-identity">
      <h2>1. Property Identity</h2>
      <table class="kv">
        <tr><th>Address entered</th><td>{_esc(record.get('input_address'))}</td></tr>
        <tr><th>Matched address</th><td>{_esc(record.get('matched_address'))}</td></tr>
        <tr><th>Coordinates</th><td>{_esc(record.get('latitude'))}, {_esc(record.get('longitude'))}</td></tr>
        <tr><th>Geocode match quality</th><td>{_esc(record.get('geocode_match_quality'))} (via {_esc(record.get('geocode_provider'))})</td></tr>
        <tr><th>Property ID</th><td>{_esc(record.get('property_id'))}</td></tr>
        <tr><th>Report date</th><td>{_esc(record.get('analysis_date_utc'))}</td></tr>
        <tr><th>Report template version</th><td>{_esc(REPORT_TEMPLATE_VERSION)}</td></tr>
      </table>
      {_section_parcel_identity(record)}
      <p class="note">Every indicator elsewhere in this report is still
      queried by the single geocoded point above, not a parcel boundary
      — only the parcel identification directly above (East Baton Rouge
      Parish addresses only) uses parcel geometry. Do not assume the
      point represents an exact building footprint.</p>
    </section>
    """


def _section_parcel_identity(record: dict) -> str:
    if record.get("parcel_data_available") is not True:
        return ""
    if record.get("parcel_match_quality") == "no_confident_match":
        return """
        <p class="note"><strong>Parcel: not confidently identified.</strong>
        This point is within East Baton Rouge Parish, but no single tax
        parcel could be confidently matched — a nearby-but-unconfirmed
        parcel is deliberately not shown rather than risking attribution
        to the wrong property.</p>
        """
    return f"""
    <table class="kv">
      <tr><th>Parcel ID (assessment #)</th><td>{_esc(record.get('parcel_id'))}</td></tr>
      <tr><th>Parcel address on file</th><td>{_esc(record.get('parcel_physical_address'))}</td></tr>
      <tr><th>Subdivision</th><td>{_esc(record.get('parcel_subdivision'))}</td></tr>
      <tr><th>Parcel area</th><td>{_esc(record.get('parcel_area_sqft'))} sq ft</td></tr>
      <tr><th>Parish assessor flood zone</th><td>{_esc(record.get('parcel_flood_zone'))}</td></tr>
      <tr><th>Match quality</th><td>{_esc(record.get('parcel_match_quality'))} ({_quality_badge(record.get('parcel_quality_flag'))})</td></tr>
    </table>
    <p class="caveat">East Baton Rouge Parish tax parcel record — parcel
    identification only, not a surveyed building footprint. The parish
    assessor's flood zone above is separate from and not a substitute
    for the FEMA NFHL flood-zone finding in Section 3; the two can
    legitimately disagree.</p>
    """


def _section_executive_snapshot(record: dict) -> str:
    ratings = record.get("module_ratings") or {}
    modules = [
        ("Flood context", ratings.get("flood_context")),
        ("Wind resilience", ratings.get("wind_resilience")),
        ("Heat/surface", ratings.get("heat_surface")),
        ("Drainage context", ratings.get("drainage_context")),
    ]
    rows = "".join(
        f'<tr><td>{_esc(name)}</td>'
        f'<td>{_esc(rating.get("concern_level")) if rating else "Not available"}</td>'
        f'<td>{_esc(rating.get("confidence")) if rating else "N/A"}</td></tr>'
        for name, rating in modules
    )
    top_actions = _sorted_recommendations(record.get("recommendations", []))[:3]
    action_items = "".join(
        f'<li><strong>{_esc(a.get("priority"))}:</strong> {_esc(a.get("action"))}</li>'
        for a in top_actions
    ) or "<li>No recommendations were generated for this property.</li>"

    return f"""
    <section id="executive-snapshot">
      <h2>2. Executive Snapshot</h2>
      <p class="note">GeoShield does not compute a single overall risk
      score (blueprint Phase 5, Step 5.5). Each module below is rated
      independently — open the matching section for the specific evidence
      behind it. "Confidence" describes how complete the underlying data
      is, separate from concern level: missing data lowers confidence, it
      never silently lowers concern (Step 5.4). "Moderate concern" is the
      floor for Flood and Drainage context even with no nearby hazard
      signal — absence of a mapped flood zone or drainage feature is not
      evidence of safety.</p>
      <table class="modules">
        <tr><th>Module</th><th>Concern level</th><th>Confidence</th></tr>
        {rows}
      </table>
      <h3>Top recommended next steps</h3>
      <ol>{action_items}</ol>
    </section>
    """


def _section_flood_context(record: dict) -> str:
    return f"""
    <section id="flood-context">
      <h2>3. Flood Context</h2>
      <table class="kv">
        <tr><th>FEMA flood zone</th><td>{_esc(record.get('fema_zone'))}</td></tr>
        <tr><th>Zone subtype</th><td>{_esc(record.get('flood_zone_subtype'))}</td></tr>
        <tr><th>Special Flood Hazard Area</th><td>{_esc(record.get('special_flood_hazard_area'))}</td></tr>
        <tr><th>Mapped floodway</th><td>{_esc(record.get('floodway_flag'))}</td></tr>
        <tr><th>Base flood elevation (ft)</th><td>{_esc(record.get('base_flood_elevation_ft'))}</td></tr>
        <tr><th>Sampled ground elevation</th><td>{_esc(record.get('ground_elevation_m'))} m (USGS 3DEP, single point)</td></tr>
        <tr><th>Elevation vs. sampled neighborhood</th><td>{_esc(record.get('elevation_relative_position'))}</td></tr>
        <tr><th>Elevation percentile rank</th><td>{_esc(record.get('elevation_percentile_rank'))}</td></tr>
        <tr><th>Data quality</th><td>{_quality_badge(record.get('flood_quality_flag'))}</td></tr>
      </table>
      <p class="caveat">Zone is FEMA map context, not total flood risk.
      FEMA maps do not capture every flood source or future conditions.
      Sampled elevation is not a surveyed finished-floor elevation. The
      percentile rank compares this point to ~13-21 other points
      grid-sampled within 250m — a discrete-grid approximation, not an
      independently defined neighborhood or drainage boundary.</p>
    </section>
    """


def _section_wind_resilience(record: dict) -> str:
    attrs = record.get("building_attributes") or {}
    return f"""
    <section id="wind-resilience">
      <h2>4. Wind Resilience</h2>
      <table class="kv">
        <tr><th>Hurricane risk (FEMA NRI, census tract)</th><td>{_esc(record.get('hurricane_risk_rating'))} (score {_esc(record.get('hurricane_risk_score'))}/100)</td></tr>
        <tr><th>Strong wind risk (FEMA NRI, census tract)</th><td>{_esc(record.get('strong_wind_risk_rating'))} (score {_esc(record.get('strong_wind_risk_score'))}/100)</td></tr>
        <tr><th>Data quality (regional context)</th><td>{_quality_badge(record.get('wind_hazard_quality_flag'))}</td></tr>
        <tr><th>Roof age (user-entered, unverified)</th><td>{_esc(attrs.get('roof_age'))}</td></tr>
        <tr><th>FORTIFIED status (user-entered, unverified)</th><td>{_esc(attrs.get('fortified_status'))}</td></tr>
        <tr><th>Shutters / opening protection (user-entered, unverified)</th><td>{_esc(attrs.get('shutters_status'))}</td></tr>
      </table>
      <p class="caveat">Hurricane/strong-wind ratings are FEMA National
      Risk Index census-tract-level context — every address in the same
      tract shares this value. It is not a wind-speed design value and
      does not reflect this specific building's roof, construction, or
      FORTIFIED status; building vulnerability cannot be inferred from
      an area map alone.</p>
    </section>
    """


def _section_heat_landsurface(record: dict) -> str:
    return f"""
    <section id="heat-land-surface">
      <h2>5. Heat / Land Surface</h2>
      <table class="kv">
        <tr><th>NLCD land-cover class (at point)</th><td>{_esc(record.get('land_cover_class_label'))} (code {_esc(record.get('land_cover_class_code'))})</td></tr>
        <tr><th>Impervious surface (single pixel)</th><td>{_esc(record.get('impervious_pct_pixel'))}%</td></tr>
        <tr><th>Tree canopy cover (single pixel)</th><td>{_esc(record.get('tree_canopy_pct_pixel'))}%</td></tr>
        <tr><th>Impervious surface (250m buffer mean)</th><td>{_esc(record.get('impervious_pct_buffer_250m'))}%</td></tr>
        <tr><th>Tree canopy cover (250m buffer mean)</th><td>{_esc(record.get('tree_canopy_pct_buffer_250m'))}%</td></tr>
        <tr><th>Data quality (buffer estimate)</th><td>{_quality_badge(record.get('landcover_buffer_quality_flag'))}</td></tr>
        <tr><th>Annual mean daily high (NOAA normals, 1991-2020)</th><td>{_esc(record.get('annual_mean_max_temp_f'))}°F</td></tr>
        <tr><th>Hottest month (NOAA normals)</th><td>{_esc(record.get('hottest_month'))} — {_esc(record.get('hottest_month_max_temp_f'))}°F average high</td></tr>
        <tr><th>Annual cooling degree days</th><td>{_esc(record.get('annual_cooling_degree_days'))}</td></tr>
        <tr><th>Data quality (climate)</th><td>{_quality_badge(record.get('climate_quality_flag'))}</td></tr>
      </table>
      <p class="caveat">Single-pixel values are one 30-meter NLCD cell
      at this exact point. Buffer-mean values grid-sample multiple
      points across a 250m radius and average them — a discrete-grid
      approximation of a neighborhood statistic, not a true
      pixel-weighted zonal calculation. Climate figures are 1991-2020
      normals from the nearest NOAA weather station, not a measurement
      at this exact address and not this year's actual or forecast
      weather.</p>
    </section>
    """


def _section_drainage_context(record: dict) -> str:
    if record.get("drainage_data_available") is not True:
        return """
        <section id="drainage-context">
          <h2>6. Drainage Context</h2>
          <p class="note"><strong>Not available.</strong> GeoShield could
          not retrieve mapped water/drainage-feature data for this
          property.</p>
        </section>
        """
    return f"""
    <section id="drainage-context">
      <h2>6. Drainage Context</h2>
      <table class="kv">
        <tr><th>Nearest mapped stream/river</th><td>{_esc(record.get('nearest_stream_or_river_m'))} m</td></tr>
        <tr><th>Nearest mapped canal/ditch</th><td>{_esc(record.get('nearest_canal_or_ditch_m'))} m</td></tr>
        <tr><th>Nearest mapped waterbody</th><td>{_esc(record.get('nearest_waterbody_m'))} m</td></tr>
        <tr><th>Nearest mapped levee</th><td>{_esc(record.get('nearest_levee_m'))} m</td></tr>
        <tr><th>Data quality</th><td>{_quality_badge(record.get('drainage_quality_flag'))}</td></tr>
      </table>
      <p class="note"><strong>No parcel-level drainage grade is shown.</strong>
      The blueprint (Phase 4.4) explicitly requires validating any
      modeled surface-water accumulation or drainage-performance finding
      against observed local events and high-resolution terrain before
      it is published — this has not been done, so the figures above are
      proximity to <em>mapped</em> features only, not a drainage
      assessment.</p>
      <p class="caveat">Distances are to features recorded in the USGS
      National Hydrography Dataset. Many small or local drainage ditches
      are not captured in this national dataset, so no nearby feature
      shown above is not evidence of good drainage.</p>
      {_section_ebr_local_drainage(record)}
    </section>
    """


def _section_ebr_local_drainage(record: dict) -> str:
    if record.get("ebr_drainage_data_available") is not True:
        return ""
    return f"""
    <h3>East Baton Rouge Parish local infrastructure</h3>
    <p class="note">The figures below are from East Baton Rouge Parish's
    own GIS records, not the national dataset above — shown only for
    addresses within East Baton Rouge Parish.</p>
    <table class="kv">
      <tr><th>Nearest municipal stormwater pipe/ditch</th><td>{_esc(record.get('nearest_stormwater_pipe_m'))} m</td></tr>
      <tr><th>Nearest catch basin/structure</th><td>{_esc(record.get('nearest_stormwater_structure_m'))} m</td></tr>
      <tr><th>Drainage district</th><td>{_esc(record.get('drainage_district_name'))}</td></tr>
      <tr><th>Data quality</th><td>{_quality_badge(record.get('ebr_drainage_quality_flag'))}</td></tr>
    </table>
    <p class="caveat">Parish asset-inventory locations only, not a
    capacity or flow-performance model.</p>
    """


def _section_action_plan(record: dict) -> str:
    recs = _sorted_recommendations(record.get("recommendations", []))
    if not recs:
        rows = '<tr><td colspan="5">No recommendations were generated for this property.</td></tr>'
    else:
        rows = "".join(
            f"<tr><td>{_esc(r.get('priority'))}</td>"
            f"<td>{_esc(r.get('action_class'))}</td>"
            f"<td>{_esc(r.get('action'))}</td>"
            f"<td>{_esc(r.get('cost_band'))}</td>"
            f"<td>{_esc(r.get('provider_type'))}</td>"
            f"<td>{_esc(r.get('confidence'))}</td></tr>"
            for r in recs
        )
    return f"""
    <section id="action-plan">
      <h2>7. Action Plan</h2>
      <table class="actions">
        <tr><th>Priority</th><th>Category</th><th>Action</th><th>Cost band</th><th>Provider type</th><th>Confidence</th></tr>
        {rows}
      </table>
      <p class="note">Ruleset version: {_esc(recs[0].get('ruleset_version')) if recs else 'n/a'}.
      Recommendations are generated by deterministic, versioned rules
      (Phase 6) — not by a machine-learning model, and not by GeoShield
      inferring facts it was not given.</p>
    </section>
    """


def _section_programs(record: dict) -> str:
    program_links = list(dict.fromkeys(
        r.get("program_link") for r in record.get("recommendations", []) if r.get("program_link")
    ))
    if not program_links:
        body = "<p>No program references were generated for this property.</p>"
    else:
        items = "".join(f"<li>{_esc(link)}</li>" for link in program_links)
        body = f"<ul>{items}</ul>"
    return f"""
    <section id="programs-resources">
      <h2>8. Programs / Resources</h2>
      {body}
      <p class="caveat">Program eligibility, funding rounds, and
      requirements change. Treat every item above as something to
      verify on the official program page, not a guaranteed benefit.</p>
    </section>
    """


def _section_data_sources(record: dict) -> str:
    sources = []
    for key in ("_full_parcel_response", "_full_flood_response", "_full_terrain_response", "_full_landcover_response", "_full_drainage_response", "_full_ebr_drainage_response"):
        resp = record.get(key)
        if resp:
            sources.append(resp)
    rows = "".join(
        f"<tr><td>{_esc(s.get('source_id'))}</td>"
        f"<td>{_esc(s.get('checked_at_utc'))}</td>"
        f"<td>{_quality_badge(s.get('quality_flag'))}</td>"
        f"<td>{_esc(s.get('customer_caveat') or s.get('note'))}</td></tr>"
        for s in sources
    ) or '<tr><td colspan="4">No sources were queried.</td></tr>'
    return f"""
    <section id="data-sources">
      <h2>9. Data Sources</h2>
      <table class="sources">
        <tr><th>Source</th><th>Checked (UTC)</th><th>Quality</th><th>Caveat</th></tr>
        {rows}
      </table>
      <p class="note">See <code>docs/data_registry.csv</code> in this
      repository for full source metadata (provider, URL, license,
      refresh frequency).</p>
    </section>
    """


def _section_disclaimer() -> str:
    return """
    <section id="disclaimer">
      <h2>10. Disclaimer</h2>
      <p>GeoShield Home Passport is an informational
      resilience-screening and decision-support product. It is not an
      official flood determination, elevation certificate, survey,
      engineering inspection, home inspection, appraisal, environmental
      assessment, insurance quote, or guarantee of future loss. Findings
      reflect publicly available and user-submitted data as of the
      report date shown and may not reflect current conditions.</p>
      <p>Where GeoShield identifies a concern or recommends an action,
      it is directing you toward verification by an appropriately
      licensed or qualified professional — not substituting for that
      professional's judgment. See <code>docs/disclaimer.md</code> for
      the full draft disclaimer (pending counsel review).</p>
    </section>
    """


CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 1rem; line-height: 1.5; }
h1 { font-size: 1.4rem; }
h2 { font-size: 1.15rem; border-bottom: 1px solid #8884; padding-bottom: .25rem; margin-top: 2rem; }
h3 { font-size: 1rem; }
table { width: 100%; border-collapse: collapse; margin: .5rem 0 1rem; font-size: .92rem; }
table.kv th { text-align: left; width: 45%; vertical-align: top; padding: .35rem .5rem; }
table.kv td { padding: .35rem .5rem; }
table.modules th, table.modules td, table.actions th, table.actions td, table.sources th, table.sources td { border: 1px solid #8884; padding: .4rem .5rem; text-align: left; vertical-align: top; }
.badge { display: inline-block; font-size: .8rem; padding: .1rem .4rem; border: 1px solid #8884; border-radius: .3rem; }
.note { font-size: .9rem; opacity: .85; }
.caveat { font-size: .85rem; opacity: .75; font-style: italic; }
section { margin-bottom: 1rem; }
code { font-size: .85em; }
"""


def generate_report_html(record: dict) -> str:
    title = f"GeoShield Home Passport — {html.escape(str(record.get('matched_address') or record.get('input_address') or 'Unknown address'))}"
    body = "\n".join([
        f"<h1>{title}</h1>",
        _section_property_identity(record),
        _section_executive_snapshot(record),
        _section_flood_context(record),
        _section_wind_resilience(record),
        _section_heat_landsurface(record),
        _section_drainage_context(record),
        _section_action_plan(record),
        _section_programs(record),
        _section_data_sources(record),
        _section_disclaimer(),
    ])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""


def write_report(record: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{record.get('property_id', 'unknown')}.html"
    out_path.write_text(generate_report_html(record), encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a GeoShield Home Passport HTML report from an indicator record.")
    parser.add_argument("record_file", help="Path to a JSON indicator record (from run_one_address.py), or - for stdin")
    parser.add_argument("--out-dir", default=None, help="Output directory (default: ../reports relative to this script)")
    args = parser.parse_args()

    source = sys.stdin if args.record_file == "-" else open(args.record_file, encoding="utf-8")
    with source:
        record = json.load(source)

    out_dir = Path(args.out_dir) if args.out_dir else Path(__file__).resolve().parents[2] / "reports"
    path = write_report(record, out_dir)
    print(f"Wrote {path}", file=sys.stderr)
    print(str(path))


if __name__ == "__main__":
    main()
