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

## Shared-bus topology and evidence

The owner has confirmed that grid and inverter feed EPS/changeover equipment,
then the Henley blocks supply both main and EV consumer units. The load sources
are on a shared downstream AC bus. We can use KEMS's existing Octopus, Ohme,
FoxESS and retained history; no repeat wiring diagram or manual transcription
of KEMS dashboard power figures is required.

The intended grid-to-EV and battery-to-house split is a **measured net-power
allocation** on that bus, not an electrically segregated supply. For an EV at
7 kW and non-EV house demand of 1 kW with no PV or battery charging, about
1 kW inverter output and about 7 kW grid import would be the target
allocation. The actual KH7 output must be constrained and verified against
fresh Ohme and grid/CT data; Self Use alone can discharge battery into EV
demand on the shared bus. If bounded output control is unavailable or
unproven, hold fresh physical SOC during EV charging instead. EPS/island
protection and EV shedding must not depend solely on cloud Ohme response.

Prior live Alpha9.59 evidence already established bounded confirmed-cheap
Force Charge, measured battery charge/grid import and mode/MinSOC restoration.
The new target-limited below-floor sequence, simultaneous EV dispatch and
transitions still require their own readback evidence, not a duplicate basic
Force Charge trial. KEMS's retained history records at five-minute intervals;
a short read-only charging transition capture may be needed for time alignment.

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

## No-export daily accounting and forecast authority

The EV/non-EV split also applies to the no-export replay outside cheap time:
the proposed battery only supplies non-EV house demand; measured EV demand
remains a separate grid allocation. Included EV is subtracted once; external EV
is added once to whole-site demand. Where membership is unavailable, do not
attribute an EV-only grid stream or discharge the battery in the replay. Daily
EV-grid attribution is nullable rather than silently reporting an invented zero.
The observed-import fallback likewise uses full verified site demand when
FoxESS grid import is missing. All of these changes are scoped to No paid
export, not the paid-export comparison contract.

The generic learned load profile can include charging demand. Once EV use
appears in the retained day's records, the no-export protective forecast uses
recent *verified non-EV* samples, not the generic learned whole-site estimate.
If non-EV source evidence is unavailable, the forecast is unavailable; missing
forecast/deadline must not authorise extra-slot grid charging. This does not
retroactively establish the EV contribution to older learned profiles; future
model refinements can provide explicitly segregated long-term house learning.

Current power-flow fields distinguish total site load, non-EV household load,
and the EV grid allocation. These are **proposed simulation allocations**,
not direct measurement of the origin of power at individual AC circuits.

## Home Assistant observability

The existing simulation sensor attributes now show the optional daily EV grid
allocation (nullable when any interval cannot be attributed), live simulated
whole-site/non-EV house/EV grid streams, cheap-period kind, EV scope proof flag
and its reason. The scope proof is a **simulation load-measurement classification**,
not a demonstration of where physical EV electricity originates.

Two binary sensors distinguish `Alpha9.69 routing shadow-only` (the sticky
no-hardware-authority flag on the control plan) from
`No-export EV load measurement scope identified` (the read-only measurement
split). The simulation sensor reports
`no_export_ev_isolation_physically_proven: false` for this candidate.
Existing control blocked-reason and next-action sensors explain why the new
proposed work-mode/MinSOC must not be sent to FoxESS. These are diagnostic
readouts only; they are not extra write entities or a commissioning bypass.

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

**Explicit release gate:** the pre-existing Alpha9.67 write-authority contract
can otherwise turn a new Alpha9.69 Force Charge plan into a hardware command
with only the older commissioning checks. Alpha9.69 therefore adds a fail-closed
rule in `assess_foxess_control_write_authority` using the dedicated
`alpha969_routing_shadow_only` state flag, with the
`no_export_overnight*` and `no_export_extra_slot*` reasons as additional
defence. The flag survives downstream `dataclasses.replace` overlays such as
Happy Hour, which replaces the operating reason and charge request. This applies
to both new Self Use and Force Charge intent, including the EV fallback. They
remain available for shadow/replay, but the existing backend must release its
owned state rather than issue their unvalidated work-mode/MinSOC writes.
Previously reviewed Alpha9.67 commands retain their older authority when
their existing conditions hold. A future live enablement requires a separate,
reviewed proof-and-authority change, not merely changing the operating mode or
turning on Master Control.

A future live change to enable battery-to-house concurrently with EV charging
requires independently validated Ohme power, site CT and FoxESS battery/grid
power over repeated transitions, documented source membership, a supported
means of limiting KH7 output to non-EV demand while confirming equivalent
EV grid import, readback, and a measured whole-site energy balance. Simulation tests or a single balanced snapshot do not provide that
proof. Below-target Force Charge in the new Alpha9.69 route is **not authorised to
write** and is **not** declared hardware-proven. The old Alpha9.67 charging
route retains only its existing reviewed bounded authority.

## Validation / release boundary

Review the focused Alpha9.69 tests, updated Alpha9.60 and Alpha9.67 assertions,
Alpha9.41 paid-export comparison contract and full repository validation.
No implicit Pi, public-web or panel version bump, merge or release.
