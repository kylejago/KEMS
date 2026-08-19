# KEMS 0.7.0-alpha7.34 — deadline prevention and overnight-only cheap control

Alpha7.34 is a safety/policy layer on top of the proven Alpha7.31 Agile dispatch baseline.

## Latest-safe-start guard

Agile Smart Export still ranks export opportunities by value while there is physical slack. On every coordinator scan KEMS now works backwards from the next configured overnight cheap start and calculates how much AC battery energy must leave the battery to reach the normal 10% target.

Remaining discharge capacity is integrated in five-minute segments. The model respects the configured battery/inverter limits and derates battery headroom for proposal/forecast solar because Feed-in First gives solar the shared inverter AC path first.

KEMS exposes:

- required discharge energy to the target
- solar-aware remaining discharge capacity
- remaining deadline margin
- latest safe export start
- guarded latest safe start
- whether the target is still physically reachable
- approximate half-hour slots that can still be skipped
- whether forecast solar was used in the capacity model

A 10-minute guard opens before the calculated latest safe start. Once active, KEMS stops gambling remaining discharge capacity on a later export price and requests the full currently-safe battery path. If the target is already physically unreachable, the existing maximum-discharge fallback remains active.

The independent safety/shadow pipeline, 7 kW shared inverter ceiling, 10% minimum SOC, candidate-applied replay and hardware-write block remain authoritative.

## Overnight-only cheap control

Alpha7.34 removes Octopus Intelligent/extra-dispatch slots from KEMS cheap-control decisions.

The configured overnight window (currently 23:30–05:30 by default) is the only period that can:

- mark KEMS `off_peak` for control
- trigger planned battery/grid charging
- define the next cheap deadline used by export pacing
- move the next overnight recharge boundary

Live import/export prices can still be observed for truthful accounting, but a daytime cheap price, Intelligent slot, EV charging state, or live extra-slot timestamp cannot make KEMS charge the battery or reclassify that period as its cheap control window.

The legacy `intelligent_slots_enabled` option is retained only for config-entry compatibility and is ignored by the runtime; new defaults set it to false.

## Hardware scope

This release remains simulation/shadow-only for inverter writes. FoxESS commissioning is unchanged. Alpha ESS preparation is limited to the vendor-neutral backend contract in `docs/hardware-backend-contract.md`; no Alpha ESS writes are implemented before FoxESS live control is proven.
