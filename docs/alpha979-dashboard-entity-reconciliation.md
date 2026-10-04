# Alpha9.79 — managed dashboard entity reconciliation

## Purpose

Remove customer-facing **Entity not found** cards caused by stale entity IDs in the
managed KEMS Master and ROI dashboards.

The live Alpha9.78 diagnostic proved the underlying data remained available. The
defect was presentation drift between dashboard YAML and the current KEMS entity
surface.

## Reconciled references

The managed dashboards now use the currently registered entities for:

- lifetime gas consumption;
- lifetime net energy cost;
- paid export income since commissioning;
- solar generation since commissioning;
- grid import since commissioning;
- grid export since commissioning;
- house electricity since commissioning; and
- simulated battery charged today.

The obsolete `sensor.kems_agile_rolling_export_plan` dependency is removed.
The KEMS-plan overview derives the current action directly from the existing
`sensor.kems_agile_slots` current-slot payload.

## Observed solar today

Alpha9.79 adds a first-class **Observed solar generation today** sensor. It uses
the canonical `SimulationState.actual_solar_generation_kwh` value already used
by current-day accounting, so the Live Data dashboard no longer has to reference
a missing entity or hide the value inside another sensor attribute.

## Regression protection

A new regression contract:

1. rejects every stale entity ID observed in the live dashboards;
2. requires all reconciled entity IDs to appear in the managed dashboard source;
3. proves the new observed-solar-today sensor is registered; and
4. audits explicit KEMS entity references in the managed Master/ROI dashboard
   sources against KEMS entity declarations.

The packaged Master dashboard must also remain byte-identical to its repository
source.

## Safety boundary

This is an entity-surface and presentation/reporting release only.

It does not change:

- FoxESS control or write authority;
- EV control or EV SOC synchronisation;
- tariff/Intelligent-slot authority;
- optimiser or export planning;
- commissioning gates;
- emergency/island behaviour; or
- hardware command scope.
