# KEMS 0.7.0-alpha7.31 — Agile solar-aware inverter headroom

Alpha7.31 fixes the first genuine non-zero Agile export failure observed in the Alpha7.30 diagnostic at 16:00 BST on 19 August 2026.

## What the proof exposed

The bounded-partial optimiser selected a 7.000 kW battery export target while the proposal solar model was producing 2.631 kW. The independent safety validator correctly rejected the candidate because Alpha7.24 normalised the shared KH7 AC output to 7.778 kW against the configured 7.000 kW inverter limit.

The strict candidate-applied replay also proved that the raw battery target could not physically fit inside the shared inverter envelope.

## Alpha7.31 routing rule

When battery discharge is active, KEMS now applies one physical routing rule consistently across dispatch, shadow proof and the current-routing dashboard:

1. Feed-in First routes available solar to AC before battery discharge.
2. Solar-to-battery is zero while the battery is discharging.
3. Routed solar AC consumes inverter capacity first.
4. Battery-to-home remains first priority for the remaining battery headroom.
5. Deliberate battery export receives only the battery/inverter/export headroom that remains.
6. The optimiser-facing battery target itself is reduced before a shadow command is built; the safety adapter does not silently clip an unsafe command into a pass.

For the 16:00 proof snapshot:

- solar generation: 2.631 kW
- house demand: 0.778 kW
- inverter limit: 7.000 kW
- battery inverter headroom: 4.369 kW
- battery → export: 4.369 kW
- solar → home: 0.778 kW
- solar → export: 1.853 kW
- total grid export: 6.222 kW
- total KH7 AC output: 7.000 kW

That is the physically coherent replacement for the rejected 7.000 kW battery-export request.

## Scope

Alpha7.31 patches the shared Alpha7.17 dispatch-target function, so both complete-horizon dispatch and Alpha7.28 bounded-partial dispatch use the same solar-aware inverter headroom. It also updates the Alpha7.24/7.25 shadow routing evidence and Alpha7.30 current-routing snapshot to use the same Feed-in First model.

Alpha7.28 price-horizon qualification, the reserved unknown-slot capacity, 10% minimum SOC, configured 7 kW battery/export limits, strict 0.01 kW non-zero replay and the independent 13-point safety validator remain authoritative.

Real FoxESS hardware writes remain blocked.
