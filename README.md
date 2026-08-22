# GeoShield Home Passport

Property-level resilience screening platform. A homeowner, buyer, realtor,
landlord, or property manager enters an address; GeoShield assembles
authoritative hazard, terrain, land-cover, climate, and neighborhood data,
calculates transparent screening indicators, translates them into
plain-language findings, and recommends practical mitigation actions.

Pilot geography: Louisiana (Greater Baton Rouge + coastal Louisiana).

This repository implements the blueprint in
`../GeoShield_Home_Passport_Step_by_Step_Business_and_GIS_Blueprint.docx`.
Current status: **Phase 0 docs done; a real, working geocode → flood →
terrain → land-cover → wind → climate → drainage-proximity → per-module
concern ratings → recommendations → report pipeline exists for one
address at a time (Phase C prototype + Phase 5 module ratings + Phase 6
rules engine + Phase 7 Instant Passport report).** No single overall
score (deliberate, see Phase 5 below), no modeled drainage/surface-water
performance (deliberately deferred — see Phase 4.4 below), no
customer-facing app.

## Status against the blueprint

| Phase | Status |
|---|---|
| 0 — Define exactly what GeoShield is | Drafted (`docs/product_spec.md`, `docs/claims_matrix.md`, `docs/disclaimer.md`, `docs/mvp_backlog.md`) — needs founder/counsel review |
| 1 — Validate the problem | Not started (requires real customer interviews) |
| 2 — Data governance / source registry | `docs/data_registry.csv` — all 10 rows live-verified (no `TODO`s) and wired into working modules: FEMA NFHL, FEMA NRI, USGS 3DEP, USGS NLCD, NOAA NCEI, USGS NHD, the East Baton Rouge Parish GIS stormwater + parcel datasets, and (as of 2026-08-22) Census ACS as an optional, explicitly non-hazard "Neighborhood Context" subsection (requires `CENSUS_API_KEY`; `claims_matrix.md` row 9 covers this claim); LA Fortify Homes and LA GOHSEP are verified-live program pages, not indicator data |
| 3 — Geocoding | Working: `src/geocoding/geocode_address.py` (US Census Geocoder, live). Step 3.2 parcel-geometry lookup also working for East Baton Rouge Parish: `src/geocoding/ebr_parcel_lookup.py` resolves a point to its tax parcel — verified live (a clean test address matched parcel 008-6736-5 correctly). Real finding: exact point-in-parcel intersection is unreliable (0/2 initial addresses matched exactly), so a spatially-nearest parcel is deliberately never guessed — only an exact hit or an address-text-confirmed match counts, else the report honestly says "not confidently identified." Owner/financial fields are deliberately never fetched from the parcel source (real PII exists in that schema). |
| 4.1 — Flood context module | Working (zone + subtype + floodway flag + SFHA + effective date): `src/indicators/flood_indicators.py` (FEMA NFHL, live) |
| 4.1 — Terrain module | Working: `src/indicators/terrain_indicators.py` gets point elevation plus a 250m grid-sampled neighborhood elevation percentile (USGS 3DEP EPQS, live, both verified across 3 real addresses including a genuinely low-lying point that correctly ranked in the bottom decile); percentile is a discrete-grid approximation, not a true zonal statistic |
| 4.3 — Heat/land-cover module | Working: `src/indicators/landcover_indicators.py` gets NLCD class + impervious % + tree canopy % at both a single 30m pixel and a 250m grid-sampled buffer mean (MRLC WMS, live, both verified); buffer mean is a discrete-grid approximation, not a true zonal statistic. `src/indicators/climate_indicators.py` adds NOAA NCEI 1991-2020 climate normals (hottest month, annual cooling degree days) from the nearest weather station — verified live at 2 real Louisiana points with a physically sensible coastal-vs-inland contrast; a real robustness gap (nearest station often has no temperature data) was found and fixed with a 12-candidate fallback |
| 4.2 — Wind module | Working: `src/indicators/wind_indicators.py` gets census-tract-level hurricane and strong-wind risk ratings from FEMA's National Risk Index (live, verified at 4 real points across LA/TX/CO with physically sensible geographic variation), combined with the roof-age/FORTIFIED/shutters rules from Step 4.2.2's table; regional risk can escalate the FORTIFIED recommendation's priority but never infers a building attribute from area data |
| 4.4 — Drainage module | Working (mapped-feature proximity only, no modeled drainage grade): `src/indicators/drainage_indicators.py` gets distance to the nearest mapped stream/river, canal/ditch, waterbody, and levee from USGS NHD (live, verified at all 3 reference addresses — Lakeview correctly found the 17th Street Canal + a levee 92.6m away, Gentilly correctly found the London Avenue Outfall Canal + a levee, both the actual 2005-breach sites). `src/indicators/ebr_local_drainage_indicators.py` adds East Baton Rouge Parish's own municipal stormwater pipe/catch-basin inventory and drainage district — live-verified at the Baton Rouge reference point (a real pipe 8.4m away, catch basin 8.6m away, "Gravity Drainage District #1"), and correctly reports itself not-applicable (not an error) for both New Orleans reference points, since they're outside the parish. Flow-accumulation/depression modeling and any drainage grade remain deliberately deferred pending local validation per the blueprint |
| 5 — Scoring | Working, scoped exactly to what the blueprint asks for: `src/scoring/module_ratings.py` gives 4 independent per-module concern ratings (Flood/Wind/Heat/Drainage) with confidence shown separately (Step 5.1/5.4), no single overall score (Step 5.5) — verified live at all 3 reference addresses, internally consistent with the matching `rules_engine.py` rule firings. Step 5.3's weighting/sensitivity-testing/historical-case comparison is a documented, deliberate gap (needs real loss/damage data this prototype doesn't have) — see `docs/methodology_scoring.md` |
| 6 — Recommendation engine | Working: `src/recommendations/rules_engine.py` — deterministic, versioned (`recommendations_v0.7`) rules covering flood/terrain/elevation-percentile/land-cover/wind/climate/drainage-proximity/local-stormwater findings, output matches Step 6.3's schema (priority/cost_band/evidence/confidence/provider_type/program_link); includes escalation rules for (a) bottom-quartile relative elevation inside a Special Flood Hazard Area, (b) no FORTIFIED documentation in a "Relatively High"/"Very High" regional hurricane-risk area, and (c) low relative elevation near a mapped water/drainage feature — all verified against real addresses with differential (escalates-vs-doesn't) testing |
| 7 — Home Passport report | Working (Instant Passport tier only, `report_v0.1`): `src/reporting/report_generator.py` renders the fixed 10-section report (Step 7.1) as a self-contained HTML file; any section with genuinely unavailable data is explicitly labeled "not available" rather than omitted |
| 8 — Full GIS prototype (ArcGIS Pro project) | Not started |
| 9+ — Production architecture, marketplace, legal, pilot, launch | Not started |

