# KEMS Alpha7.40 — Agile-first coordinated release

Alpha7.40 makes **Full KEMS Agile** the flagship KEMS strategy while preserving Live Data, Battery & Solar and Full KEMS as evidence-backed comparison products.

## Optimiser

- Add a proactive economic opportunity guard on top of the proven rolling planner and Alpha7.34 latest-safe-start guard.
- Move already-exportable battery energy into stronger current Agile slots when waiting would force part of that energy into cheaper later slots or leave too little forecast/headroom margin.
- Replan every coordinator scan from the latest simulated SOC, house demand, solar evidence and available Agile prices.
- Preserve the 10% pre-cheap target, shared inverter limit, export limit, discharge limit, house-first priority and negative-price protections.
- Keep real FoxESS writes hard-blocked pending commissioning.

## Agile accuracy / observability

The Full KEMS Agile workspace is the primary diagnostic surface and must expose, where evidence exists:

- live house, solar, battery, grid import/export and SOC
- current and remaining Agile prices
- current routing and today cumulative routing
- solar → home / battery / export
- grid → home / battery
- battery → home / export
- curtailment/clipping/export-limit loss where determinable
- planned battery export by remaining settlement period
- actual/current/forecast SOC trajectory
- latest-safe and guarded-latest-safe start
- economic-opportunity guard and the price advantage that caused it
- price-horizon completeness and missing intervals
- observed vs forecast/reconstructed evidence labelling
- house/solar forecast error and confidence as evidence accumulates

## Strategy comparison

Compare becomes a larger decision page across the four user-facing products:

- Live Data
- Battery & Solar
- Full KEMS
- Full KEMS Agile

It should show:

- recommendation to next configured cheap-period boundary
- today projected outcome
- yesterday / 7-day / 30-day / available long-term evidence
- common bill basis: import cost minus export income
- import/export energy and income
- solar utilisation and battery routing
- end SOC / battery throughput
- savings vs Live Data
- strategy win rate and evidence coverage
- cumulative historical cost/savings
- an explainable `why this strategy won` decomposition

Incomplete, reconstructed and model-only periods must remain visibly labelled and must not silently receive the same confidence as complete measured evidence.

## Coordinated platform scope

Pair Alpha7.40 with KEMS Web.20 so the Pi/property dashboard and seven-day-delayed public demo present the same Agile-first comparison model. Retain the canonical KEMS brand and LAN-only Pi-management security boundary.
