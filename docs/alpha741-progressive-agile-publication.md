# KEMS 0.7.0-alpha7.41 — progressive Agile price publication

Alpha7.41 removes the remaining all-or-nothing behaviour while Octopus Agile Outgoing prices are still being published.

## Behaviour

KEMS uses every real price it currently has. Missing settlement periods remain explicitly **unknown**; KEMS never substitutes zero, an average, a previous-day value, or an assumed high/low price.

For a live incomplete horizon, the existing Alpha7.26/Alpha7.28 bounded-partial planner remains authoritative. Deliberate battery export is allowed only when:

- the current half-hour has a real Agile export price;
- the broad Octopus price request itself succeeded;
- any missing periods are accounted for as still-unpublished future prices rather than retrieval errors;
- the full discharge opportunity of the unknown periods remains reserved; and
- the existing inverter, export, battery, reserve, freshness and independent shadow-safety checks pass.

A retrieval error still keeps the original full price-horizon hold. An unknown current price still blocks deliberate export in that current half-hour.

## Tomorrow planning

Tomorrow is now exposed as a progressive publication state, for example:

`Provisional — using 46/48 published prices`

The state records the published count, expected count, missing labels, full unknown-slot capacity reserve and automatic replan policy. As additional Octopus prices appear, KEMS rebuilds the plan on its normal refresh cycle. Once every expected settlement period is present, the state automatically becomes complete.

The Home Assistant dashboard includes `sensor.kems_agile_tomorrow_publication_plan` in the Full KEMS Agile forecast evidence.

## Safety boundary

Alpha7.41 does not change the 10% reserve, KH7/inverter limits, export limits, Alpha7.34 latest-safe-start protection or Alpha7.40 economic-opportunity guard. It does not create a FoxESS control path. Real hardware writes remain blocked until commissioning is explicitly completed.
