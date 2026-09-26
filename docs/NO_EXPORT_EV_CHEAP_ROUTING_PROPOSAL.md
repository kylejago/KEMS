# No-paid-export EV-aware cheap routing — draft simulation proof

Status: DRAFT; do not release or enable live control from this proposal.

## Agreed policy

- Only when export tariff is **No paid export**. Full KEMS paid-export
  simulation and its economic/export routing remain untouched.
- Normal overnight 23:30–05:30: physical SOC **above** resolved target may
  supply genuine household demand down to the target, never intentionally
  discharge or export just to reach it. At/below target, preserve the floor;
  charge towards the forecast target when charging is justified.
- Confirmed extra Intelligent slot: grid covers EV power; battery covers
  genuine home demand when sufficient to reach the next cheap period.
  Only a forecast energy shortfall authorises buying extra cheap energy for
  home support or battery replenishment. No battery/grid export.
- Whenever the EV is charging, its power is assigned to **grid only**. Solar
  first supplies home and may charge battery; it never substitutes for the
  EV's grid-only allocation in this no-export cheap-window proposal.
- The resolved target is a **minimum floor**, not a forced-discharging
  destination. E.g., 80% physical SOC, 60% target, 10% needed for the house:
  ending SOC 70%, with no deliberate export.

## Simulation contract

`kems_core.no_export_cheap_policy.route_no_export_cheap` is a pure, interval
energy-routing allocator used for the no-export current plan and replay.
It deducts measured EV demand **once** from the measured whole-site load;
each interval routes PV, home battery discharge, EV grid, home grid and
optional grid-to-battery energy separately with charge/discharge efficiencies
and 7 kW inverter/battery and 14.5 kW site limits taken from config.
Unknown, stale or inconsistent EV telemetry fails closed: no modelled
battery-to-house discharge or grid charging on an unproven EV/home split.
The normal overnight and confirmed extra slot retain their different
forecast horizons. PV surplus is stored up to actual battery capacity,
then curtailed in this zero-export simulation.

The entire paid-export cheap branch is left independent. Historical no-export
comparison uses this same `SimulationEngine`; historical results may change
because this is a **policy change**, not a retrospective correction.

## Critical live hardware boundary

The KH7 FoxESS Self Use and Force Charge commands currently available to KEMS
cannot independently guarantee "EV grid-only, household battery-only" when
both use the same AC bus. A read-only software flow is **not** proof of
physical separation. The existing Alpha9.67 live write-authority and backend
must not be widened by this draft. No Force Discharge, zero-export-limit
writes, EV control-service actions or uncommissioned power manipulation
are introduced by the allocator.

Before any merge/release, prove the control target remains independently
isolated from the new preview; the current control planner consumes the
SimulationState target. Do not treat this PR as a finished live policy.
Before a subsequent controlled release, add an EV-aware physical actuation
path or another independently verified electrical separation; require fresh
Ohme power, physical KH7 battery/grid/home data, bounded import, mode
readback, no EV-fed-by-battery evidence and safe fail-closed recovery.
Commission on a real EV charge session before permitting hardware writes.

## Acceptance

1. No EV watt is allocated to solar/battery under valid measured conditions.
2. Battery is used for actual house demand only above the forecast floor.
3. No deliberate export or forced discharge; reaching 70% above a 60%
   floor is acceptable when the house no longer needs energy.
4. A genuine extra-slot shortfall permits bounded cheap recharge; an adequate
   SOC does not trigger battery charging or home grid-bypass.
5. Missing/stale EV evidence does not permit a guessed house-only battery
   discharge, nor an extra charging write.
6. Paid-export Full KEMS replay and live control remain exactly unchanged.
7. Tests and independent PR CI must be green on the frozen head, followed by
   a further explicit live-readiness review. No automatic merging or release.
