# Module Concern Ratings — Methodology (module_ratings_v0.1)

Implements Phase 5, Step 5.3's last checklist item: "Publish a
methodology summary." Read this alongside `src/scoring/module_ratings.py`,
which is the actual source of truth — this document explains it, it
doesn't define new behavior.

## What this is

Four independent per-module ratings — Flood Context, Wind Resilience,
Heat/Surface, Drainage Context — each a `concern_level` (`Insufficient
data` / `Low concern` / `Moderate concern` / `Elevated concern` / `High
concern`) plus a separate `confidence` (`N/A` / `Low` / `Medium` /
`High`), per Step 5.1 and Step 5.4.

Every threshold is the same threshold already used in
`src/recommendations/rules_engine.py`'s escalation rules — nothing here
was invented independently. If a property's Drainage Context rating says
"Elevated concern," there is always a corresponding recommendation in
the action plan citing the same evidence, and vice versa.

Confidence reflects data completeness, not the concern level itself
(Step 5.4): a module with genuinely missing source data returns
`Insufficient data` / `N/A` rather than defaulting to a false "Low
concern." Flood Context and Drainage Context specifically never return
`Low concern` — even with no nearby hazard signal, the floor is
`Moderate concern`, because the absence of a mapped flood zone or a
nearby mapped drainage feature is explicitly not evidence of safety
(the same caution already stated in `FLOOD_ZONE_X_CONTEXT`'s and
`DRAINAGE_NO_MAPPED_FEATURE_NEARBY`'s recommendation text).

## What this deliberately is NOT

- **Not a single overall score.** Step 5.5: "avoid a single overall
  score until users prove they need one." The four ratings are never
  combined, averaged, or blended into one number anywhere in this
  codebase.
- **Not weighted or sensitivity-tested (Step 5.3, incomplete).** The
  blueprint's Step 5.3 calls for starting with "expert-informed
  provisional weights," running sensitivity analysis (does changing each
  weight change rankings materially?), and comparing scores against known
  historical cases. None of that has been done, and it can't be done
  honestly without real observed loss/damage data this prototype does
  not have — inventing weights and presenting them as validated would be
  exactly the "false precision" Step 5.5 warns a single score risks. This
  is a known, explicit gap, not an oversight.
- **Not cross-module.** Each rating is computed entirely from that one
  module's own indicators. A property's Flood Context rating is never
  influenced by its Heat/Surface indicators, or vice versa.
- **Not normalized to a common 0–100 scale.** Step 5.2 warns against
  "mixing incomparable measures merely because they can be normalized."
  Each module uses its own domain-appropriate thresholds (percentiles,
  distance-in-meters, percent-cover, °F) rather than a shared numeric
  range.

## Per-module logic (see `src/scoring/module_ratings.py` for the exact code)

| Module | High concern | Elevated concern | Moderate concern | Low concern |
|---|---|---|---|---|
| Flood Context | Floodway, or SFHA + bottom-quartile relative elevation | SFHA alone | Zone X / no SFHA | *(never — see above)* |
| Wind Resilience | "Very High" regional hurricane rating, no FORTIFIED doc | "Relatively High"/"Very High" regional rating, no FORTIFIED doc | No FORTIFIED doc, lower regional rating | FORTIFIED documentation on file |
| Heat/Surface | High impervious + low canopy + hot climate, all three | Any two of those three signals | Exactly one signal | None of the signals |
| Drainage Context | Within 100m of mapped water/drainage AND bottom-quartile elevation | Within 100m of mapped water, 300m of a levee, or 50m of EBR local stormwater infrastructure | Nothing within those distances | *(never — see above)* |

## Version history

- `module_ratings_v0.1` (2026-08-21): initial release, covering the 4
  modules live at that date (flood, terrain-derived elevation, land
  cover, climate, wind, national + East Baton Rouge Parish local
  drainage). Bump this version whenever a threshold changes, per the
  same "never recompute an old report silently" rule
  `RULESET_VERSION` already follows.
