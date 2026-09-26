# Alpha9.69 proposal — selective cheap routing with no paid export

## Scope

This proposal is restricted to **No paid export**. Paid-export Full KEMS / Agile
simulation is preserved. A normal 23:30–05:30 cheap window and a *confirmed*
Intelligent extra cheap window use the same forecast SOC **floor**, but the EV
draw is always allocated to grid in the new **digital-twin** flow model.

- The forecast-derived target is a **floor, not a discharge destination**.
  Battery may supply remaining non-EV house load naturally down to the floor.
  No discretionary battery export, Force Discharge, or discharge to chase SOC.
  If house load only consumes 10 percentage points from 80% against a 60%
  target, ending SOC of 70% is correct.
- Solar supplies non-EV house load first; surplus charges the battery. Export
  remains zero in no-paid-export simulation, with residual solar curtailed.
- EV draw is segregated from combined FoxESS site load and allocated to grid.
  Unknown or stale EV power must not be assigned to battery-to-home.
- If SOC is below the forecast target, confirmed cheap electricity may refill
  the deficit subject to available charge power, 14.5 kW site-import headroom
  (when configured), and solar contribution. Above target: no grid charging.
- Extra Intelligent slots are eligible only under the existing multi-signal
  confirmation; an unconfirmed raw slot cannot authorise grid charging.
- The current-day flow model and historical no-export replay use the same
  routing helper; no-export flow must not alter paid-export behaviour.

## Critical hardware boundary

**The simulator's EV-only grid routing is not physical proof.** FoxESS Self Use
currently sees combined site demand and the available Alpha9.68 live commands
are Work Mode, Force Charge power and Min SoC-on-grid. Those controls cannot
selectively discharge the battery to only the house while independently
guaranteeing that an EV charger on the same site draws only from grid.

This branch therefore adjusts the *physical* MinSOC floor to the forecast
target only when EV is **not charging**. While EV is charging and physical SOC
is already at/above target, the live planner conservatively holds physical SOC,
so it cannot discharge the battery into EV load. The consequence is that the
non-solar house load can also be supplied from grid. This is an acknowledged
temporary deviation, **not** a claim of successful EV-only hardware routing.

Physical EV-only routing requires an separately reviewed, telemetry-backed
control strategy, hardware/service boundary, and failure tests before the
digital-twin claim can become a live-control promise. Do not weaken existing
master enable, commissioned-state, SOC freshness, EPS/island, tariff corroboration,
readback/ownership or emergency-stop gates. Do not enable Force Discharge or
import/export-limit writes by implication.

## Validation and release

Keep this change as a **draft PR** until CI, no-export replay/accounting parity,
paid-export comparison, and EV hardware isolation readiness are reviewed.
Do not publish or deploy a new KEMS HA release, update Pi/Public Web, or flash
the panel solely on the strength of simulation tests. Before any physical test,
verify Master remains under user control and that cheap-window Force Charge
still depends on fresh physical SOC and a confirmed cheap tariff window.
