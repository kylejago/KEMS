# Alpha9.72 — No-export target parity and EV pre-arm

## Purpose

Alpha9.72 closes two defects proven by the 28–29 September 2026 live-control test.

1. The continuously recalculated forecast requirement and the physical No Paid Export cheap-charge target could diverge. The customer-facing forecast required about 51% SOC while the legacy physical path stopped at about 47%.
2. A connected EV could begin drawing during a confirmed cheap period before the live MinSOC hold had armed, allowing one coordinator cycle of battery discharge into the shared home/EV AC bus.

## Target authority

For No Paid Export, `Snapshot.forecast_required_morning_soc_percent` is now the canonical overnight target whenever it is finite and available. That same value is used for:

- the published overnight charge target SOC and kWh,
- the confirmed-cheap physical Control view,
- the existing Force Charge stop decision.

The target remains bounded by the configured battery reserve and 100%.

The previous learned-load No-export target calculation remains available only as a fail-safe fallback when the forecast target is unavailable. Full KEMS / Agile counterfactual optimisation remains separate and unchanged.

This change does not allow Force Charge outside a confirmed cheap period. Tariff confirmation, fresh physical SOC, commissioning, Master enable, site-import headroom, emergency-stop, island and FoxESS Modbus version gates remain authoritative.

## EV pre-arm

During a confirmed cheap period, an EV that is connected but still reporting a fresh 0 kW / not-charging state now pre-arms the existing whole-bus MinSOC hold.

The pre-arm:

- raises only the existing MinSOC-on-grid floor,
- uses the same physical-SOC + 1 percentage-point guard already proven by Alpha9.70,
- preserves an independently safe existing Force Charge request,
- does not claim circuit isolation,
- remains latched while the EV stays connected in the cheap window,
- clears when the EV disconnects or cheap authority ends.

Once Ohme reports active charging, the existing Alpha9.70 site-headroom rebudgeting and whole-bus EV guard continue to apply.

## Hardware scope

Alpha9.72 does **not** add any new write surface.

Still permitted only through the existing reviewed path:

- Self Use,
- confirmed-cheap Force Charge,
- Min SoC-on-grid.

Still blocked:

- deliberate Force Discharge,
- paid/Agile export control,
- import power-limit writes,
- export power-limit writes,
- direct Ohme charging commands,
- automatic Master enable.

## Live evidence motivating the fix

The 28–29 September live trace proved:

- cheap authority activated correctly at 23:30,
- FoxESS entered Force Charge and charged the battery,
- the legacy physical target stopped around 47% while the forecast requirement was around 51%,
- when Ohme began drawing, one scan showed material battery discharge into the EV before MinSOC was raised,
- the next scan correctly moved EV demand to grid and held battery discharge near zero,
- the non-cheap 10% physical MinSOC baseline restored correctly after the cheap window.

Alpha9.72 changes only the two mismatches above and retains the proven safety boundaries.
