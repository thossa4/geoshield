# GeoShield Home Passport — Product Specification (v0.1 draft)

Status: **Draft for founder/GIS-lead/counsel review — not approved.**
Source: Phase 0, Step 0.1–0.2 and the Phase 0 deliverables table of the
GeoShield blueprint.

## One-sentence promise (Step 0.1)

> GeoShield helps you understand property resilience concerns around an
> address, see the evidence behind them, and identify practical next
> actions.

This is decision-support language. Never restate the promise as certainty
("GeoShield tells you if your home will flood").

## Audience

- Homeowners and homebuyers in Louisiana (primary consumer).
- Realtors and home inspectors (first B2B channel).
- Property managers / small landlords managing multiple addresses (B2B,
  later).

## Inputs

- Street address (required), geocoded to lat/long and, where available,
  parcel ID.
- Optional user-supplied building attributes: roof age, roof type,
  FORTIFIED status, shutters/opening protection, year built. These are
  always stored and displayed as **user-entered/unverified** unless
  independently verified.
- Purpose flag (buying / own / selling / managing) — personalizes wording
  only, never the underlying score.

## Outputs (Version 1 scope — Step 0.2)

- [ ] Flood-hazard map context and flood-zone information from current
      FEMA sources where available.
- [ ] Elevation and terrain context using the best available USGS
      elevation data for the location.
- [ ] Proximity/context indicators for water, coast, major drainage
      features, and imperviousness where appropriate.
- [ ] Wind/hurricane-resilience questions using user-entered
      roof/building attributes plus public hazard context.
- [ ] Heat/land-cover indicators such as tree canopy/impervious cover and
      climate context.
- [ ] A prioritized mitigation checklist linked to professional services,
      grants/programs, and credible guidance.
- [ ] A traceable source/date/caveat panel for every major finding.

Report structure follows Phase 7, Step 7.1 (10 fixed sections: property
identity, executive snapshot, flood context, wind resilience, heat/land
surface, drainage context, action plan, programs/resources, data sources,
disclaimer).

## Explicitly excluded from Version 1 (Step 0.3)

- No guarantee that a property will or will not flood.
- No replacement for an elevation certificate, survey, engineering
  inspection, home inspection, appraisal, environmental assessment,
  insurance quote, or official flood determination.
- No "safe/unsafe" binary label based on coarse regional data.
- No insurance premium prediction unless later built with appropriate
  regulatory and actuarial expertise.
- No contractor quality guarantee; verification and marketplace terms
  must be explicit.
- No single overall "GeoShield Score" until module-level ratings prove
  users need one (Phase 5, Step 5.5).

## Report tiers (Phase 7, Step 7.2)

| Tier | Contents | Purpose |
|---|---|---|
| Instant Passport | Automated authoritative-data screening + action list. | Low-friction consumer purchase / lead generation. |
| Reviewed Passport | Automated report plus human GIS/quality review and optional professional-data inputs. | Higher-price product for homebuyers, realtors, property managers. |

## Response time

Target processing budget per the Phase 16 operations timeline: address
confirmation (0 min) → geocode/parcel (0–1 min) → indicator calculation
(1–3 min) → QA checks (3–4 min) → scoring/recommendations (4–5 min) →
report generation (5–6 min). Reviewed-tier reports additionally route to
an analyst and will take longer; exact SLA to be set once the pipeline is
built and timed.

## Product-language rule

Use "screening indicator," "context," "relative concern," and
"recommended next step." Avoid language such as "your home will flood,"
"structurally safe," or "guaranteed low risk." See `claims_matrix.md`
before any marketing copy is published.

## Open items before this spec can be marked approved

- Founder/product lead sign-off on scope.
- GIS/science lead sign-off on which indicators are technically
  achievable with currently accessible data.
- Counsel review of claims and exclusions (Phase 12, Step 12.1).
