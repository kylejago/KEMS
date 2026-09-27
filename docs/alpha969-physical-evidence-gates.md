# Alpha9.69 — physical evidence and commissioning gates

Status: physical commissioning protocol for a **future expanded live routing**
change. The Alpha9.69 candidate publishes only simulation, read-only evidence
and an independently visible shadow proposal while preserving Alpha9.68 live
cheap charging. Merging that narrower release never grants new write authority.
This document does not request anyone to operate the inverter. Use an
appropriately qualified installer for controlled electrical/inverter validation
and follow FoxESS/Ohme operating instructions.

## Confirmed topology and existing evidence

Owner-confirmed: grid and inverter feed the EPS/changeover equipment; its
output runs to Henley blocks supplying both the main and EV consumer units.
House and EV therefore share the downstream AC supply. There is no dedicated
KH7 output for the EV in the known topology; **do not request another wiring
diagram or promise physical circuit-by-circuit source isolation**. The
installation's EPS changeover, island protection and EV load-shedding design
still need their own protective readback/installer validation before changing
island behaviour.

KEMS already records Ohme status/power, FoxESS Load/PV/battery/grid readings,
SOC, tariff evidence and source ages. Use those sources, its existing
EV-membership inference and retained snapshots; do not request duplicate
manual data entry. Retained snapshots are sampled every 300 seconds; faster
charge-start/stop evidence may need a bounded read-only event capture or HA
history. Prior physical Alpha9.59 testing already verified a bounded 7 kW
Force Charge request, about 6.8 kW observed battery charge and about 8.1 kW
site import, with Self Use/MinSOC restoration. The distinct **target-limited
below-floor sequence and simultaneous EV/house power allocation** still need
measured validation.

## Non-negotiable separation

1. A confirmed cheap tariff proves the **price window**, not the physical
   origin of electricity feeding the charger.
2. Three consistent site-balance observations can support whether Ohme power is
   inside or outside FoxESS Load Power. They do **not** prove that a KH7 work
   mode can constrain total shared-bus inverter output so the measured grid
   import supplies the equivalent EV demand.
3. A desired ControlState `Force Charge`, `Self Use` or MinSOC is not evidence
   that the physical inverter followed that request. This PR blocks writes
   using `alpha969_routing_shadow_only`, which persists through downstream
   Happy Hour overlays.
4. Existing Alpha9.67 bounded live authority, if separately enabled, is not
   expanded by this PR. No Force Discharge, import/export limit, direct Ohme
   control or new FoxESS service writes are proposed here.

## Automatic read-only shared-bus balance audit

The collector now saves `shared_bus_ev_audit` on each KEMS snapshot, exposes
the latest result through the **EV shared-bus allocation audit** diagnostic
sensor and includes it in KEMS diagnostics. It uses **existing** Ohme,
FoxESS and grid measurements: no extra user mapping or duplicate power
sensors. Ohme power report age is retained and samples older than 90 seconds
are excluded. The three-sample EV/load membership classifier likewise clears
its evidence when Ohme is old or a required physical input is stale.

An actively charging EV is assessed only when the measured load boundary is
identified, every required power reading is finite and carries acceptable
freshness, and the no-paid-export policy applies. The audit compares observed
battery discharge with non-EV residual home demand after solar and compares
grid import with EV power after giving any surplus PV credit. It reports
`net_allocation_consistent`, `deviation`, `unavailable`, `idle` or
`not_applicable`, plus the separate measured quantities and a *candidate*
inverter site-output ceiling. The comparison is **not** electrical isolation
proof, closed-loop control, a Force Discharge setpoint or a safety interlock.
Neither a single green snapshot nor three measurement-membership samples
authorise physical KH7 writes.

KEMS's normal retained history is a five-minute observation series; audit
readouts update each coordinator scan and are retained at that sampling
interval. Pre-upgrade snapshots have no Ohme report-age or shared-bus audit,
so historical evidence cannot be retroactively declared verified. For
short transitions, a future read-only event trace may be required, using the
same mapped KEMS sources and recording actual work-mode/MinSOC readbacks.

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
Do not claim a physically segregated EV source from a successful
measurement classification. On a shared bus, validate **net allocation**:
site import at least the equivalent verified Ohme load while KH7 output is
limited to independently verified non-EV demand. For example, with 1 kW
non-EV home demand, 7 kW EV demand and no PV, 1 kW KH7 output plus 7 kW
net grid import meets the proposed accounting objective. It does not prove
which individual AC circuit receives which electrons; charging the battery
or adding PV requires separately balanced accounting and import headroom.

## Stage-gate matrix (no enabling in this PR)

| Situation | Proposed observable behavior | Evidence required before any future write-authority PR |
| --- | --- | --- |
| Overnight, SOC above floor, EV idle | PV to home first; available battery to non-EV house, hold floor | Fresh physical SOC, house/load scope, grid/CT balance across load changes; no forced discharge to target |
| Overnight, SOC at floor | Hold battery floor; home may use grid | SOC and MinSOC readback after transitions; no accidental below-floor discharge |
| Overnight, SOC below floor | Request only shortfall in shadow | Separate controlled proof that Force Charge responds, respects limits and stops on fresh target readback |
| Extra confirmed Intelligent slot | Grid allocation for EV; protect future house forecast | Independent tariff confirmation, valid end/deadline, fresh EV and grid evidence, measured shared-bus import/Ohme balance and a proven KH7 output constraint (not inferred from twin) |
| EV active or status/power unknown | Hold physical SOC in proposed live fallback | Measured charger/house/battery/grid balance at charge start and stop; loss of either Ohme or CT must fail closed |
| Solar surplus | Solar to house then natural battery charge, no paid export | CT/import/export readings and inverter readback; include PV and battery charge in measured site balance; never infer circuit isolation |
| Slot end, tariff stale/unconfirmed, grid outage or Power Down | Existing higher-priority safety/Power Down authority takes precedence | Repeat readback/restore/fail-safe checks without relying on merely planned flow values |

For each proposed test, record configured import limit, inverter and charge
limits, charge/discharge efficiency, SOC and target before/after, and differences
between measured and predicted flows. A theoretical split or passing simulator
test does not satisfy the future hardware gate.

## Stop conditions and release boundary

Stop the physical exercise if source freshness, charger state, CT direction,
MinSOC/charge-mode readback or required site-grid/EV balance cannot be established; if
grid import exceeds the configured safe limit; if battery SOC crosses its
intended floor; or if unexpected export, island operation or a safety/Power
Down priority conflict occurs. Record the observed outcome rather than
adjusting the algorithm to assume a success.

Before a future **separate** live-authority change: collect a retained physical
evidence pack, explicitly identify which KH7 controls can limit shared-bus
output and achieve the verified grid-import/EV allocation, have the installer
review failure behavior,
add boundary/transition regressions, and re-run exact-head CI and manual
readback validation. If KH7 cannot enforce the split, preserve the conservative
EV-active hold-SOC fallback rather than asserting an unachievable independent
EV circuit supply.

For the Alpha9.69 **shadow-only** PR, merge/release only after the existing
live charging planner is preserved and independently tested, release identity
is correct and all exact-head checks pass. No unproven new KH7 commands become
live as a result; require a separate future PR for any expanded authority.
