# GeoShield Claims Matrix (v0.1 draft)

Status: **Draft — every marketing/UI claim must be checked against this
table before publication (Phase 12, Step 12.2).** Add a row before making
any new claim; do not let marketing or sales language outrun the
technical report.

| # | Claim (customer-facing language) | Evidence / data that supports it | What it must NOT imply | Reviewed by / date |
|---|---|---|---|---|
| 1 | "See flood-map context for this address." | FEMA National Flood Hazard Layer effective zone at the geocoded point/parcel, with map effective date shown. | Does not imply total flood risk or a guarantee the property will/won't flood; FEMA maps don't capture every flood source or future conditions. | — |
| 2 | "Understand this property's terrain and relative elevation." | USGS 3DEP bare-earth DEM sampled at/near the parcel; percentile vs. a documented neighborhood reference geography. | Not a surveyed finished-floor elevation; not an engineering elevation certificate. | — |
| 3 | "See tree canopy and impervious-surface context." | USGS Annual NLCD land-cover statistics in defined buffers around the property. | Raster resolution limits parcel-scale precision; not a parcel-specific drainage grade. | — |
| 4 | "Get wind/hurricane-resilience questions relevant to this home." | Regional wind/hurricane hazard context (authoritative source) + user-entered roof/building attributes. | Building vulnerability cannot be inferred from a map alone; unverified user data must be labeled as such. | — |
| 5 | "See heat and climate context for the area." | NOAA NCEI historical climate normals/extremes; NLCD tree/impervious context. | Station/grid data are not building-level or indoor-temperature measurements. | — |
| 6 | "Get a prioritized action plan." | Deterministic, versioned recommendation rules (Phase 6) triggered by specific findings; each action tagged with evidence, priority, cost band, confidence. | Recommendations are not a substitute for a licensed professional's inspection or judgment. | — |
| 7 | "Connect with a verified professional." | Provider passed the verification checklist in Phase 10, Step 10.2 (license, insurance, service area, agreement to standards). | "Verified" describes documentation on file, not a guarantee of work quality; providers cannot pay to alter GeoShield scores. | — |
| 8 | "A state/federal program may be worth checking." | Rules-based flag referencing an official, currently-linked program page with a last-checked date. | Not an eligibility determination or award guarantee. | — |

## Rules for adding a claim

1. Every claim must cite the specific data source(s) and quality/confidence
   flag (Phase 3, Step 3.4: A/B/C/D/N/A) it relies on.
2. If a claim cannot point to an existing indicator in
   `data_registry.csv`, it cannot ship.
3. Claims about scores/ratings must distinguish concern level from
   confidence level (Phase 5, Step 5.4) — never collapse "we don't have
   data" into "low risk."
4. Counsel reviews any claim that touches flood determination, insurance,
   inspection, appraisal, or program eligibility before it goes live
   (Phase 12, Step 12.1–12.2).
