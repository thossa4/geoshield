# GeoShield MVP Backlog (v0.1 draft)

Status: draft, per Phase 0 deliverables table ("MVP backlog: must-have /
later / explicitly excluded feature list"). Reorganize as real backlog
items (issues/tickets) once a tracker is chosen.

## Must-have (Version 1 / MVP)

- Address geocoding with match-confidence and map-pin confirmation
  (Phase 3, Step 3.1).
- FEMA flood-zone context lookup against the effective NFHL (Phase 4.1).
- Terrain/elevation context from USGS 3DEP, reported as relative
  position in plain language (Phase 4.1.2).
- Impervious-cover and distance-to-water proxies (Phase 4.1.3).
- Wind/hurricane resilience questionnaire + rules-based action engine
  (Phase 4.2).
- Heat/land-cover indicators (tree canopy, impervious %, NOAA climate
  context) (Phase 4.3).
- Quality/confidence flag (A/B/C/D/N/A) on every indicator (Phase 3,
  Step 3.4).
- Deterministic, versioned recommendation rules (Phase 6, Step 6.2).
- Instant Passport report (fixed 10-section structure, Phase 7, Step
  7.1) as PDF/web output.
- Data Source Registry with owner, URL, refresh cycle, license, caveat
  per source (Phase 2).
- Landing page with email capture and role-based CTAs (Homeowner / Buyer
  / Realtor / Property Manager) (Phase 1, Step 1.3).

## Later (post-MVP, only after validation)

- Reviewed Passport tier with human GIS/QA review (Phase 7, Step 7.2).
- Drainage/surface-water accumulation modeling — only after local
  validation against observed events (Phase 4.4).
- Contractor/professional marketplace and lead flow (Phase 10).
- B2B subscription / portfolio dashboard for realtors and property
  managers (Phase 11, Step 11.1).
- Batch/portfolio and municipal analytics product (Phase 11, Step 11.1).
- Public methodology page and sensitivity-tested scoring weights (Phase
  5, Step 5.3).
- Data-refresh monitoring/alerting jobs (Phase 20, Months 4–6).

## Explicitly excluded (not on any near-term roadmap)

- A single overall "GeoShield Score" (Phase 5, Step 5.5) — module-level
  ratings only, unless users prove they need a composite number.
- Insurance premium prediction (Phase 0, Step 0.3).
- Any binary "safe/unsafe" label (Phase 0, Step 0.3).
- Contractor pay-to-rank or any mechanism letting advertisers change a
  risk rating (Phase 10, Step 10.4; Phase 17 governance rule).
- Mortgage/insurance ecosystem integration before dedicated legal/
  regulatory review (Phase 15, Step 15.2).
