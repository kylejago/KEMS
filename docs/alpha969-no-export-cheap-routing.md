# Alpha9.69 proposal — No paid export cheap routing

Review-only work, based on Alpha9.68 main at
8663995905d8b272d8d10095eceafc7bf3e6a67a. Do not merge or release
without independent validation and live physical evidence.

## Policy

This routing is selected only when no paid export tariff is active. A confirmed
cheap period is still required. Europe/London local clock 23:30–05:30 is the
scheduled overnight period; a separately confirmed cheap time is an extra
Intelligent slot. An unconfirmed or stale raw Intelligent hint is not authority.

The resolved target is a minimum floor. When SOC exceeds it, solar serves
non-EV household demand first and the battery may serve the remaining house
demand without crossing that floor. Remaining energy is NOT exported or force
discharged to arrive at target. Below the floor, solar may naturally charge the
battery, and bounded cheap grid charging can cover the remaining shortfall.
Surplus PV may naturally charge beyond the floor; the floor is not a solar
charge ceiling.

In an extra slot, battery grid charging additionally requires a valid
forward-demand source and next-cheap deadline. A missing forecast is NOT
permission to charge to 100%. The charger should take confirmed cheap grid
power while sufficiently stored battery energy serves non-EV household load in
the proposed twin.

## EV scope and accounting

KEMS's house_load_kw is the mapped FoxESS Load Power reading where available,
or a distinctly marked simulation-only Octopus demand fallback. The name does
not establish whether the Ohme charging circuit lies inside that measurement.

The collector uses three consecutive, unambiguous independent site-power
balances to record a simulation-only EV/load membership flag. The replay and
current twin use one accounting split:

- Included EV: total site load = observed load; non-EV = load minus Ohme power.
- External EV: total site load = observed load plus Ohme power; non-EV = load.
- Unknown/stale/mismatched: retain observed load as an opaque total, do not
  subtract or add Ohme power, do not attribute an EV-only grid stream, and hold
  battery discharge during that EV snapshot.

EV must not be charged once as part of house load and again as separate site
demand. Paid-export replay and customer Full KEMS comparisons keep their
existing accounting contracts. The new evidence field is not a statement that
the inverter can independently allocate physical AC flows.

## Live scope — conservative by design

The reviewed KH7 interface offers Self Use / Force Charge, force-charge power
and MinSOC-on-grid. These controls alone cannot ensure that Self Use discharges
only into the house when Ohme is simultaneously charging on the same AC bus.

Therefore, while the EV is active in Control mode, the physical MinSOC is held
at least at current fresh physical SOC and battery-to-house intent is zero for
the live command. Proposed simulation/shadow battery-to-house flow must NOT be
described as measured physical flow. The control reason and next action expose
the fallback. Neither Force Discharge nor import/export power-limit writes are
added. Existing write-authority, emergency stop, commissioning, ownership
restoration, grid/island and site-import gates remain in place.

A future live change to enable battery-to-house concurrently with EV charging
requires independently validated Ohme power, site CT and FoxESS battery/grid
power over repeated transitions, documented source membership, a supported
means of enforcing EV grid supply, readback, and confirmed physical energy
balance. Simulation tests or a single balanced snapshot do not provide that
proof. Below-target Force Charge remains subject to the pre-existing
commissioning and live readback gates and is **not** declared hardware-proven.

## Validation / release boundary

Review the focused Alpha9.69 tests, updated Alpha9.60 and Alpha9.67 assertions,
Alpha9.41 paid-export comparison contract and full repository validation.
No implicit Pi, public-web or panel version bump, merge or release.
