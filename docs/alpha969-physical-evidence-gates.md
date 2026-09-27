# Alpha9.69 — physical evidence and commissioning gates

Status: **proposed evidence protocol only**. Alpha9.69 remains a draft, shadow-only
routing change. This document does not grant write authority or request anyone
to operate the inverter. Use an appropriately qualified installer for controlled
electrical/inverter validation and follow FoxESS/Ohme operating instructions.

## Non-negotiable separation

1. A confirmed cheap tariff proves the **price window**, not the physical
   origin of electricity feeding the charger.
2. Three consistent site-balance observations can support whether Ohme power is
   inside or outside FoxESS Load Power. They do **not** prove that a KH7 work
   mode can route battery power exclusively to home loads while the EV is active.
3. A desired ControlState `Force Charge`, `Self Use` or MinSOC is not evidence
   that the physical inverter followed that request. This PR blocks writes
   using `alpha969_routing_shadow_only`, which persists through downstream
   Happy Hour overlays.
4. Existing Alpha9.67 bounded live authority, if separately enabled, is not
   expanded by this PR. No Force Discharge, import/export limit, direct Ohme
   control or new FoxESS service writes are proposed here.

## Passive evidence capture — no KEMS hardware writes

Capture the same timestamp/window for each item:
- Octopus confirmed tariff state, scheduled overnight vs extra Intelligent
  dispatch evidence, slot start/end and freshness.
- Ohme connected/charging status, charger power and freshness.
- FoxESS Load Power, PV power, battery power with confirmed sign convention,
  battery SOC, grid import, grid export, and source freshness.
- Independent site/CT or meter evidence where available, and the actual
  inverter work-mode, MinSOC and charge-power readbacks.
- KEMS no-export simulated total load, non-EV house load, EV-grid allocation,
  evidence reason, desired battery/house/grid flows and the sticky shadow-only
  flag.

Compare both hypotheses independently for at least three fresh, consecutive
samples in each stable phase: `site = load` versus
`site = load + Ohme`. Reject missing, stale, mismatched or ambiguous
samples. The existing candidate classifier uses a 0.40 kW minimum / 6%
site-balance tolerance, but its verdict is **measurement membership only**.
Require observations of **EV idle, plug-in, charge start, steady charge,
charge stop and unplug**. A flag observed only while idle is not EV-scope proof.
Keep the physical EV-origin claim explicitly *unproven* regardless of a
successful measurement classification.

## Stage-gate matrix (no enabling in this PR)

| Situation | Proposed observable behavior | Evidence required before any future write-authority PR |
| --- | --- | --- |
| Overnight, SOC above floor, EV idle | PV to home first; available battery to non-EV house, hold floor | Fresh physical SOC, house/load scope, grid/CT balance across load changes; no forced discharge to target |
| Overnight, SOC at floor | Hold battery floor; home may use grid | SOC and MinSOC readback after transitions; no accidental below-floor discharge |
| Overnight, SOC below floor | Request only shortfall in shadow | Separate controlled proof that Force Charge responds, respects limits and stops on fresh target readback |
| Extra confirmed Intelligent slot | Grid allocation for EV; protect future house forecast | Independent tariff confirmation, valid end/deadline, fresh EV and grid evidence, physical isolation capability (not inferred from twin) |
| EV active or status/power unknown | Hold physical SOC in proposed live fallback | Measured charger/house/battery/grid balance at charge start and stop; loss of either Ohme or CT must fail closed |
| Solar surplus | Solar to house then natural battery charge, no paid export | CT/import/export readings and inverter readback; never invent EV isolation from PV routing |
| Slot end, tariff stale/unconfirmed, grid outage or Power Down | Existing higher-priority safety/Power Down authority takes precedence | Repeat readback/restore/fail-safe checks without relying on merely planned flow values |

For each proposed test, record configured import limit, inverter and charge
limits, charge/discharge efficiency, SOC and target before/after, and differences
between measured and predicted flows. A theoretical split or passing simulator
test does not satisfy the future hardware gate.

## Stop conditions and release boundary

Stop the physical exercise if source freshness, charger state, CT direction,
MinSOC/charge-mode readback or expected isolation cannot be established; if
grid import exceeds the configured safe limit; if battery SOC crosses its
intended floor; or if unexpected export, island operation or a safety/Power
Down priority conflict occurs. Record the observed outcome rather than
adjusting the algorithm to assume a success.

Before a future **separate** live-authority change: collect a retained physical
evidence pack, explicitly identify which KH7 controls actually enforce
EV-grid/home-battery separation, have the installer review failure behavior,
add boundary/transition regressions, and re-run exact-head CI and manual
readback validation. If KH7 cannot enforce the split, preserve the conservative
EV-active hold-SOC fallback rather than asserting physical EV-grid routing.

For **this PR**, remain draft and do not merge/release merely on green CI.