### Try it

```
cd geoshield/src
python run_one_address.py "750 Florida St, Baton Rouge, LA 70801" --roof-age 12 --fortified unknown --shutters unknown --report
```

Geocodes the address, queries FEMA NFHL, USGS elevation, NLCD land-cover,
FEMA NRI wind context, NOAA climate normals, USGS NHD + East Baton Rouge
Parish local drainage data for the point, computes 4 per-module concern
ratings, runs the recommendation rules engine, prints the full record
(indicators + module ratings + recommendations) as JSON, and appends
rows to `data/processed/property_indicators.csv` and
`data/processed/recommendations.csv`. `--roof-age`/`--fortified`/
`--shutters` are optional and default to "unknown," which triggers the
corresponding verify-this recommendations. Add `--report` to also render
the full Home Passport HTML report to `reports/{property_id}.html`
(open it directly in a browser). No single overall score is computed —
see `docs/methodology_scoring.md` and Phase 5's "avoid a single overall
score" rule.

### Run the regression tests

```
cd geoshield
python -m unittest tests.regression.test_reference_properties -v
```

Runs the live pipeline (real network calls to FEMA/USGS/Census, no
mocking) against three real reference addresses recorded in
`tests/reference_properties/properties.py`: a Zone X property in
Baton Rouge, a moderate-relative-elevation SFHA property in Lakeview
(New Orleans), and a notably-low-relative-elevation SFHA property in
Gentilly (New Orleans) that exercises the
`TERRAIN_LOW_RELATIVE_ELEVATION_IN_SFHA` escalation rule. Takes roughly
45-60 seconds; a failure can mean either a real regression or a
transient upstream outage — check which before assuming the code broke.

## Folder structure

```
geoshield/
  README.md
  docs/               product_spec.md, methodology.md, claims_matrix.md, data_registry.csv
  data/                raw/  processed/  cache/
  gis/                 ArcGIS Pro project + geodatabases (not created yet)
  src/                 etl/  geocoding/  indicators/  scoring/  recommendations/  reporting/  qa/
  tests/               unit/  regression/  reference_properties/
  web/                 front-end app (not started)
  api/                 backend API (not started)
  infra/               deployment/infra config (not started)
  reports/templates/   report template(s) (not started)
  notebooks/research_only/
```

## Important

GeoShield is an **informational resilience-screening and decision-support
product**, not an official flood determination, engineering inspection,
appraisal, insurance underwriting tool, or guarantee of future loss. See
`docs/disclaimer.md` and `docs/claims_matrix.md` before writing any
marketing copy or UI text.

## License

All rights reserved. This repository has no open-source license — the
code, data-source integrations, and rules/recommendation logic are
proprietary. Viewing is fine; reuse, redistribution, or derivative works
are not permitted without the owner's explicit written permission.
